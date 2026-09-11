"""Cloisonnement du back-office par syndicat.

Wagtail ne passe le queryset d'un SnippetViewSet qu'à la vue index
(`get_index_view_kwargs`, wagtail/snippets/views/snippets.py). Tous les autres
écrans — édition, suppression, copie, historique, dépublication, révisions,
prévisualisation — relisent l'objet par sa clé primaire sans aucun filtre, et
plusieurs appellent même `get_object_or_404(self.model, pk=…)` en dur.

Le cloisonnement est donc posé là où *toutes* les vues d'un viewset passent :
`ViewSet.construct_view`. Énumérer les attributs `*_view_class` aurait été un
inventaire à maintenir — donc à oublier — alors que Wagtail en ajoute à chaque
version.
"""
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404

from wagtail.snippets.views.chooser import SnippetChooserViewSet

from .site_context import get_current_site, scope_qs, scope_qs_slug


class MixinObjetCloisonne:
    """Refuse de servir un objet hors du périmètre du syndicat courant.

    Le contrôle porte sur la ligne en base et non sur l'instance reçue : un
    objet reconstruit depuis une révision reste jugé sur son enregistrement
    réel.
    """

    _viewset_cloisonne = None

    def get_object(self, *args, **kwargs):
        # Signatures hétérogènes selon les vues : get_object(self) pour les
        # écrans bâtis sur BaseObjectMixin, get_object(self, queryset=None)
        # pour ceux qui viennent de Django.
        objet = super().get_object(*args, **kwargs)
        # Création, ou prévisualisation d'un objet pas encore enregistré :
        # il n'y a rien à cloisonner.
        if objet is None or not getattr(objet, 'pk', None):
            return objet
        perimetre = self._viewset_cloisonne.get_queryset(self.request)
        if not perimetre.filter(pk=objet.pk).exists():
            if not self._basculer_vers_le_syndicat_de(objet):
                raise Http404("Contenu hors du périmètre de votre syndicat.")
        return objet

    def _basculer_vers_le_syndicat_de(self, objet):
        """Bascule le CMS sur le syndicat de l'objet, si l'utilisateur y a droit.

        Arnaud, 11/09/2026 : une 404 muette en ouvrant un article de la conf,
        parce que son site courant était resté sur le STUCS. Le contenu
        existait ; seul le sélecteur était ailleurs. Et tout lien « Modifier »
        mène à cet écran (`ArticlePage` y renvoie lui-même) : le piège se
        refermait à chaque changement de syndicat.

        La règle d'accès n'est pas nouvelle : c'est `get_available_sites`, la
        liste que propose déjà le sélecteur — tous les syndicats pour un
        superutilisateur ou un rédacteur en chef, le sien seul pour un
        rédacteur. Le cloisonnement des rédacteurs est donc intact : pour eux,
        l'objet du voisin reste une 404.
        """
        from django.contrib import messages
        from .site_context import get_available_sites, set_current_site

        syndicat = self._viewset_cloisonne.syndicat_de(objet)
        if syndicat is None:
            return False
        if not get_available_sites(self.request).filter(pk=syndicat.pk).exists():
            return False
        set_current_site(self.request, syndicat.pk)
        if not self._viewset_cloisonne.get_queryset(self.request).filter(pk=objet.pk).exists():
            return False
        messages.info(self.request,
                      f"« {objet} » appartient à {syndicat.title} : "
                      f"le CMS a basculé sur ce syndicat.")
        return True


class MixinFormulaireCloisonne:
    """Verrouille le champ « syndicat » du formulaire.

    Le cloisonnement en lecture empêche d'ouvrir le contenu du voisin ; il
    n'empêche pas d'en *créer* chez lui, le champ de rattachement étant libre
    dans le formulaire et forgeable dans le POST. D'où les deux gardes : le
    champ est borné et masqué à l'affichage, et réécrit à l'enregistrement.
    """

    _viewset_cloisonne = None

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        self._viewset_cloisonne.verrouiller_champ_syndicat(form, self.request)
        return form

    def form_valid(self, form):
        # L'écran de suppression passe un simple formulaire de confirmation,
        # sans instance : il n'y a alors rien à estampiller.
        if hasattr(form, 'instance'):
            self._viewset_cloisonne.imposer_syndicat(form.instance, self.request)
        return super().form_valid(form)


class MixinSelecteurCloisonne:
    """Borne un sélecteur de snippet au syndicat courant.

    Le sélecteur est un viewset distinct : le cloisonnement des écrans
    d'édition ne l'atteint pas. Sans lui, un rédacteur parcourt et retient le
    contenu des autres syndicats — les articles qu'il met dans sa newsletter,
    par exemple. Le périmètre est relu sur le viewset du modèle, donc aucune
    déclaration supplémentaire n'est nécessaire.
    """

    def _perimetre(self):
        return self.model_class.snippet_viewset.get_queryset(self.request)

    def get_object_list(self):
        return self._perimetre()

    def get_object(self, pk):
        # Hors périmètre : DoesNotExist, que la vue traduit en 404.
        return self._perimetre().get(pk=pk)

    def get_objects(self, pks):
        return self._perimetre().filter(pk__in=pks)


