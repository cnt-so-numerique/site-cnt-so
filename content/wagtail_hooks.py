from django.contrib.auth.models import Group
from django.urls import path
from django.utils.html import format_html
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import (
    SnippetViewSet, SnippetViewSetGroup,
    CreateView as SnippetCreateView, EditView as SnippetEditView,
    IndexView as SnippetIndexView,
)
from django import forms as django_forms
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, FieldRowPanel, ObjectList, TabbedInterface, InlinePanel

from .widgets import EditorJsWidget
from .models import (
    Article,
    Page as ContentPage,
    Category,
    Tag,
    Media,
    Author,
    MenuItem,
    Comment,
    ContactMessage,
    FormulaireContact,
    Subscriber,
    Newsletter,
)


def _scope_by_site(qs, request):
    from cms.site_context import scope_qs
    return scope_qs(qs, request, site_field='site')


def _make_scoped_article_view(base_class):
    """Filtre catégories/tags par syndicat courant dans le formulaire article."""
    class ScopedView(base_class):
        def get_form(self, form_class=None):
            form = super().get_form(form_class)
            from cms.site_context import get_current_site
            current = get_current_site(self.request)

            # Pré-sélectionner le syndicat courant (sans toucher au widget)
            if current and 'site' in form.fields:
                if not form.initial.get('site'):
                    form.initial['site'] = current.pk

            # Catégories et tags filtrés par site courant
            if current:
                if 'categories' in form.fields:
                    form.fields['categories'].queryset = Category.objects.filter(site=current).order_by('name')
                if 'tags' in form.fields:
                    form.fields['tags'].queryset = Tag.objects.filter(site=current).order_by('name')
            return form
    return ScopedView


# ── Articles ──────────────────────────────────────────────────────────────────

class ArticleViewSet(SnippetViewSet):
    model = Article
    icon = 'doc-full'
    menu_label = 'Articles'
    menu_order = 100
    list_display = ['title', 'site', 'author', 'status', 'published_at']
    list_filter = ['status', 'site']
    search_fields = ['title', 'excerpt']
    ordering = ['-published_at', '-created_at']

    panels = [
        TabbedInterface([
            ObjectList([
                FieldPanel('title'),
                FieldPanel('slug'),
                FieldRowPanel([
                    FieldPanel('site'),
                    FieldPanel('author'),
                ]),
                FieldRowPanel([
                    FieldPanel('status'),
                    FieldPanel('published_at'),
                ]),
                FieldPanel('is_sticky', heading='À la une / carrousel'),
            ], heading='Publication'),
            ObjectList([
                FieldPanel('content', widget=EditorJsWidget),
                FieldPanel('excerpt'),
            ], heading='Contenu'),
            ObjectList([
                FieldPanel('featured_image'),
                FieldPanel('categories', widget=django_forms.CheckboxSelectMultiple),
                FieldPanel('tags', widget=django_forms.CheckboxSelectMultiple),
            ], heading='Médias & Taxonomies'),
        ])
    ]

    add_view_class = _make_scoped_article_view(SnippetCreateView)
    edit_view_class = _make_scoped_article_view(SnippetEditView)

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Pages statiques ───────────────────────────────────────────────────────────

