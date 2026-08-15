from django import forms
from django.http import HttpResponseRedirect
from django.shortcuts import get_list_or_404
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import format_html
from django.views import View
from urllib.parse import urlparse

import django_filters

from wagtail import hooks
from wagtail.admin.filters import WagtailFilterSet
from wagtail.admin.ui.components import Component
from wagtail.snippets.bulk_actions.delete import DeleteBulkAction
from wagtail.snippets.views.chooser import SnippetChooserViewSet
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import (
    SnippetViewSet, SnippetViewSetGroup,
    CreateView as SnippetCreateView, EditView as SnippetEditView,
    IndexView as SnippetIndexView,
)
from wagtail.admin.panels import FieldPanel, FieldRowPanel, MultiFieldPanel, ObjectList, TabbedInterface, InlinePanel

from content.admin_utils import (
    WagtailChefRequiredMixin, WagtailSyndicatRequiredMixin, is_chef as _is_chef,
)

from .models import (
    ArticlePage, ContentPage, CmsCategory, Event, SectionPage, panneaux_article,
)
from .cloisonnement import ViewSetCloisonne
from .site_context import SESSION_KEY, get_current_site, get_available_sites, set_current_site


def _safe_redirect(url, fallback='/cms/'):
    """Rejette les URLs externes pour prévenir les open redirects."""
    if not url:
        return fallback
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return fallback
    return url or fallback



class PageTreeCreateMixin:
    """Insère une page Wagtail dans l'arbre à la création.

    ArticlePage et ContentPage sont des pages Wagtail, mais elles sont éditées
    via des SnippetViewSet. À la création, `form.save()` fait un INSERT direct
    sans renseigner les champs d'arbre (`depth`, `path`) : la base refuse
    l'enregistrement (« NOT NULL constraint failed: wagtailcore_page.depth »)
    et le rédacteur reçoit une erreur 500. La page doit être ajoutée comme
    enfant de la SectionPage de son syndicat, là où vivent tous les articles.
    """

    def _page_parente(self, instance):
        from .models import SectionPage
        slug = getattr(instance, 'section_slug', '') or ''
        parent = SectionPage.objects.filter(slug=slug).first()
        if parent is None and slug:
            parent = SectionPage.objects.filter(legacy_site_slug=slug).first()
        if parent is None:
            parent = get_current_site(self.request)
        if parent is None:
            parent = SectionPage.objects.filter(slug='principal').first()
        return parent

    def save_instance(self):
        from wagtail.log_actions import log

        if self.form.instance.pk:
            return super().save_instance()

        parent = self._page_parente(self.form.instance)
        if parent is None:
            return super().save_instance()

        # save(commit=False) prépare aussi save_m2m (catégories, tags)
        instance = self.form.save(commit=False)
        # `Page.live` vaut True par défaut : sans cette ligne, « Enregistrer le
        # brouillon » mettait l'article EN LIGNE dès sa création, et les trois
        # essais du STUCS se sont retrouvés en tête du flux RSS public
        # (constaté le 15/08/2026). Wagtail fait la même chose dans le
        # `save_instance` qu'on surcharge ici — voir le commentaire « make sure
        # the live field is set to False » dans
        # wagtail/admin/views/generic/mixins.py. C'est `publish_action()` qui
        # remettra `live` à True, et lui seul renseigne `first_published_at`.
        if self.view_name == 'create':
            instance.live = False
        # Passer par une instance générique Page : sur la classe spécifique,
        # le gestionnaire ne voit que les pages du même type et treebeard
        # calcule un chemin déjà pris.
        from wagtail.models import Page
        Page.objects.get(pk=parent.pk).add_child(instance=instance)
        if hasattr(self.form, 'save_m2m'):
            self.form.save_m2m()

        # Reproduit le contrat de Wagtail : la suite de la vue (publication,
        # messages, réponse JSON) lit has_content_changes et new_revision.
        self.has_content_changes = True
        self.new_revision = None
        if getattr(self, 'revision_enabled', False):
            self.new_revision = instance.save_revision(
                user=self.request.user,
                clean=not getattr(self, 'saving_as_draft', False),
            )
        log(instance=instance, action='wagtail.create',
            revision=self.new_revision, content_changed=True)
        return instance


class IterateurCategoriesGroupees:
    """Regroupe les cases à cocher par catégorie parente.

    Django rend nativement des groupes dans `CheckboxSelectMultiple` dès que
    l'itérateur de choix produit des couples `(nom du groupe, [choix])`. Le 13
    a 62 catégories sur deux niveaux : une liste plate, même triée et préfixée,
    reste illisible (retour d'Arnaud sur le compte essai-13, 05/08/2026).

    L'étiquette redevient courte dans un groupe : l'en-tête porte déjà le nom
    du parent, « BTP › Vos droits » sous « BTP » bégaierait.

    ⚠️ Affecter `field.iterator` ne suffit pas : c'est l'affectation de
    `field.queryset` qui recharge `widget.choices`. Poser l'itérateur APRÈS le
    queryset laisse le widget avec ses choix plats, sans rien signaler.
    """

    def __init__(self, field):
        self.field = field
        self.queryset = field.queryset

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ('', self.field.empty_label)
        groupes = {}
        for obj in self.queryset:
            cle = obj.parent.name if obj.parent_id else obj.name
            groupes.setdefault(cle, []).append(obj)
        for nom, objets in groupes.items():
            # Le parent d'abord s'il est lui-même sélectionnable, puis ses
            # enfants par ordre alphabétique.
            objets.sort(key=lambda o: (o.parent_id is not None, o.name))
            yield (nom, [(self.field.prepare_value(o), o.name) for o in objets])

    def __len__(self):
        return sum(1 for _ in self)


