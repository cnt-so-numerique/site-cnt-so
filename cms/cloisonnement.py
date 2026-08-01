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
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404

from .site_context import scope_qs, scope_qs_slug


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
            raise Http404("Contenu hors du périmètre de votre syndicat.")
        return objet


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

    def construct_view(self, view_class, **kwargs):
        if hasattr(view_class, 'get_object'):
            view_class = type(
                f'{view_class.__name__}Cloisonne',
                (MixinObjetCloisonne, view_class),
                {'_viewset_cloisonne': self},
            )
        return super().construct_view(view_class, **kwargs)