class ContentPageViewSet(SnippetViewSet):
    model = ContentPage
    icon = 'doc-empty'
    menu_label = 'Pages'
    menu_order = 110
    list_display = ['title', 'site', 'author', 'status']
    list_filter = ['status', 'site']
    search_fields = ['title']
    ordering = ['menu_order', 'title']

    panels = [
        TabbedInterface([
            ObjectList([
                FieldPanel('title'),
                FieldPanel('slug'),
                FieldRowPanel([
                    FieldPanel('site'),
                    FieldPanel('author'),
                ]),
                FieldRowPanel([
                    FieldPanel('status'),
                    FieldPanel('published_at'),
                ]),
                FieldPanel('parent'),
                FieldPanel('menu_order'),
                FieldPanel('template'),
            ], heading='Publication'),
            ObjectList([
                FieldPanel('content', widget=EditorJsWidget),
                FieldPanel('excerpt'),
            ], heading='Contenu'),
            ObjectList([
                FieldPanel('featured_image'),
            ], heading='Image'),
        ])
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Catégories ────────────────────────────────────────────────────────────────

class CategoryViewSet(SnippetViewSet):
    model = Category
    icon = 'folder-open-inverse'
    menu_label = 'Catégories'
    menu_order = 120
    list_display = ['name', 'site', 'parent']
    list_filter = ['site']
    search_fields = ['name']

    panels = [
        FieldPanel('site'),
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('description'),
        FieldPanel('parent'),
        FieldPanel('redirect_page'),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Tags ──────────────────────────────────────────────────────────────────────

class TagViewSet(SnippetViewSet):
    model = Tag
    icon = 'tag'
    menu_label = 'Tags'
    menu_order = 130
    list_display = ['name', 'site']
    list_filter = ['site']
    search_fields = ['name']

    panels = [
        FieldPanel('site'),
        FieldPanel('name'),
        FieldPanel('slug'),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Médias ────────────────────────────────────────────────────────────────────

class MediaViewSet(SnippetViewSet):
    model = Media
    icon = 'image'
    menu_label = 'Médias'
    menu_order = 140
    list_display = ['title', 'site', 'mime_type', 'uploaded_at']
    list_filter = ['site', 'mime_type']
    search_fields = ['title', 'alt_text']
    ordering = ['-uploaded_at']

    panels = [
        FieldPanel('site'),
        FieldPanel('title'),
        FieldPanel('file'),
        FieldPanel('original_url'),
        FieldPanel('mime_type'),
        FieldPanel('alt_text'),
        FieldPanel('caption'),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Commentaires ──────────────────────────────────────────────────────────────

class CommentViewSet(SnippetViewSet):
    model = Comment
    icon = 'comment'
    menu_label = 'Commentaires'
    menu_order = 200
    list_display = ['author_name', 'article', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['author_name', 'content']
    ordering = ['-created_at']

    panels = [
        FieldPanel('article'),
        FieldPanel('author_name'),
        FieldPanel('author_email'),
        FieldPanel('content'),
        FieldPanel('status'),
        FieldPanel('parent'),
    ]

    def get_queryset(self, request):
        from cms.site_context import scope_qs
        return scope_qs(Comment.objects.all(), request, site_field='article__site')


# ── Messages de contact ───────────────────────────────────────────────────────

class ContactMessageViewSet(SnippetViewSet):
    model = ContactMessage
    icon = 'mail'
    menu_label = 'Messages de contact'
    menu_order = 210
    list_display = ['name', 'email', 'subject', 'site', 'created_at', 'is_read']
    list_filter = ['site', 'is_read']
    search_fields = ['name', 'email', 'subject']
    ordering = ['-created_at']

    panels = [
        FieldPanel('site'),
        FieldPanel('name'),
        FieldPanel('email'),
        FieldPanel('phone'),
        FieldPanel('city'),
        FieldPanel('sector'),
        FieldPanel('subject'),
        FieldPanel('message'),
        FieldPanel('is_read'),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Abonnés newsletter ────────────────────────────────────────────────────────

class SubscriberViewSet(SnippetViewSet):
    model = Subscriber
    icon = 'user'
    menu_label = 'Abonnés'
    menu_order = 300
    list_display = ['email', 'name', 'site', 'is_active', 'subscribed_at']
    list_filter = ['site', 'is_active']
    search_fields = ['email', 'name']
    ordering = ['-subscribed_at']

    panels = [
        FieldPanel('site'),
        FieldPanel('email'),
        FieldPanel('name'),
        FieldPanel('is_active'),
        FieldPanel('confirmed_at'),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Newsletter ────────────────────────────────────────────────────────────────

class NewsletterViewSet(SnippetViewSet):
    model = Newsletter
    icon = 'mail'
    menu_label = 'Newsletters'
    menu_order = 310
    list_display = ['title', 'site', 'status', 'created_at', 'sent_at']
    list_filter = ['site', 'status']
    search_fields = ['title']
    ordering = ['-created_at']

    panels = [
        MultiFieldPanel([
            FieldPanel('site'),
            FieldPanel('title'),
            FieldPanel('status'),
        ], heading='Informations'),
        FieldPanel('intro'),
        InlinePanel(
            'newsletter_articles',
            label="Article",
            heading="Articles sélectionnés (dans l'ordre)",
            panels=[
                FieldPanel('article'),
                FieldPanel('order'),
            ]
        ),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Menus ─────────────────────────────────────────────────────────────────────

class _MenuIndexRedirect(SnippetIndexView):
    """Redirige la liste snippet vers la vue arborescente personnalisée."""
    def get(self, request, *args, **kwargs):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect('/cms/menus/')


def _scoped_menuitem_form(form):
    """Filtre le champ category par syndicat courant et utilise le chooser Wagtail."""
    from wagtail.snippets.widgets import AdminSnippetChooser
    from cms.site_context import get_current_site
    request = getattr(form, 'request', None)
    current = get_current_site(request) if request else None
    if current and 'category' in form.fields:
        form.fields['category'].queryset = Category.objects.filter(
            site=current
        ).order_by('name')
        form.fields['category'].widget = AdminSnippetChooser(Category)
    return form


class _MenuItemEditView(SnippetEditView):
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.request = self.request
        return _scoped_menuitem_form(form)


class _MenuItemCreateView(SnippetCreateView):
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.request = self.request
        return _scoped_menuitem_form(form)


class MenuItemViewSet(SnippetViewSet):
    model = MenuItem
    icon = 'list-ul'
    menu_label = 'Menus'
    menu_order = 400
    index_view_class = _MenuIndexRedirect
    edit_view_class = _MenuItemEditView
    add_view_class = _MenuItemCreateView
    list_display = ['title', 'menu', 'site', 'link_type', 'order', 'is_active']
    list_filter = ['site', 'menu']
    search_fields = ['title']
    ordering = ['menu', 'order']

    panels = [
        FieldRowPanel([
            FieldPanel('site'),
            FieldPanel('menu'),
        ]),
        FieldPanel('title'),
        FieldPanel('link_type'),
        FieldPanel('url'),
        FieldPanel('article'),
        FieldPanel('page'),
        FieldPanel('category'),
        FieldPanel('target_site'),
        FieldRowPanel([
            FieldPanel('parent'),
            FieldPanel('order'),
        ]),
        FieldRowPanel([
            FieldPanel('is_active'),
            FieldPanel('opens_new_tab'),
        ]),
    ]

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


# ── Auteurs ───────────────────────────────────────────────────────────────────

class AuthorViewSet(SnippetViewSet):
    model = Author
    icon = 'user'
    menu_label = 'Auteurs'
    menu_order = 500
    list_display = ['display_name', 'username', 'site', 'email']
    list_filter = ['site']
    search_fields = ['username', 'display_name', 'email']

    panels = [
        FieldPanel('user'),
        FieldPanel('site'),
        FieldPanel('username'),
        FieldPanel('display_name'),
        FieldPanel('first_name'),
        FieldPanel('last_name'),
        FieldPanel('email'),
    ]

    def get_queryset(self, request):
        from cms.site_context import scope_qs
        return scope_qs(Author.objects.all(), request, site_field='site')


# ── Groupes de menus ─────────────────────────────────────────────────────────

class ContenuGroup(SnippetViewSetGroup):
    menu_label = 'Articles & Pages (legacy)'
    menu_name = 'legacy-contenu'
    menu_icon = 'doc-full'
    menu_order = 950  # tout en bas
    items = (ArticleViewSet, ContentPageViewSet, CategoryViewSet, TagViewSet, MediaViewSet)


# ── Formulaires de contact ────────────────────────────────────────────────────

class _ContactListRedirect(SnippetIndexView):
    def get(self, request, *args, **kwargs):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect('/cms/contact/')


class _ContactConfigRedirect(SnippetIndexView):
    def get(self, request, *args, **kwargs):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect('/cms/contact-config/')


class ContactMessagesViewSet(SnippetViewSet):
    model = ContactMessage
    icon = 'mail'
    menu_label = 'Messages reçus'
    menu_order = 100
    index_view_class = _ContactListRedirect

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


class ContactConfigViewSet(SnippetViewSet):
    model = FormulaireContact
    icon = 'cog'
    menu_label = 'Config formulaire'
    menu_order = 110
    index_view_class = _ContactConfigRedirect

    def get_queryset(self, request):
        return _scope_by_site(self.model.objects.all(), request)


class ContactGroup(SnippetViewSetGroup):
    menu_label = 'Contact'
    menu_icon = 'form'
    menu_order = 250
    items = (ContactMessagesViewSet, ContactConfigViewSet)


class ModerationsGroup(SnippetViewSetGroup):
    menu_label = 'Modération'
    menu_icon = 'warning'
    menu_order = 200
    items = (CommentViewSet,)


class NewsletterGroup(SnippetViewSetGroup):
    menu_label = 'Newsletter'
    menu_icon = 'mail'
    menu_order = 300
    items = (NewsletterViewSet, SubscriberViewSet)


class NavigationGroup(SnippetViewSetGroup):
    menu_label = 'Navigation'
    menu_icon = 'list-ul'
    menu_order = 400
    items = (MenuItemViewSet,)


class AdministrationGroup(SnippetViewSetGroup):
    menu_label = 'Administration'
    menu_icon = 'cog'
    menu_order = 600
    items = (AuthorViewSet,)


register_snippet(ContenuGroup)
register_snippet(ModerationsGroup)
register_snippet(ContactGroup)
register_snippet(NewsletterGroup)
register_snippet(NavigationGroup)  # URLs add/edit nécessaires pour /cms/menus/
register_snippet(AdministrationGroup)


# ── Masque les menus Wagtail non utilisés (pages, docs, images Wagtail) ───────

@hooks.register('construct_main_menu')
def hide_unused_wagtail_menus(request, menu_items):
    # On garde 'explorer' (arbre de pages) — c'est là que sont les articles/pages Wagtail
    # On masque seulement les menus Wagtail natifs non utilisés dans ce projet
    # articles-pages-legacy = ContenuGroup (content.Article/Page — remplacé par cms.ArticlePage)
    hidden = {'documents', 'images', 'legacy-contenu', 'explorer'}
    menu_items[:] = [item for item in menu_items if item.name not in hidden]


# ── URLs admin supplémentaires (newsletter, contact) ─────────────────────────

@hooks.register('register_admin_urls')
def register_content_admin_urls():
    from content.newsletter_views import NewsletterSendView, SubscriberExportView
    from content.contact_cms_views import (
        ContactSubmissionListView, ContactSubmissionDetailView,
        FormulaireContactConfigView, ChampContactCreateView, ChampContactDeleteView,
    )
    return [
        path('newsletter/<int:pk>/envoyer/', NewsletterSendView.as_view(), name='newsletter_send'),
        path('abonnes/export/', SubscriberExportView.as_view(), name='subscriber_export'),
        path('contact/', ContactSubmissionListView.as_view(), name='contact_list'),
        path('contact/<int:pk>/', ContactSubmissionDetailView.as_view(), name='contact_detail'),
        path('contact-config/', FormulaireContactConfigView.as_view(), name='contact_config'),
        path('contact-config/champ/ajouter/', ChampContactCreateView.as_view(), name='contact_champ_create'),
        path('contact-config/champ/<int:pk>/supprimer/', ChampContactDeleteView.as_view(), name='contact_champ_delete'),
    ]


# ── Bouton "Envoyer" sur la page d'édition d'une Newsletter ──────────────────

@hooks.register('register_snippet_action_menu_item')
def add_newsletter_send_button(model, **kwargs):
    from content.models import Newsletter as NewsletterModel
    if model is not NewsletterModel:
        return

    from wagtail.snippets.action_menu import ActionMenuItem

    class SendNewsletterMenuItem(ActionMenuItem):
        label = 'Envoyer la newsletter'
        name = 'send-newsletter'
        icon_name = 'mail'

        def get_url(self, context):
            instance = context.get('instance')
            if instance and instance.pk and instance.status == 'draft':
                return f'/cms/newsletter/{instance.pk}/envoyer/'
            return None

        def is_shown(self, context):
            instance = context.get('instance')
            return instance and instance.pk and instance.status == 'draft'

    return SendNewsletterMenuItem(order=100)