def _make_scoped_article_page_view(base_class):
    """
    - Filtre cms_categories par section courante.
    - Pré-remplit/verrouille section_slug.
    - Masque featured_on_conf pour les non-chefs.
    - Pré-coche in_carousel selon l'état réel du carrousel.
    - Enforce section_slug au save pour les rédacteurs.
    """
    class ScopedView(PageTreeCreateMixin, base_class):
        @staticmethod
        def _borner_categories(form, current):
            """Ne propose que les catégories du syndicat concerné.

            Le filtre ne s'appliquait qu'avec un syndicat sélectionné : un
            superuser sans sélection voyait les 219 catégories des douze
            sections, dont « Non classé » six fois (Arnaud, 05/08/2026). Un
            rédacteur, lui, n'a jamais vu que les siennes.

            Sans sélection, on se rabat sur la section de l'article. Si elle
            est inconnue (création par un superuser qui n'a rien choisi), on
            n'ampute pas son choix : on préfixe par la section pour distinguer
            les homonymes.
            """
            from django.db.models.functions import Coalesce
            champ = form.fields['cms_categories']
            # Chaque parent immédiatement suivi de ses enfants : trier sur
            # `parent__name` seul reléguait les 22 parents du 13 tout en bas,
            # après leurs propres enfants.
            # `select_related('parent')` : l'étiquette lit le parent, sinon
            # c'est une requête par catégorie.
            qs = (CmsCategory.objects.select_related('parent')
                  .annotate(_groupe=Coalesce('parent__name', 'name'))
                  .order_by('_groupe', 'parent__name', 'name'))
            slugs = None
            if current:
                slugs = current.slugs_contenu
            else:
                propre = getattr(form.instance, 'section_slug', '')
                if propre:
                    slugs = {propre}
            if slugs:
                champ.iterator = IterateurCategoriesGroupees
                champ.queryset = qs.filter(section_slug__in=slugs)
            else:
                # Toutes sections confondues : grouper mélangerait des
                # syndicats. Liste plate, préfixée par la section.
                champ.queryset = qs
                champ.label_from_instance = lambda c: f'[{c.section_slug}] {c}'

        def get_form(self, form_class=None):
            form = super().get_form(form_class)
            current = get_current_site(self.request)
            chef = _is_chef(self.request.user)

            if not chef and 'featured_on_conf' in form.fields:
                form.fields['featured_on_conf'].widget = forms.HiddenInput()
                form.fields['featured_on_conf'].required = False

            if 'cms_categories' in form.fields:
                self._borner_categories(form, current)

            if current:
                # Lire sur les deux slugs (cf. SectionPage.slugs_contenu),
                # écrire sur le slug Wagtail.
                slug = current.slug
                slugs = current.slugs_contenu
                if 'section_slug' in form.fields:
                    if chef:
                        form.fields['section_slug'].initial = slug
                        form.fields['section_slug'].help_text = (
                            f"Syndicat courant : <strong>{current.title}</strong>. "
                            "Changez via le sélecteur de syndicat en haut de page."
                        )
                    else:
                        form.fields['section_slug'].initial = slug
                        form.fields['section_slug'].widget = forms.HiddenInput()
                        form.fields['section_slug'].required = False

                # Pré-coche in_carousel selon l'état réel en base
                if current.section_type in ('sectoral', 'regional') and 'in_carousel' in form.fields:
                    instance = getattr(self, 'object', None)
                    if instance and instance.pk:
                        from .models import CarouselArticle
                        already = CarouselArticle.objects.filter(
                            page=current, article=instance
                        ).exists()
                        form.fields['in_carousel'].initial = already
                        form.instance.in_carousel = already
            else:
                if chef and 'section_slug' in form.fields:
                    form.fields['section_slug'].help_text = (
                        "⚠️ Aucun syndicat sélectionné. "
                        "Utilisez le sélecteur de syndicat en haut de page avant de créer un article."
                    )
            return form

        def form_valid(self, form):
            """Enforce section_slug côté serveur pour les non-chefs."""
            if not _is_chef(self.request.user):
                current = get_current_site(self.request)
                if current:
                    form.instance.section_slug = current.slug
            return super().form_valid(form)

    return ScopedView


# ── Articles ──────────────────────────────────────────────────────────────────

class FiltreArticles(WagtailFilterSet):
    """Filtres de la liste des articles, dont un par catégorie.

    Le filtre est borné au syndicat courant : sans cela, il proposerait les
    219 catégories des douze sections, dont « Non classé » six fois — le même
    défaut que le formulaire d'article (Arnaud, 05/08/2026). django-filter
    accepte un `queryset` appelable qui reçoit la requête, ce qui permet de
    réutiliser le périmètre déjà défini par le cloisonnement.
    """

    @staticmethod
    def _categories_du_syndicat(request):
        from django.db.models.functions import Coalesce
        qs = (CmsCategory.objects.select_related('parent')
              .annotate(_groupe=Coalesce('parent__name', 'name'))
              .order_by('_groupe', 'parent__name', 'name'))
        current = get_current_site(request) if request else None
        if current:
            return qs.filter(section_slug__in=current.slugs_contenu)
        return qs

    cms_categories = django_filters.ModelChoiceFilter(
        label='Catégorie',
        field_name='cms_categories',
        queryset=lambda request: FiltreArticles._categories_du_syndicat(request),
    )

    class Meta:
        model = ArticlePage
        fields = ['live', 'section_slug', 'is_featured', 'cms_categories']


class IndexArticles(SnippetIndexView):
    """Liste des articles, avec un bouton d'ajout qui se voit et se comprend.

    Wagtail fabrique le libellé par gabarit — « Ajouter un(e) Article » en
    français, avec la parenthèse d'accord. C'est le geste le plus fréquent d'un
    rédacteur : il mérite une phrase écrite pour lui (demande d'Arnaud,
    15/08/2026).
    """

    @property
    def add_item_label(self):
        return "Écrire un article"