class SelecteurCloisonne(SnippetChooserViewSet):
    """Sélecteur dont toutes les vues sont bornées au syndicat courant."""

    _METHODES = ('get_object_list', 'get_object', 'get_objects')

    def construct_view(self, view_class, **kwargs):
        if any(hasattr(view_class, nom) for nom in self._METHODES):
            view_class = type(
                f'{view_class.__name__}Cloisonne',
                (MixinSelecteurCloisonne, view_class),
                {},
            )
        return super().construct_view(view_class, **kwargs)


class ViewSetCloisonne:
    """À placer AVANT SnippetViewSet dans les bases d'un viewset.

    `cloisonnement` déclare le périmètre une seule fois, et sert aussi bien la
    liste que les écrans qui lisent par clé primaire :

        ('fk',   'site')            clé étrangère vers SectionPage
        ('fk',   'article__site')   traversée de relation
        ('slug', 'section_slug')    slug Wagtail *ou* slug hérité de WordPress
        ('pk',   None)              l'objet est le syndicat lui-même
    """

    cloisonnement = None

    # Le sélecteur de SectionPage fait exception : MenuItem.target_site s'en
    # sert pour créer des liens vers les AUTRES syndicats, ce qui est le but.
    chooser_viewset_class = SelecteurCloisonne

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.cloisonnement is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} doit déclarer `cloisonnement` : sans "
                "cette déclaration, ses écrans seraient ouverts aux rédacteurs "
                "des autres syndicats."
            )

    def get_queryset(self, request):
        """Périmètre visible. Ne retourne jamais None (contrairement au défaut
        de SnippetViewSet) : les écrans par pk s'en servent pour arbitrer."""
        mode, champ = self.cloisonnement
        qs = self.model._default_manager.all()
        if mode == 'slug':
            return scope_qs_slug(qs, request, slug_field=champ)
        if mode == 'pk':
            # L'objet EST la SectionPage : Django résout l'instance passée à
            # filter() en sa clé primaire.
            return scope_qs(qs, request, site_field='pk')
        return scope_qs(qs, request, site_field=champ)

    def syndicat_de(self, objet):
        """SectionPage à laquelle l'objet est rattaché, ou None.

        Lu d'après la même déclaration `cloisonnement` que le périmètre, pour
        qu'une nouvelle forme de rattachement n'ait qu'un endroit à décrire.
        """
        from django.db.models import Q
        from .models import SectionPage

        mode, chemin = self.cloisonnement
        if mode == 'pk':
            return SectionPage.objects.filter(pk=objet.pk).first()
        if mode == 'slug':
            slug = getattr(objet, chemin, '') or ''
            if not slug:
                return None
            # Slug Wagtail ou slug hérité de WordPress, comme `slugs_contenu`.
            return SectionPage.objects.filter(Q(slug=slug) | Q(legacy_site_slug=slug)).first()
        cible = objet
        for maillon in chemin.split('__'):
            cible = getattr(cible, maillon, None)
            if cible is None:
                return None
        return cible if isinstance(cible, SectionPage) else None

    # ── Verrouillage du champ de rattachement au syndicat ────────────────────

    def champ_syndicat(self):
        """Champ du modèle qui porte le rattachement, déduit du cloisonnement.

        Pour `article__site`, c'est `article` : le rattachement passe par un
        objet intermédiaire, qu'on borne au lieu de le masquer.
        """
        mode, chemin = self.cloisonnement
        return None if mode == 'pk' else chemin.split('__')[0]

    def _syndicat_a_imposer(self, request):
        """SectionPage à forcer, ou None si l'utilisateur a le choix."""
        from content.admin_utils import is_chef
        if is_chef(request.user):
            return None
        return get_current_site(request)

    def verrouiller_champ_syndicat(self, form, request):
        champ = self.champ_syndicat()
        if not champ or champ not in form.fields:
            return
        current = self._syndicat_a_imposer(request)
        if current is None:
            return
        mode, chemin = self.cloisonnement
        f = form.fields[champ]
        if '__' in chemin:
            # Le rattachement passe par un autre objet (un commentaire tient au
            # syndicat par son article) : borner le choix, pas le supprimer.
            f.queryset = f.queryset.filter(**{chemin.split('__', 1)[1]: current})
        elif mode == 'slug':
            f.initial = current.slug
            f.required = False
            f.widget = forms.HiddenInput()
        else:
            from .models import SectionPage
            f.queryset = SectionPage.objects.filter(pk=current.pk)
            f.initial = current.pk
            f.widget = forms.HiddenInput()

    def imposer_syndicat(self, instance, request):
        """Dernier mot côté serveur : le champ masqué reste forgeable."""
        mode, chemin = self.cloisonnement
        if mode == 'pk' or '__' in chemin:
            return
        current = self._syndicat_a_imposer(request)
        if current is None:
            return
        setattr(instance, chemin, current.slug if mode == 'slug' else current)

    def construct_view(self, view_class, **kwargs):
        bases = []
        if hasattr(view_class, 'get_object'):
            bases.append(MixinObjetCloisonne)
        if hasattr(view_class, 'get_form'):
            bases.append(MixinFormulaireCloisonne)
        if bases:
            view_class = type(
                f'{view_class.__name__}Cloisonne',
                (*bases, view_class),
                {'_viewset_cloisonne': self},
            )
        return super().construct_view(view_class, **kwargs)