class ArticlePageViewSet(ViewSetCloisonne, SnippetViewSet):
    cloisonnement = ('slug', 'section_slug')
    model = ArticlePage
    icon = 'doc-full'
    menu_label = 'Articles'
    menu_order = 100
    list_display = ['title', 'section_slug', 'publication_date', 'live', 'is_featured']
    filterset_class = FiltreArticles
    search_fields = ['title', 'excerpt']
    ordering = ['-publication_date', '-first_published_at']
    panels = [FieldPanel('title'), panneaux_article()]

    index_view_class = IndexArticles
    add_view_class = _make_scoped_article_page_view(SnippetCreateView)
    edit_view_class = _make_scoped_article_page_view(SnippetEditView)



# ── Pages de contenu ──────────────────────────────────────────────────────────

_CONTENT_PAGE_PANELS = [
    FieldPanel('title'),
    TabbedInterface([
        ObjectList([
            FieldPanel('body'),
        ], heading='Contenu'),
        ObjectList([
            FieldPanel('section_slug'),
            FieldPanel('author_name'),
            FieldPanel('featured_image'),
        ], heading='Métadonnées'),
    ]),
]


class _ContentPageCreateView(PageTreeCreateMixin, SnippetCreateView):
    """Même correctif d'arbre que pour les articles."""


class ContentPageViewSet(ViewSetCloisonne, SnippetViewSet):
    cloisonnement = ('slug', 'section_slug')
    model = ContentPage
    add_view_class = _ContentPageCreateView
    icon = 'doc-empty'
    menu_label = 'Pages statiques'
    menu_order = 110
    panels = _CONTENT_PAGE_PANELS
    list_display = ['title', 'section_slug', 'live']
    list_filter = ['live', 'section_slug']
    search_fields = ['title']



# ── Catégories CMS ────────────────────────────────────────────────────────────

class CmsCategoryViewSet(ViewSetCloisonne, SnippetViewSet):
    cloisonnement = ('slug', 'section_slug')
    model = CmsCategory
    icon = 'folder-open-inverse'
    menu_label = 'Catégories'
    menu_order = 120
    list_display = ['name', 'section_slug', 'parent']
    list_filter = ['section_slug']
    search_fields = ['name', 'slug']



# ── Sections ──────────────────────────────────────────────────────────────────

class SectionPageViewSet(ViewSetCloisonne, SnippetViewSet):
    # La fiche est gérée en autonomie par chaque syndicat : l'objet EST le
    # périmètre. Un chef sans syndicat sélectionné les voit toutes.
    cloisonnement = ('pk', None)
    # Seul sélecteur non cloisonné, et il doit le rester : MenuItem.target_site
    # s'en sert pour pointer vers les AUTRES syndicats — c'est sa raison d'être.
    chooser_viewset_class = SnippetChooserViewSet
    model = SectionPage
    icon = 'site'
    menu_label = 'Mon syndicat'
    menu_order = 200
    list_display = ['title', 'slug', 'section_type', 'live']
    search_fields = ['title', 'slug']
    panels = SectionPage.content_panels



@hooks.register('construct_snippet_action_menu')
def syndicat_enregistrer_publie_directement(menu_items, request, context):
    """« Mon syndicat » est une fiche de réglages : le bouton principal publie
    directement — sinon les modifs dorment en brouillon en attente de « Publier »."""
    if context.get('model') is not SectionPage:
        return
    publish = next((i for i in menu_items if i.name == 'action-publish'), None)
    if publish is None:
        return
    publish.label = 'Enregistrer'
    menu_items[:] = [publish] + [
        i for i in menu_items if i.name not in ('action-publish', 'action-save')
    ]


# ── Événements ────────────────────────────────────────────────────────────────

class EventViewSet(ViewSetCloisonne, SnippetViewSet):
    cloisonnement = ('fk', 'section')
    model = Event
    icon = 'date'
    menu_label = 'Agenda'
    menu_order = 130
    list_display = ['title', 'section', 'date', 'location']
    list_filter = ['section']
    search_fields = ['title', 'location']
    ordering = ['date', 'time']
    panels = [
        FieldPanel('section'),
        FieldPanel('title'),
        MultiFieldPanel([
            FieldRowPanel([FieldPanel('date'), FieldPanel('end_date')]),
            FieldPanel('time'),
        ], heading="Date et heure"),
        FieldPanel('location'),
        # latitude/longitude remplis automatiquement par le géocodeur JS
        FieldRowPanel([FieldPanel('latitude'), FieldPanel('longitude')]),
        FieldPanel('description'),
        FieldPanel('url'),
    ]



# ── Groupe principal CMS ──────────────────────────────────────────────────────

class CmsContenuGroup(SnippetViewSetGroup):
    menu_label = 'Rédaction'
    menu_icon = 'doc-full-inverse'
    menu_order = 100
    items = (ArticlePageViewSet, ContentPageViewSet, CmsCategoryViewSet, EventViewSet)

    def get_menu_item(self, order=None):
        """Marque l'entrée pour que la feuille de style puisse la grossir.

        La barre latérale de Wagtail est rendue par React : ses classes sont
        calculées côté navigateur et aucune ne porte le nom de l'entrée. En
        revanche le composant recopie les `attrs` de l'élément sur son bouton
        — c'est le seul crochet stable pour viser « Rédaction » et pas les
        autres rubriques. `classname`, lui, n'est pas repris par ce composant.
        """
        item = super().get_menu_item(order=order)
        item.attrs = {**(item.attrs or {}), 'data-cnt-menu': 'redaction'}
        return item


class CmsAdminGroup(SnippetViewSetGroup):
    menu_label = 'Structure du site'
    menu_icon = 'site'
    menu_order = 150
    items = (SectionPageViewSet,)


register_snippet(CmsContenuGroup)
register_snippet(CmsAdminGroup)


# ── Suppression en masse ──────────────────────────────────────────────────────

@hooks.register('register_bulk_action')
class SuppressionEnMasseCloisonnee(DeleteBulkAction):
    """Les actions en masse court-circuitent complètement les viewsets.

    `BulkAction` lit les objets par clé primaire sans aucun filtre et résout
    « tout sélectionner » en `model.objects.all()`, tandis que `check_perm` ne
    teste que la permission de modèle — Wagtail l'assume dans son propre code :
    « snippets permissions are not enforced per object ». Le rôle syndicat ayant
    `delete_subscriber`, un seul POST sur
    `/cms/bulk/content/subscriber/delete/?id=all` effaçait les abonnés de tous
    les syndicats.

    Enregistrée après celle de Wagtail (cms est plus bas dans INSTALLED_APPS) :
    le registre garde la dernière classe vue pour un `action_type` donné.
    """

    def _perimetre(self, model):
        viewset = getattr(model, 'snippet_viewset', None)
        if isinstance(viewset, ViewSetCloisonne):
            return viewset.get_queryset(self.request)
        return model._default_manager.all()

    def get_queryset(self, model, object_ids):
        # Redéfini en méthode d'instance (classmethod chez Wagtail) : il faut
        # la requête pour connaître le syndicat courant. Le site d'appel,
        # `self.get_queryset(self.model, object_ids)`, fonctionne pour les deux.
        return get_list_or_404(self._perimetre(model).filter(pk__in=object_ids))

    def get_all_objects_in_listing_query(self, parent_id):
        return self._perimetre(self.model).values_list('pk', flat=True)


# ── Boutons "Voir / Prévisualiser" sur les articles ───────────────────────────

@hooks.register('register_snippet_action_menu_item')
def add_article_view_button(model, **kwargs):
    if model is not ArticlePage:
        return

    from wagtail.snippets.action_menu import ActionMenuItem

    class ViewOnSiteMenuItem(ActionMenuItem):
        name = 'view-on-site'
        icon_name = 'link-external'

        def is_shown(self, context):
            instance = context.get('instance')
            return bool(instance and instance.pk and instance.live)

        def render_html(self, context):
            instance = context.get('instance')
            if not (instance and instance.pk and instance.live):
                return ''
            url = instance.get_absolute_url()
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" class="button button-secondary">'
                '<svg class="icon icon-link-external" aria-hidden="true"><use href="#icon-link-external"></use></svg>'
                ' Voir sur le site</a>',
                url,
            )

    class PreviewDraftMenuItem(ActionMenuItem):
        name = 'preview-draft'
        icon_name = 'view'

        def is_shown(self, context):
            instance = context.get('instance')
            return bool(instance and instance.pk and not instance.live)

        def render_html(self, context):
            instance = context.get('instance')
            if not (instance and instance.pk and not instance.live):
                return ''
            url = reverse('wagtailadmin_pages:view_draft', args=[instance.pk])
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" class="button button-secondary">'
                '<svg class="icon icon-view" aria-hidden="true"><use href="#icon-view"></use></svg>'
                ' Prévisualiser</a>',
                url,
            )

    # Retourne les deux — Wagtail appelle ce hook une fois et attend un seul item,
    # donc on enregistre deux hooks séparés
    return ViewOnSiteMenuItem(order=90)


@hooks.register('register_snippet_action_menu_item')
def add_article_preview_button(model, **kwargs):
    if model is not ArticlePage:
        return

    from wagtail.snippets.action_menu import ActionMenuItem

    class PreviewDraftMenuItem(ActionMenuItem):
        name = 'preview-draft'
        icon_name = 'view'

        def is_shown(self, context):
            instance = context.get('instance')
            return bool(instance and instance.pk and not instance.live)

        def render_html(self, context):
            instance = context.get('instance')
            if not (instance and instance.pk and not instance.live):
                return ''
            url = reverse('wagtailadmin_pages:view_draft', args=[instance.pk])
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" class="button button-secondary">'
                '<svg class="icon icon-view" aria-hidden="true"><use href="#icon-view"></use></svg>'
                ' Prévisualiser</a>',
                url,
            )

    return PreviewDraftMenuItem(order=91)


# ── Scoping articles par syndicat courant ─────────────────────────────────────

def _scope_by_current_site(qs, request, site_field='section_slug'):
    """Filtre un queryset selon le syndicat courant en session."""
    current = get_current_site(request)
    if current:
        return qs.filter(**{site_field: current.slug})
    return qs


# ── Panneau dashboard "Mon syndicat" ──────────────────────────────────────────

class SiteDashboardPanel(Component):
    """Panneau Wagtail dashboard montrant le syndicat courant avec accès rapides."""
    order = 50

    def __init__(self, request):
        self.request = request

    def render_html(self, parent_context=None):
        request = self.request
        current = get_current_site(request)
        available = get_available_sites(request)

        stats = {}
        section_page_id = None
        if current:
            from content.models import Subscriber, ContactMessage
            slugs = current.slugs_contenu
            stats['articles'] = ArticlePage.objects.filter(section_slug__in=slugs).count()
            stats['pages'] = ContentPage.objects.filter(section_slug__in=slugs).count()
            stats['subscribers'] = Subscriber.objects.filter(site=current, is_active=True).count()
            stats['contacts_unread'] = ContactMessage.objects.filter(site=current, is_read=False).count()
            section_page_id = current.pk

        return render_to_string('cms/dashboard/site_panel.html', {
            'current_site': current,
            'available_sites': available,
            'stats': stats,
            'section_page_id': section_page_id,
            'is_chef': _is_chef(request.user),
            'request': request,
        }, request=request)


@hooks.register('construct_homepage_panels')
def add_site_dashboard_panel(request, panels):
    panels.insert(0, SiteDashboardPanel(request))


# ── Menu "Syndicats" dans la barre latérale ──────────────────────────────────

from wagtail.admin.menu import MenuItem as WagtailMenuItem


class ChefOnlyMenuItem(WagtailMenuItem):
    """Entrée de menu réservée aux superusers et rédacteurs-en-chef."""
    def is_shown(self, request):
        return _is_chef(request.user)


class SyndicatMenuItem(WagtailMenuItem):
    """Entrée visible pour les chefs ET les rédacteurs rattachés à un syndicat."""
    def is_shown(self, request):
        return _is_chef(request.user) or get_current_site(request) is not None


@hooks.register('register_admin_menu_item')
def add_syndicats_menu_item():
    return ChefOnlyMenuItem(
        'Syndicats',
        '/cms/syndicats/',
        name='syndicats',
        icon_name='site',
        order=160,
    )


@hooks.register('register_admin_menu_item')
def add_mailing_lists_menu_item():
    # Autonomie des syndicats : chaque rédacteur gère la liste OVH de son
    # syndicat (_allowed_mailing_lists le borne à celle-ci).
    return SyndicatMenuItem(
        'Listes mails',
        '/cms/mailing-lists/',
        name='mailing-lists',
        icon_name='mail',
        order=315,
    )

# "Menus" supprimé — "Navigation" redirige vers /cms/menus/ (voir MenuItemViewSet)


@hooks.register('construct_main_menu')
def hide_structure_du_site_menu(request, menu_items):
    """Masque "Structure du site" — l'édition syndicat se fait via /cms/syndicats/."""
    menu_items[:] = [
        item for item in menu_items
        if getattr(item, 'name', '') != 'structure-du-site'
        and getattr(item, 'label', '') != 'Structure du site'
    ]


# ── Sélecteur de syndicat dans la sidebar ────────────────────────────────────

@hooks.register('insert_global_admin_css')
def insert_categories_css():
    """Mise en page de la liste des catégories d'un article.

    62 cases sur une colonne (le cas du 13) obligent à faire défiler l'écran
    pour choisir une rubrique. Colonnes, en-tête de groupe détaché, cases
    décalées dessous.

    Le balisage est celui de Wagtail, relevé sur le HTML servi — et NON le
    `<ul>/<li>` de Django, que j'avais supposé à tort :

        #id_cms_categories > div            un groupe
          > label (SANS `for`)              son en-tête
          > div > label[for]                une case

    D'où le `:not([for])` : sans lui, en liste non groupée (superuser sans
    syndicat choisi), les étiquettes des cases prendraient le style d'en-tête.
    """
    return """<style>
#id_cms_categories {
    columns: 3 200px;
    column-gap: 1.5rem;
}
#id_cms_categories > div {
    break-inside: avoid;
    page-break-inside: avoid;
    margin-bottom: .75rem;
}
#id_cms_categories > div > label:not([for]) {
    display: block;
    font-weight: 700;
    font-size: .72rem;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: var(--w-color-text-label, #5b5b5b);
    margin-bottom: .25rem;
}
#id_cms_categories > div > label:not([for]) + div {
    padding-left: .6rem;
    border-left: 2px solid var(--w-color-border-field-default, #d9d9d9);
}
#id_cms_categories label[for] {
    display: block;
    font-weight: 400;
    font-size: .87rem;
    line-height: 1.5;
}
@media (max-width: 900px) {
    #id_cms_categories { columns: 1; }
}
</style>"""


@hooks.register('insert_global_admin_css')
def insert_site_selector_css():
    return """<style>
.cms-site-selector-bar {
    background: #13151a;
    border-top: 1px solid #2d3139;
    padding: .5rem 1rem;
    font-size: .8rem;
}
.cms-site-selector-bar select {
    background: #252932;
    border: 1px solid #2d3139;
    border-radius: 4px;
    color: #e2e8f0;
    font-size: .8rem;
    padding: .2rem .5rem;
    cursor: pointer;
    width: 100%;
    margin-top: .25rem;
}
.cms-site-selector-bar .label {
    color: #94a3b8;
    display: block;
    margin-bottom: .2rem;
}
.cms-site-selector-bar strong {
    color: #e63946;
}
</style>"""


@hooks.register('insert_global_admin_js')
def insert_site_selector_js():
    return """<script>
(function() {
  function injectSiteBar() {
    if (document.getElementById('cnt-site-bar')) return;
    fetch('/cms/current-site-fragment/')
      .then(function(r) { return r.text(); })
      .then(function(html) {
        if (!html.trim()) return;
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        var bar = tmp.firstElementChild;
        if (!bar) return;

        // Ajouter next=URL_courante sur chaque lien de changement de syndicat
        bar.querySelectorAll('a[href*="select-site"]').forEach(function(a) {
          a.href = a.href + '&next=' + encodeURIComponent(window.location.pathname);
        });

        var main = document.getElementById('main') || document.querySelector('main');
        if (!main) return;

        // Injecter AVANT la zone sticky Wagtail (header listing) ou en tête de main
        var sticky = main.querySelector('.w-sticky');
        if (sticky) {
          // sticky est enfant de .content (pas de main) — insertBefore sur son parent direct
          sticky.parentNode.insertBefore(bar, sticky);
        } else {
          // Fallback : en tête de main (dashboard, pages sans sticky header)
          main.insertBefore(bar, main.firstChild);
        }
      })
      .catch(function() {});
  }
  document.addEventListener('DOMContentLoaded', injectSiteBar);
})();
</script>"""


# ── Géocodeur adresse sur les pages d'édition d'événement ────────────────────

@hooks.register('insert_editor_js')
def insert_event_geocoder_js():
    from django.templatetags.static import static
    return format_html('<script src="{}"></script>', static('cms/js/event_geocoder.js'))


# ── Vue sélection du syndicat ─────────────────────────────────────────────────

class SelectSiteView(View):
    def _handle(self, request, site_id_raw, next_url=None):
        # Seuls superuser et redacteur_en_chef peuvent changer de site
        if site_id_raw and _is_chef(request.user):
            try:
                set_current_site(request, int(site_id_raw))
            except (ValueError, TypeError):
                pass
        return HttpResponseRedirect(_safe_redirect(next_url, fallback='/cms/'))

    def get(self, request):
        return self._handle(
            request,
            request.GET.get('site_id'),
            _safe_redirect(request.GET.get('next'), fallback='/cms/'),
        )

    def post(self, request):
        return self._handle(
            request,
            request.POST.get('site_id'),
            _safe_redirect(request.POST.get('next'), fallback='/cms/'),
        )


# ── Listes mails OVH ──────────────────────────────────────────────────────────

def _allowed_mailing_lists(request):
    """
    Retourne la liste des noms de listes OVH accessibles à l'utilisateur courant.
    - Superadmin : toutes les listes
    - Chef confédéral comme rédacteur de syndicat : uniquement la ou les
      listes assignées à son syndicat courant (autonomie des syndicats,
      décision 2026-07-16)
    - Aucun syndicat résolu : liste vide (accès refusé côté appelant)
    """
    if request.user.is_superuser:
        return None  # None = pas de restriction
    current = get_current_site(request)
    if current and current.ovh_mailing_list:
        return [n.strip() for n in current.ovh_mailing_list.split(',') if n.strip()]
    return []


def _can_access_list(request, list_name):
    allowed = _allowed_mailing_lists(request)
    if allowed is None:
        return True
    return list_name in allowed


class MailingListIndexView(View):
    def get(self, request):
        from django.http import HttpResponse, HttpResponseForbidden
        from cms import ovh_client

        allowed = _allowed_mailing_lists(request)
        if allowed is not None and len(allowed) == 0:
            return HttpResponseForbidden(
                "Aucune liste mail n'est rattachée à votre syndicat "
                "(ou aucun syndicat n'est rattaché à votre compte).")

        error = None
        lists = []
        try:
            names = ovh_client.list_mailing_lists()
            if allowed is not None:
                names = [n for n in names if n in allowed]
            for name in names:
                try:
                    count = len(ovh_client.get_subscribers(name))
                except Exception:
                    count = '?'
                lists.append({'name': name, 'count': count})
        except Exception as e:
            error = str(e)
        html = render_to_string('cms/mailing/list_index.html', {
            'lists': lists,
            'error': error,
            'is_superadmin': request.user.is_superuser,
            'request': request,
        }, request=request)
        return HttpResponse(html)


class MailingListDetailView(View):
    def _render(self, request, list_name, msg_ok=None, msg_err=None):
        from django.http import HttpResponse
        from cms import ovh_client
        try:
            subscribers = ovh_client.get_subscribers(list_name)
        except Exception as e:
            subscribers = []
            msg_err = msg_err or str(e)
        html = render_to_string('cms/mailing/list_detail.html', {
            'list_name': list_name,
            'subscribers': subscribers,
            'msg_ok': msg_ok,
            'msg_err': msg_err,
            'request': request,
        }, request=request)
        return HttpResponse(html)

    def get(self, request, list_name):
        import csv as csv_module
        from django.http import HttpResponse, HttpResponseForbidden
        from cms import ovh_client
        if not _can_access_list(request, list_name):
            return HttpResponseForbidden("Vous n'avez pas accès à cette liste.")
        if request.GET.get('export') == 'csv':
            try:
                subscribers = ovh_client.get_subscribers(list_name)
            except Exception as e:
                return HttpResponse(f"Erreur : {e}", status=500)
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{list_name}.csv"'
            response.write('﻿')
            writer = csv_module.writer(response)
            writer.writerow(['email'])
            for email in sorted(subscribers):
                writer.writerow([email])
            return response
        return self._render(request, list_name)

    def post(self, request, list_name):
        from django.http import HttpResponseForbidden
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError
        from cms import ovh_client
        if not _can_access_list(request, list_name):
            return HttpResponseForbidden("Vous n'avez pas accès à cette liste.")
        action = request.POST.get('action')
        msg_ok = msg_err = None

        if action == 'import':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                return self._render(request, list_name, msg_err="Aucun fichier fourni.")
            try:
                content = csv_file.read().decode('utf-8-sig').splitlines()
            except Exception:
                return self._render(request, list_name, msg_err="Impossible de lire le fichier (encodage ?).")
            emails_to_add = []
            for line in content:
                # Accepte CSV (1re colonne) ou simple liste d'emails
                candidate = line.split(',')[0].strip().strip('"').lower()
                if not candidate or candidate == 'email':
                    continue
                try:
                    validate_email(candidate)
                    emails_to_add.append(candidate)
                except DjangoValidationError:
                    pass
            if not emails_to_add:
                return self._render(request, list_name, msg_err="Aucune adresse e-mail valide trouvée dans le fichier.")
            # Dédoublonnage avant envoi à OVH
            emails_to_add = list(dict.fromkeys(emails_to_add))
            added = skipped = errors = 0
            for email in emails_to_add:
                try:
                    result = ovh_client.add_subscriber(list_name, email)
                    if result:
                        added += 1
                    else:
                        skipped += 1
                except Exception:
                    errors += 1
            parts = [f"{added} ajouté(s)"]
            if skipped:
                parts.append(f"{skipped} déjà présent(s)")
            if errors:
                parts.append(f"{errors} erreur(s)")
            msg_ok = " · ".join(parts) + f" (sur {len(emails_to_add)} adresses dans le fichier)."
            return self._render(request, list_name, msg_ok=msg_ok)

        email = request.POST.get('email', '').strip()
        if not email:
            return self._render(request, list_name, msg_err="Adresse e-mail manquante.")
        try:
            if action == 'add':
                added = ovh_client.add_subscriber(list_name, email)
                msg_ok = f"{email} ajouté." if added else f"{email} était déjà abonné."
            elif action == 'remove':
                ovh_client.remove_subscriber(list_name, email)
                msg_ok = f"{email} retiré."
            else:
                msg_err = "Action inconnue."
        except Exception as e:
            msg_err = str(e)
        return self._render(request, list_name, msg_ok=msg_ok, msg_err=msg_err)


@hooks.register('register_admin_urls')
def register_site_admin_urls():
    return [
        path('select-site/', SelectSiteView.as_view(), name='cms_select_site'),
        path('current-site-fragment/', CurrentSiteFragmentView.as_view(), name='cms_current_site_fragment'),
        path('syndicats/', SyndicatManageView.as_view(), name='cms_syndicats'),
        path('menus/', MenuTreeView.as_view(), name='cms_menus'),
        path('menus/move/', MoveMenuItemView.as_view(), name='cms_menu_move'),
        path('menus/reorder/', ReorderMenuItemsView.as_view(), name='cms_menu_reorder'),
        path('mailing-lists/', MailingListIndexView.as_view(), name='cms_mailing_list_index'),
        path('mailing-lists/<str:list_name>/', MailingListDetailView.as_view(), name='cms_mailing_list_detail'),
    ]


class MoveMenuItemView(WagtailSyndicatRequiredMixin, View):
    """Déplace un élément de menu : haut/bas ou indent/outdent."""
    def _handle(self, request, data):
        from django.http import HttpResponse
        from content.models import MenuItem

        pk = data.get('item')
        action = data.get('action')  # up | down | indent | outdent
        next_url = _safe_redirect(data.get('next'), fallback='/cms/menus/')

        try:
            item = MenuItem.objects.get(pk=pk)
        except (MenuItem.DoesNotExist, TypeError, ValueError):
            return HttpResponseRedirect(next_url)

        # Un rédacteur de syndicat ne manipule que les menus de SON syndicat
        # (le pk vient du POST : sans ce garde, n'importe quel item de
        # n'importe quel site serait déplaçable).
        if not _is_chef(request.user):
            current = get_current_site(request)
            if current is None or item.site_id != current.pk:
                return HttpResponseRedirect(next_url)

        if action == 'up':
            siblings = MenuItem.objects.filter(
                site=item.site, menu=item.menu, parent=item.parent
            ).order_by('order', 'pk')
            sibling_list = list(siblings)
            idx = next((i for i, s in enumerate(sibling_list) if s.pk == item.pk), None)
            if idx and idx > 0:
                prev = sibling_list[idx - 1]
                item.order, prev.order = prev.order, item.order
                # ensure distinct if equal
                if item.order == prev.order:
                    item.order = prev.order - 1
                item.save(update_fields=['order'])
                prev.save(update_fields=['order'])

        elif action == 'down':
            siblings = MenuItem.objects.filter(
                site=item.site, menu=item.menu, parent=item.parent
            ).order_by('order', 'pk')
            sibling_list = list(siblings)
            idx = next((i for i, s in enumerate(sibling_list) if s.pk == item.pk), None)
            if idx is not None and idx < len(sibling_list) - 1:
                nxt = sibling_list[idx + 1]
                item.order, nxt.order = nxt.order, item.order
                if item.order == nxt.order:
                    item.order = nxt.order + 1
                item.save(update_fields=['order'])
                nxt.save(update_fields=['order'])

        elif action == 'indent':
            # Mettre en sous-item de l'élément juste au-dessus (même niveau)
            siblings = MenuItem.objects.filter(
                site=item.site, menu=item.menu, parent=item.parent
            ).order_by('order', 'pk')
            sibling_list = list(siblings)
            idx = next((i for i, s in enumerate(sibling_list) if s.pk == item.pk), None)
            if idx and idx > 0:
                new_parent = sibling_list[idx - 1]
                item.parent = new_parent
                item.order = MenuItem.objects.filter(
                    site=item.site, menu=item.menu, parent=new_parent
                ).count()
                item.save(update_fields=['parent', 'order'])

        elif action == 'outdent':
            # Remonter d'un niveau (enlever le parent)
            if item.parent:
                from django.db.models import Max
                grandparent = item.parent.parent  # peut être None
                item.parent = grandparent
                agg = MenuItem.objects.filter(
                    site=item.site, menu=item.menu, parent=grandparent
                ).aggregate(m=Max('order'))
                item.order = (agg['m'] or 0) + 1
                item.save(update_fields=['parent', 'order'])

        return HttpResponseRedirect(next_url)

    def post(self, request):
        return self._handle(request, request.POST)


class ReorderMenuItemsView(WagtailSyndicatRequiredMixin, View):
    """Réordonne et/ou re-parent les éléments de menu (AJAX POST JSON).

    Formats acceptés :
      { moves: [{id, parent, order}, ...] }   — drag-and-drop SortableJS (nesting inclus)
      { items: [pk, ...] }                    — compat ancienne version (ordre seul)
    """
    raise_exception = True  # vue JSON : 403 explicite plutôt qu'une redirection
    def post(self, request):
        import json
        from django.http import JsonResponse
        from content.models import MenuItem
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'invalid payload'}, status=400)

        # Les pk (items ET parents) viennent du JSON : un rédacteur de
        # syndicat est borné aux MenuItem de son syndicat, sinon il pourrait
        # réordonner/re-parenter les menus des autres sites.
        if _is_chef(request.user):
            scoped = MenuItem.objects.all()
        else:
            current = get_current_site(request)
            if current is None:
                return JsonResponse({'ok': False, 'error': 'aucun syndicat'}, status=403)
            scoped = MenuItem.objects.filter(site=current)

        if 'moves' in data:
            for move in data.get('moves', []):
                try:
                    parent_id = move.get('parent')
                    if parent_id is not None and not scoped.filter(pk=int(parent_id)).exists():
                        continue
                    scoped.filter(pk=int(move['id'])).update(
                        order=int(move['order']),
                        parent_id=parent_id,
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        elif 'items' in data:
            for i, pk in enumerate(data.get('items', [])):
                try:
                    scoped.filter(pk=int(pk)).update(order=i)
                except (ValueError, TypeError):
                    continue

        return JsonResponse({'ok': True})


class CurrentSiteFragmentView(View):
    """Fragment HTML du sélecteur de syndicat pour la sidebar."""
    def get(self, request):
        from django.http import HttpResponse
        current = get_current_site(request)
        available = get_available_sites(request)
        if not available.exists():
            return HttpResponse('')
        html = render_to_string('cms/dashboard/site_selector_sidebar.html', {
            'current_site': current,
            'available_sites': available,
            'is_chef': _is_chef(request.user),
        }, request=request)
        return HttpResponse(html)


class MenuTreeView(WagtailSyndicatRequiredMixin, View):
    """Vue arborescente des menus du syndicat courant."""

    def get(self, request):
        from django.http import HttpResponse
        from content.models import MenuItem

        current = get_current_site(request)

        def build_tree(menu_type, site):
            roots = list(
                MenuItem.objects.filter(site=site, menu=menu_type, parent__isnull=True)
                .order_by('order')
                .select_related('category', 'page', 'article', 'target_site')
            )
            children_map = {}
            for child in MenuItem.objects.filter(site=site, menu=menu_type, parent__isnull=False).order_by('order').select_related('category', 'page', 'article', 'target_site'):
                children_map.setdefault(child.parent_id, []).append(child)

            def attach(items):
                for item in items:
                    item.children_list = children_map.get(item.pk, [])
                    attach(item.children_list)
                return items

            return attach(roots)

        site_data = None
        if current:
            site_data = {
                'site': current,
                'main': build_tree('main', current),
                'footer': build_tree('footer', current),
                'secondary': build_tree('secondary', current),
            }

        ctx = {
            'current_site': current,
            'site_data': site_data,
            'request': request,
        }
        html = render_to_string('cms/menus/menu_tree.html', ctx, request=request)
        return HttpResponse(html)


class SyndicatManageView(WagtailChefRequiredMixin, View):
    """Vue de gestion des syndicats (créer, voir, désactiver)."""
    def get(self, request):
        from django.http import HttpResponse
        from cms.models import SectionPage, HomePage
        from content.models import Subscriber

        sections = SectionPage.objects.all().order_by('title')
        home = HomePage.objects.first()

        section_data = []
        for section in sections:
            article_count = ArticlePage.objects.filter(
                section_slug__in=section.slugs_contenu).count()
            subscriber_count = Subscriber.objects.filter(site=section, is_active=True).count()
            section_data.append({
                'section': section,
                'article_count': article_count,
                'subscriber_count': subscriber_count,
                'site_id': section.pk,
            })

        html = render_to_string('cms/dashboard/syndicats.html', {
            'section_data': section_data,
            'home_pk': home.pk if home else '',
            'request': request,
        }, request=request)
        return HttpResponse(html)


@hooks.register('insert_global_admin_css')
def insert_gestes_frequents_css():
    """Grossit les deux gestes les plus fréquents d'un rédacteur.

    Demande d'Arnaud du 15/08/2026 : « Écrire un article » et la rubrique
    « Rédaction » se perdaient dans une interface où tout a le même poids.

    ⚠️ La barre latérale est rendue par React : ses classes sont calculées
    côté navigateur et aucune ne porte le nom de l'entrée. On vise donc
    l'attribut `data-cnt-menu` posé par `CmsContenuGroup.get_menu_item` — le
    composant recopie les `attrs` sur son bouton, contrairement à `classname`.

    Le bouton d'ajout est visé par son `href` : `.w-header-button` seul
    grossirait celui de toutes les listes, y compris les catégories et les
    abonnés, ce qui reviendrait à ne rien mettre en avant du tout.
    """
    return format_html('''<style>
        /* « Écrire un article » — le geste le plus fréquent */
        a.w-header-button[href$="/cms/snippets/cms/articlepage/add/"] {{
            font-size: 1.0625rem;
            font-weight: 700;
            padding: .7rem 1.4rem;
            background: {rouge};
            color: #fff;
            border-color: {rouge};
        }}
        a.w-header-button[href$="/cms/snippets/cms/articlepage/add/"]:hover {{
            background: {rouge_fonce};
            border-color: {rouge_fonce};
            color: #fff;
        }}
        a.w-header-button[href$="/cms/snippets/cms/articlepage/add/"] .icon {{
            width: 1.15em;
            height: 1.15em;
        }}

        /* Rubrique « Rédaction » de la barre latérale */
        .sidebar-menu-item__link[data-cnt-menu="redaction"] {{
            font-size: 1.0625rem;
            font-weight: 700;
        }}
        .sidebar-menu-item__link[data-cnt-menu="redaction"] .icon {{
            width: 1.35em;
            height: 1.35em;
        }}
        /* Le repère visuel tient sans la taille, pour une barre repliée ou un
           réglage de zoom qui écraserait l'écart. */
        .sidebar-menu-item__link[data-cnt-menu="redaction"]::before {{
            content: '';
            position: absolute;
            left: 0; top: .35rem; bottom: .35rem;
            width: 4px;
            background: {rouge};
        }}
        .sidebar-menu-item__link[data-cnt-menu="redaction"] {{
            position: relative;
        }}
    </style>''', rouge='#E81C24', rouge_fonce='#c01018')
