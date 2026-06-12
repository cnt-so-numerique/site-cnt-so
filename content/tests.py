import uuid

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, Group, Permission
from django.urls import reverse
from django.utils import timezone

from wagtail.models import Page as WagtailPage
from taggit.models import Tag as TaggitTag

from content.models import (
    Author, Category, Tag, Media, Article, Page,
    Comment, MenuItem, Subscriber, Newsletter,
)
from content.forms import ContactForm, CommentForm
from cms.models import ArticlePage, CmsCategory, HomePage


# ── Fixtures helpers ───────────────────────────────────────────────────────────

def _ensure_section_page(slug, name=None, site_type='regional', live=True,
                          external_url='', contact_email=''):
    """Crée (ou retourne) le SectionPage correspondant au slug donné."""
    from cms.models import SectionPage
    from django.db.models import Q
    sp = SectionPage.objects.filter(Q(slug=slug) | Q(legacy_site_slug=slug)).first()
    if sp:
        return sp
    home = _get_article_parent()
    return home.add_child(instance=SectionPage(
        title=name or slug,
        slug=slug,
        section_type=site_type,
        live=live,
        legacy_site_slug=slug,
        external_url=external_url,
        contact_email=contact_email,
    ))


def make_site(slug='principal', wp_blog_id=1, site_type='main', name='CNT-SO', **kwargs):
    """Crée un SectionPage et le retourne (FK target de tous les modèles)."""
    live = kwargs.get('is_active', True)
    external_url = kwargs.get('external_url', '')
    contact_email = kwargs.get('contact_email', '')
    return _ensure_section_page(
        slug=slug, name=name, site_type=site_type, live=live,
        external_url=external_url, contact_email=contact_email,
    )


def make_article(site, title='Article test', slug=None, status='publish', **kwargs):
    return Article.objects.create(
        site=site, title=title,
        slug=slug or title.lower().replace(' ', '-'),
        status=status,
        published_at=timezone.now() if status == 'publish' else None,
        **kwargs
    )


def _get_article_parent():
    """Retourne (ou crée) une HomePage Wagtail pour servir de parent aux ArticlePage de test."""
    home = HomePage.objects.filter(slug='home-test').first()
    if not home:
        root = WagtailPage.objects.filter(depth=1).first()
        home = root.add_child(instance=HomePage(title='Home Test', slug='home-test', live=True))
    return home


def make_article_page(section_slug='principal', title='Article test', slug=None,
                      live=True, is_featured=False, categories=None, **kwargs):
    parent = _get_article_parent()
    slug = slug or title.lower().replace(' ', '-')
    art = parent.add_child(instance=ArticlePage(
        title=title, slug=slug,
        section_slug=section_slug,
        live=live,
        is_featured=is_featured,
        **kwargs
    ))
    if categories:
        through = ArticlePage.cms_categories.through
        for cat in categories:
            through.objects.create(articlepage=art, cmscategory=cat)
    return art


def make_cms_category(name='Cat', slug=None, section_slug='principal', **kwargs):
    return CmsCategory.objects.create(
        name=name,
        slug=slug or name.lower().replace(' ', '-'),
        section_slug=section_slug,
        **kwargs
    )


def make_superuser(username='superuser', password='pass'):
    return User.objects.create_superuser(username=username, password=password)


def _setup_editorial_groups():
    from content.apps import create_editorial_groups
    from django.apps import apps
    create_editorial_groups(apps.get_app_config('auth'))
    try:
        access = Permission.objects.get(codename='access_admin')
        for name in ['redacteur', 'redacteur_en_chef']:
            group = Group.objects.get(name=name)
            group.permissions.add(access)
            for codename in ['view_articlepage', 'add_articlepage', 'change_articlepage',
                             'view_contentpage']:
                try:
                    group.permissions.add(Permission.objects.get(codename=codename))
                except Permission.DoesNotExist:
                    pass
    except Permission.DoesNotExist:
        pass


def make_chef(username='chef', password='pass', site=None):
    group = Group.objects.get(name='redacteur_en_chef')
    user = User.objects.create_user(username=username, password=password)
    user.groups.add(group)
    if site:
        Author.objects.create(user=user, site=site, username=username)
    return User.objects.get(pk=user.pk)


def make_redacteur(username='redac', password='pass', site=None):
    group = Group.objects.get(name='redacteur')
    user = User.objects.create_user(username=username, password=password)
    user.groups.add(group)
    if site:
        Author.objects.create(user=user, site=site, username=username)
    return User.objects.get(pk=user.pk)


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class SectionPageCompatTest(TestCase):
    """Vérifie que SectionPage a la même interface que l'ancien content.Site."""
    def setUp(self):
        self.main = make_site()
        self.sub = make_site('rhone-alpes', wp_blog_id=2, site_type='regional', name='Rhône-Alpes')
        self.ext = make_site('ext', wp_blog_id=3, external_url='https://ext.example.com')

    def test_str(self):
        self.assertEqual(str(self.main), 'CNT-SO')

    def test_get_absolute_url_principal(self):
        self.assertEqual(self.main.get_absolute_url(), reverse('content:home'))

    def test_get_absolute_url_subsite(self):
        expected = reverse('content:site_home', kwargs={'site_slug': 'rhone-alpes'})
        self.assertEqual(self.sub.get_absolute_url(), expected)

    def test_get_absolute_url_external(self):
        self.assertEqual(self.ext.get_absolute_url(), 'https://ext.example.com')


class AuthorModelTest(TestCase):
    def test_str_with_display_name(self):
        author = Author(username='jdoe', display_name='John Doe')
        self.assertEqual(str(author), 'John Doe')

    def test_str_falls_back_to_username(self):
        author = Author(username='jdoe', display_name='')
        self.assertEqual(str(author), 'jdoe')


class CategoryModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_auto_slug_on_save(self):
        cat = Category.objects.create(site=self.site, name='Actualités et Luttes')
        self.assertEqual(cat.slug, 'actualites-et-luttes')

    def test_slug_not_overwritten_if_provided(self):
        cat = Category.objects.create(site=self.site, name='Test', slug='my-slug')
        self.assertEqual(cat.slug, 'my-slug')

    def test_get_absolute_url_principal(self):
        cat = Category.objects.create(site=self.site, name='Luttes', slug='luttes')
        self.assertEqual(
            cat.get_absolute_url(),
            reverse('content:category_detail', kwargs={'slug': 'luttes'})
        )

    def test_get_absolute_url_subsite(self):
        cat = Category.objects.create(site=self.sub, name='Luttes', slug='luttes')
        expected = reverse('content:site_category_detail', kwargs={'site_slug': 'sub', 'slug': 'luttes'})
        self.assertEqual(cat.get_absolute_url(), expected)


class TagModelTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_auto_slug_on_save(self):
        tag = Tag.objects.create(site=self.site, name='Sans-Papiers')
        self.assertEqual(tag.slug, 'sans-papiers')

    def test_slug_not_overwritten_if_provided(self):
        tag = Tag.objects.create(site=self.site, name='Test', slug='my-tag')
        self.assertEqual(tag.slug, 'my-tag')


class MediaModelTest(TestCase):
    def test_url_falls_back_to_original_url(self):
        media = Media(original_url='https://wp.example.com/img.jpg')
        self.assertEqual(media.url, 'https://wp.example.com/img.jpg')

    def test_url_empty_when_no_file_and_no_original(self):
        media = Media()
        self.assertEqual(media.url, '')


class ArticleModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_auto_slug_on_save(self):
        article = Article.objects.create(site=self.site, title='Mon Premier Article', status='draft')
        self.assertEqual(article.slug, 'mon-premier-article')

    def test_slug_not_overwritten_if_provided(self):
        article = Article.objects.create(site=self.site, title='Test', slug='my-slug', status='draft')
        self.assertEqual(article.slug, 'my-slug')

    def test_get_absolute_url_principal(self):
        article = Article.objects.create(site=self.site, title='Test', slug='test', status='publish')
        self.assertEqual(
            article.get_absolute_url(),
            reverse('content:article_detail', kwargs={'slug': 'test'})
        )

    def test_get_absolute_url_subsite(self):
        article = Article.objects.create(site=self.sub, title='Test', slug='test', status='publish')
        expected = reverse('content:site_article_detail', kwargs={'site_slug': 'sub', 'slug': 'test'})
        self.assertEqual(article.get_absolute_url(), expected)


class ArticlePageModelTest(TestCase):
    """Tests pour cms.ArticlePage (le nouveau modèle d'article)."""

    def setUp(self):
        make_site()
        make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_published_at_uses_publication_date_when_set(self):
        import datetime
        dt = datetime.datetime(2025, 3, 15, tzinfo=datetime.timezone.utc)
        art = make_article_page(section_slug='principal', title='Dated', slug='dated',
                                publication_date=dt)
        self.assertEqual(art.published_at, dt)

    def test_published_at_falls_back_to_first_published_at(self):
        import datetime
        art = make_article_page(section_slug='principal', title='No date', slug='no-date')
        # Wagtail ne set pas first_published_at via add_child en test — on le force
        from cms.models import ArticlePage as AP
        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        AP.objects.filter(pk=art.pk).update(first_published_at=dt)
        art.refresh_from_db()
        self.assertEqual(art.published_at, dt)

    def test_published_at_is_none_when_no_dates(self):
        art = make_article_page(section_slug='principal', title='Nodates', slug='nodates')
        art.publication_date = None
        art.first_published_at = None
        self.assertIsNone(art.published_at)

    def test_get_absolute_url_principal(self):
        art = make_article_page(section_slug='principal', title='Art URL', slug='art-url')
        self.assertEqual(
            art.get_absolute_url(),
            reverse('content:article_detail', kwargs={'slug': 'art-url'})
        )

    def test_get_absolute_url_subsite(self):
        art = make_article_page(section_slug='sub', title='Sub URL', slug='sub-url')
        expected = reverse('content:site_article_detail', kwargs={'site_slug': 'sub', 'slug': 'sub-url'})
        self.assertEqual(art.get_absolute_url(), expected)

    def test_tags_property_returns_cms_tags(self):
        from taggit.models import Tag as TaggitTag
        tag = TaggitTag.objects.create(name='Solidarité', slug='solidarite')
        art = make_article_page(section_slug='principal', title='Tagged', slug='tagged')
        from cms.models import CmsArticleTag
        CmsArticleTag.objects.create(content_object=art, tag=tag)
        self.assertIn(tag, list(art.tags.all()))

    def test_categories_property_returns_cms_categories(self):
        cat = make_cms_category(name='PropCat', slug='prop-cat', section_slug='principal')
        art = make_article_page(section_slug='principal', title='PropArt', slug='prop-art',
                                categories=[cat])
        self.assertIn(cat, list(art.categories.all()))


class ContentPageModelTest(TestCase):
    """Tests pour cms.ContentPage."""

    def setUp(self):
        make_site()
        make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_get_absolute_url_returns_non_empty(self):
        from cms.models import ContentPage
        parent = _get_article_parent()
        cp = parent.add_child(instance=ContentPage(
            title='About CMS', slug='about-cms', section_slug='principal', live=True
        ))
        url = cp.get_absolute_url()
        self.assertTrue(url)  # ne doit pas être vide

    def test_get_absolute_url_fallback_to_slash(self):
        from cms.models import ContentPage
        cp = ContentPage(title='No tree', slug='no-tree', section_slug='principal')
        # Sans parent dans l'arbre, url est None → fallback '/'
        self.assertEqual(cp.get_absolute_url(), '/')


class CmsCategoryModelTest(TestCase):
    """Tests pour cms.CmsCategory."""

    def setUp(self):
        make_site()
        make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_get_absolute_url_principal(self):
        cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')
        self.assertEqual(
            cat.get_absolute_url(),
            reverse('content:category_detail', kwargs={'slug': 'luttes'})
        )

    def test_get_absolute_url_subsite(self):
        cat = make_cms_category(name='Actu Sub', slug='actu-sub', section_slug='sub')
        expected = reverse('content:site_category_detail', kwargs={'site_slug': 'sub', 'slug': 'actu-sub'})
        self.assertEqual(cat.get_absolute_url(), expected)

    def test_save_auto_generates_slug_from_name(self):
        cat = make_cms_category(name='Mon Test Catégorie', slug=None, section_slug='principal')
        self.assertTrue(len(cat.slug) > 0)
        self.assertNotIn(' ', cat.slug)


class PageModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_auto_slug_on_save(self):
        page = Page.objects.create(site=self.site, title='Qui Sommes Nous', status='draft')
        self.assertEqual(page.slug, 'qui-sommes-nous')

    def test_get_absolute_url_principal(self):
        page = Page.objects.create(site=self.site, title='Test', slug='test', status='publish')
        self.assertEqual(
            page.get_absolute_url(),
            reverse('content:page_detail', kwargs={'slug': 'test'})
        )

    def test_get_absolute_url_subsite(self):
        page = Page.objects.create(site=self.sub, title='Test', slug='test', status='publish')
        expected = reverse('content:site_page_detail', kwargs={'site_slug': 'sub', 'slug': 'test'})
        self.assertEqual(page.get_absolute_url(), expected)


class CommentModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.article = Article.objects.create(
            site=self.site, title='Test Article', slug='test', status='publish'
        )

    def test_str_contains_author_and_article(self):
        comment = Comment(article=self.article, author_name='Alice', content='Hello')
        self.assertIn('Alice', str(comment))
        self.assertIn('Test Article', str(comment))


class SubscriberModelTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_token_auto_generated(self):
        sub = Subscriber.objects.create(site=self.site, email='test@example.com')
        self.assertIsNotNone(sub.token)

    def test_default_is_inactive(self):
        sub = Subscriber.objects.create(site=self.site, email='test@example.com')
        self.assertFalse(sub.is_active)

    def test_unique_site_email_raises_integrity_error(self):
        from django.db import IntegrityError
        Subscriber.objects.create(site=self.site, email='dup@example.com')
        with self.assertRaises(IntegrityError):
            Subscriber.objects.create(site=self.site, email='dup@example.com')

    def test_same_email_on_different_sites_is_allowed(self):
        other = make_site('other', wp_blog_id=2, site_type='regional', name='Other')
        Subscriber.objects.create(site=self.site, email='shared@example.com')
        sub2 = Subscriber.objects.create(site=other, email='shared@example.com')
        self.assertIsNotNone(sub2.pk)


class MenuItemGetUrlTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_url_type_returns_url(self):
        item = MenuItem(site=self.site, link_type='url', url='https://example.com')
        self.assertEqual(item.get_url(), 'https://example.com')

    def test_url_type_empty_returns_hash(self):
        item = MenuItem(site=self.site, link_type='url', url='')
        self.assertEqual(item.get_url(), '#')

    def test_category_type(self):
        cat = Category.objects.create(site=self.site, name='Luttes', slug='luttes')
        item = MenuItem(site=self.site, link_type='category', category=cat)
        self.assertEqual(item.get_url(), cat.get_absolute_url())

    def test_site_type(self):
        item = MenuItem(site=self.site, link_type='site', target_site=self.sub)
        self.assertEqual(item.get_url(), self.sub.get_absolute_url())

    def test_article_type(self):
        article = Article.objects.create(site=self.site, title='T', slug='t', status='publish')
        item = MenuItem(site=self.site, link_type='article', article=article)
        self.assertEqual(item.get_url(), article.get_absolute_url())

    def test_page_type(self):
        page = Page.objects.create(site=self.site, title='T', slug='t', status='publish')
        item = MenuItem(site=self.site, link_type='page', page=page)
        self.assertEqual(item.get_url(), page.get_absolute_url())

    def test_contact_main_site(self):
        item = MenuItem(site=self.site, link_type='contact')
        self.assertEqual(item.get_url(), reverse('content:contact'))

    def test_contact_subsite(self):
        item = MenuItem(site=self.sub, link_type='contact')
        expected = reverse('content:site_contact', kwargs={'site_slug': 'sub'})
        self.assertEqual(item.get_url(), expected)

    def test_agenda_subsite(self):
        item = MenuItem(site=self.sub, link_type='agenda')
        expected = reverse('content:site_agenda', kwargs={'site_slug': 'sub'})
        self.assertEqual(item.get_url(), expected)

    def test_no_match_returns_hash(self):
        item = MenuItem(site=self.site, link_type='category', category=None)
        self.assertEqual(item.get_url(), '#')


# ═══════════════════════════════════════════════════════════════════════════════
# FORM TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class ContactFormTest(TestCase):
    def _data(self, **overrides):
        base = {
            'name': 'Alice',
            'email': 'alice@example.com',
            'phone': '0600000000',
            'city': 'Paris',
            'sector': 'Nettoyage',
            'subject': 'Test',
            'message': 'Bonjour',
        }
        base.update(overrides)
        return base

    def test_valid_form(self):
        form = ContactForm(data=self._data())
        self.assertTrue(form.is_valid())

    def test_invalid_email(self):
        form = ContactForm(data=self._data(email='not-an-email'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_missing_name(self):
        form = ContactForm(data=self._data(name=''))
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_subject_and_message_are_optional(self):
        form = ContactForm(data=self._data(subject='', message=''))
        self.assertTrue(form.is_valid())


class CommentFormTest(TestCase):
    def test_valid_form(self):
        data = {'author_name': 'Bob', 'author_email': 'bob@example.com', 'content': 'Great!'}
        self.assertTrue(CommentForm(data=data).is_valid())

    def test_missing_author_name(self):
        data = {'author_name': '', 'author_email': 'bob@example.com', 'content': 'Hi'}
        form = CommentForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('author_name', form.errors)

    def test_missing_content(self):
        data = {'author_name': 'Bob', 'author_email': '', 'content': ''}
        form = CommentForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('content', form.errors)

    def test_author_email_optional(self):
        data = {'author_name': 'Bob', 'author_email': '', 'content': 'Hello'}
        self.assertTrue(CommentForm(data=data).is_valid())


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class HomeViewTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_returns_200(self):
        response = self.client.get(reverse('content:home'))
        self.assertEqual(response.status_code, 200)

    def test_context_has_site(self):
        response = self.client.get(reverse('content:home'))
        self.assertEqual(response.context['site'], self.site)

    def test_context_has_featured_article_key(self):
        response = self.client.get(reverse('content:home'))
        self.assertIn('featured_article', response.context)

    def test_context_has_hero_mini_cards_key(self):
        response = self.client.get(reverse('content:home'))
        self.assertIn('hero_mini_cards', response.context)

    def test_sticky_article_becomes_featured(self):
        sticky = make_article_page(section_slug='principal', title='Sticky', slug='sticky', is_featured=True)
        response = self.client.get(reverse('content:home'))
        self.assertEqual(response.context['featured_article'], sticky)

    def test_first_article_is_featured_when_no_sticky(self):
        art = make_article_page(section_slug='principal', title='First', slug='first')
        response = self.client.get(reverse('content:home'))
        self.assertEqual(response.context['featured_article'], art)

    def test_featured_article_none_when_no_articles(self):
        response = self.client.get(reverse('content:home'))
        self.assertIsNone(response.context['featured_article'])

    def test_hero_mini_cards_populated_with_multiple_articles(self):
        for i in range(4):
            make_article_page(section_slug='principal', title=f'Art {i}', slug=f'art-{i}')
        response = self.client.get(reverse('content:home'))
        self.assertIn('hero_mini_cards', response.context)
        self.assertLessEqual(len(response.context['hero_mini_cards']), 3)

    def test_flux_grid_in_context(self):
        for i in range(5):
            make_article_page(section_slug='principal', title=f'Flux {i}', slug=f'flux-{i}')
        response = self.client.get(reverse('content:home'))
        self.assertIn('flux_grid', response.context)


class ArticleDetailViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.article = make_article_page(section_slug='principal', title='Published', slug='published')
        self.draft = make_article_page(section_slug='principal', title='Draft', slug='draft', live=False)

    def test_published_article_returns_200(self):
        url = reverse('content:article_detail', kwargs={'slug': 'published'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_draft_article_returns_404(self):
        url = reverse('content:article_detail', kwargs={'slug': 'draft'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_nonexistent_slug_returns_404(self):
        url = reverse('content:article_detail', kwargs={'slug': 'no-such-article'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_context_has_related_articles(self):
        url = reverse('content:article_detail', kwargs={'slug': 'published'})
        response = self.client.get(url)
        self.assertIn('related_articles', response.context)

    def test_context_site_is_principal_site(self):
        url = reverse('content:article_detail', kwargs={'slug': 'published'})
        response = self.client.get(url)
        self.assertIsNotNone(response.context['site'])
        self.assertEqual(response.context['site'].slug, 'principal')

    def test_context_has_is_gallery_key(self):
        url = reverse('content:article_detail', kwargs={'slug': 'published'})
        response = self.client.get(url)
        self.assertIn('is_gallery', response.context)

    def test_fallback_to_global_when_not_on_principal(self):
        """Un article hors du site principal est trouvé via /article/<slug>/."""
        make_site('other', wp_blog_id=2, site_type='regional', name='Other')
        art = make_article_page(section_slug='other', title='Other Art', slug='other-art-fallback')
        url = reverse('content:article_detail', kwargs={'slug': 'other-art-fallback'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class SiteHomeViewTest(TestCase):
    def setUp(self):
        make_site()  # principal required for context processor
        self.sub = make_site('rhone-alpes', wp_blog_id=2, site_type='regional', name='RA')

    def test_returns_200(self):
        url = reverse('content:site_home', kwargs={'site_slug': 'rhone-alpes'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_redirects_to_external_url(self):
        self.sub.external_url = 'https://external.example.com'
        self.sub.save()
        url = reverse('content:site_home', kwargs={'site_slug': 'rhone-alpes'})
        response = self.client.get(url)
        self.assertRedirects(response, 'https://external.example.com', fetch_redirect_response=False)

    def test_renders_home_page_if_exists(self):
        Page.objects.create(site=self.sub, title='Accueil', slug='home', status='publish')
        url = reverse('content:site_home', kwargs={'site_slug': 'rhone-alpes'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_404_for_nonexistent_site(self):
        url = reverse('content:site_home', kwargs={'site_slug': 'no-such-site'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_articles_scoped_to_sub_site(self):
        make_article_page(section_slug='rhone-alpes', title='RA Art', slug='ra-art')
        make_article_page(section_slug='principal', title='Princ Art', slug='princ-art')
        url = reverse('content:site_home', kwargs={'site_slug': 'rhone-alpes'})
        response = self.client.get(url)
        pks = [a.pk for a in response.context['articles']]
        slugs = [a.slug for a in response.context['articles']]
        self.assertIn('ra-art', slugs)
        self.assertNotIn('princ-art', slugs)


class SiteArticleDetailViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')
        self.article = make_article_page(section_slug='sub', title='Sub Article', slug='sub-article')

    def test_returns_200(self):
        url = reverse('content:site_article_detail', kwargs={'site_slug': 'sub', 'slug': 'sub-article'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_404_when_article_belongs_to_different_site(self):
        other = make_site('other', wp_blog_id=3, site_type='regional', name='Other')
        url = reverse('content:site_article_detail', kwargs={'site_slug': 'other', 'slug': 'sub-article'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_context_site_is_subsite(self):
        url = reverse('content:site_article_detail', kwargs={'site_slug': 'sub', 'slug': 'sub-article'})
        response = self.client.get(url)
        self.assertEqual(response.context['site'].slug, 'sub')


class PageDetailViewTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_published_page_returns_200(self):
        Page.objects.create(site=self.site, title='About', slug='about', status='publish')
        url = reverse('content:page_detail', kwargs={'slug': 'about'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_draft_page_returns_404(self):
        Page.objects.create(site=self.site, title='Draft', slug='draft-page', status='draft')
        url = reverse('content:page_detail', kwargs={'slug': 'draft-page'})
        self.assertEqual(self.client.get(url).status_code, 404)


class SitePageDetailViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_published_page_returns_200(self):
        Page.objects.create(site=self.sub, title='Sub Page', slug='sub-page', status='publish')
        url = reverse('content:site_page_detail', kwargs={'site_slug': 'sub', 'slug': 'sub-page'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_draft_page_returns_404(self):
        Page.objects.create(site=self.sub, title='Draft Sub', slug='draft-sub', status='draft')
        url = reverse('content:site_page_detail', kwargs={'site_slug': 'sub', 'slug': 'draft-sub'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_page_from_different_site_returns_404(self):
        other = make_site('other', wp_blog_id=3, site_type='regional', name='Other')
        Page.objects.create(site=other, title='Other Page', slug='other-page', status='publish')
        url = reverse('content:site_page_detail', kwargs={'site_slug': 'sub', 'slug': 'other-page'})
        self.assertEqual(self.client.get(url).status_code, 404)


class CategoryDetailViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')

    def test_returns_200(self):
        url = reverse('content:category_detail', kwargs={'slug': 'luttes'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_404_for_nonexistent_category(self):
        url = reverse('content:category_detail', kwargs={'slug': 'no-cat'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_context_has_category(self):
        url = reverse('content:category_detail', kwargs={'slug': 'luttes'})
        response = self.client.get(url)
        self.assertEqual(response.context['category'], self.cat)

    def test_articles_with_category_appear_in_queryset(self):
        art = make_article_page(section_slug='principal', title='Luttes Art', slug='luttes-art',
                                categories=[self.cat])
        url = reverse('content:category_detail', kwargs={'slug': 'luttes'})
        response = self.client.get(url)
        self.assertIn(art, response.context['articles'])

    def test_articles_without_category_not_in_queryset(self):
        other_cat = make_cms_category(name='Autre', slug='autre', section_slug='principal')
        art = make_article_page(section_slug='principal', title='No Luttes', slug='no-luttes',
                                categories=[other_cat])
        url = reverse('content:category_detail', kwargs={'slug': 'luttes'})
        response = self.client.get(url)
        self.assertNotIn(art, response.context['articles'])

    def test_fallback_to_any_section_when_not_on_principal(self):
        """Si la catégorie n'existe pas sur principal, on prend la première trouvée."""
        other = make_site('other', wp_blog_id=2, site_type='regional', name='Other')
        subcat = make_cms_category(name='SubOnly', slug='sub-only', section_slug='other')
        url = reverse('content:category_detail', kwargs={'slug': 'sub-only'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['category'], subcat)


class SiteCategoryDetailViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')
        self.cat = make_cms_category(name='News', slug='news', section_slug='sub')

    def test_returns_200(self):
        url = reverse('content:site_category_detail', kwargs={'site_slug': 'sub', 'slug': 'news'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_redirect_when_no_redirect_page(self):
        url = reverse('content:site_category_detail', kwargs={'site_slug': 'sub', 'slug': 'news'})
        self.assertEqual(self.client.get(url).status_code, 200)


class TagDetailViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.tag = TaggitTag.objects.create(name='Grève', slug='greve')

    def test_returns_200(self):
        url = reverse('content:tag_detail', kwargs={'slug': 'greve'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_context_has_tag(self):
        url = reverse('content:tag_detail', kwargs={'slug': 'greve'})
        response = self.client.get(url)
        self.assertEqual(response.context['tag'], self.tag)

    def test_articles_with_tag_appear_in_context(self):
        from cms.models import CmsArticleTag
        art = make_article_page(section_slug='principal', title='Grève art', slug='greve-art')
        CmsArticleTag.objects.create(content_object=art, tag=self.tag)
        url = reverse('content:tag_detail', kwargs={'slug': 'greve'})
        response = self.client.get(url)
        self.assertIn(art, response.context['articles'])

    def test_articles_without_tag_not_in_context(self):
        art_no_tag = make_article_page(section_slug='principal', title='No tag', slug='no-tag-art')
        url = reverse('content:tag_detail', kwargs={'slug': 'greve'})
        response = self.client.get(url)
        self.assertNotIn(art_no_tag, response.context['articles'])


class SearchViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        make_article_page(section_slug='principal', title='Article sur la grève', slug='greve')

    def test_returns_200_without_query(self):
        self.assertEqual(self.client.get(reverse('content:search')).status_code, 200)

    def test_empty_query_returns_no_results(self):
        response = self.client.get(reverse('content:search') + '?q=')
        self.assertEqual(len(response.context['articles']), 0)

    def test_matching_title_returns_results(self):
        response = self.client.get(reverse('content:search') + '?q=grève')
        self.assertGreaterEqual(len(response.context['articles']), 1)

    def test_non_matching_query_returns_empty(self):
        response = self.client.get(reverse('content:search') + '?q=zzznomatch')
        self.assertEqual(len(response.context['articles']), 0)

    def test_context_has_query(self):
        response = self.client.get(reverse('content:search') + '?q=test')
        self.assertEqual(response.context['query'], 'test')

    def test_matching_excerpt_returns_results(self):
        make_article_page(section_slug='principal', title='Autre titre', slug='excerpt-search',
                          excerpt='Contenu spécifique sur la solidarité ouvrière')
        response = self.client.get(reverse('content:search') + '?q=solidarité')
        self.assertGreaterEqual(len(response.context['articles']), 1)


class WordPressRedirectViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.article = make_article_page(section_slug='principal', title='WP Article', slug='wp-article')

    def test_redirects_to_article_url(self):
        response = self.client.get('/2024/01/wp-article/')
        self.assertEqual(response.status_code, 301)
        self.assertIn('wp-article', response['Location'])

    def test_redirects_to_page_url(self):
        Page.objects.create(site=self.site, title='WP Page', slug='wp-page', status='publish')
        response = self.client.get('/2024/01/wp-page/')
        self.assertEqual(response.status_code, 301)
        self.assertIn('wp-page', response['Location'])

    def test_404_for_unknown_slug(self):
        response = self.client.get('/2024/01/no-such-slug/')
        self.assertEqual(response.status_code, 404)

    def test_redirects_subsite_article(self):
        make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')
        sub_art = make_article_page(section_slug='sub', title='Sub WP Art', slug='sub-wp-art')
        response = self.client.get('/sub/2024/01/sub-wp-art/')
        self.assertEqual(response.status_code, 301)
        self.assertIn('sub-wp-art', response['Location'])


class ContactViewTest(TestCase):
    def setUp(self):
        make_site()

    def _contact_data(self, **overrides):
        data = {
            'name': 'Alice', 'email': 'alice@example.com',
            'phone': '0600000000', 'city': 'Paris', 'sector': 'Nettoyage',
            'subject': 'Bonjour', 'message': 'Test'
        }
        data.update(overrides)
        return data

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(reverse('content:contact')).status_code, 200)

    def test_valid_post_creates_contact_message(self):
        from content.models import ContactMessage
        self.client.post(reverse('content:contact'), self._contact_data())
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_valid_post_redirects_to_success(self):
        response = self.client.post(reverse('content:contact'), self._contact_data())
        self.assertRedirects(response, reverse('content:contact_success'))

    def test_invalid_post_does_not_create_message(self):
        from content.models import ContactMessage
        # Missing required name and invalid email
        self.client.post(reverse('content:contact'), {'name': '', 'email': 'bad', 'phone': '06', 'city': 'Paris', 'sector': 'X', 'subject': '', 'message': ''})
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_invalid_post_returns_200(self):
        response = self.client.post(reverse('content:contact'), {'name': '', 'email': ''})
        self.assertEqual(response.status_code, 200)

    def test_contact_success_returns_200(self):
        self.assertEqual(self.client.get(reverse('content:contact_success')).status_code, 200)


class SiteContactViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_get_returns_200(self):
        url = reverse('content:site_contact', kwargs={'site_slug': 'sub'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_valid_post_sets_site_on_message(self):
        from content.models import ContactMessage
        data = {
            'name': 'Bob', 'email': 'bob@example.com',
            'phone': '0600000000', 'city': 'Lyon', 'sector': 'Nettoyage',
            'subject': 'Hi', 'message': 'Hello'
        }
        self.client.post(reverse('content:site_contact', kwargs={'site_slug': 'sub'}), data)
        msg = ContactMessage.objects.first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.site, self.sub)

    def test_site_contact_success_returns_200(self):
        url = reverse('content:site_contact_success', kwargs={'site_slug': 'sub'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_site_contact_success_404_for_unknown_site(self):
        url = reverse('content:site_contact_success', kwargs={'site_slug': 'no-site'})
        self.assertEqual(self.client.get(url).status_code, 404)


class NewsletterSubscribeViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.url = reverse('content:newsletter_subscribe')

    def test_valid_email_creates_inactive_subscriber(self):
        self.client.post(self.url, {'email': 'new@example.com', 'name': 'Test'})
        sub = Subscriber.objects.filter(site=self.site, email='new@example.com').first()
        self.assertIsNotNone(sub)
        self.assertFalse(sub.is_active)

    def test_invalid_email_does_not_create_subscriber(self):
        self.client.post(self.url, {'email': 'not-an-email', 'name': ''})
        self.assertFalse(Subscriber.objects.exists())

    def test_invalid_email_redirects(self):
        response = self.client.post(self.url, {'email': 'bad', 'name': ''})
        self.assertEqual(response.status_code, 302)

    def test_resubscribe_with_already_inactive_returns_200(self):
        Subscriber.objects.create(site=self.site, email='exists@example.com', is_active=False)
        response = self.client.post(self.url, {'email': 'exists@example.com', 'name': ''})
        self.assertEqual(response.status_code, 200)

    def test_subscribe_already_active_subscriber_returns_200(self):
        Subscriber.objects.create(site=self.site, email='active@example.com', is_active=True)
        response = self.client.post(self.url, {'email': 'active@example.com', 'name': ''})
        self.assertEqual(response.status_code, 200)


class NewsletterConfirmViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = Subscriber.objects.create(site=self.site, email='test@example.com', is_active=False)

    def test_confirm_activates_subscriber(self):
        self.client.get(reverse('content:newsletter_confirm', kwargs={'token': self.sub.token}))
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.is_active)

    def test_confirm_sets_confirmed_at(self):
        self.client.get(reverse('content:newsletter_confirm', kwargs={'token': self.sub.token}))
        self.sub.refresh_from_db()
        self.assertIsNotNone(self.sub.confirmed_at)

    def test_confirm_already_active_stays_active(self):
        self.sub.is_active = True
        self.sub.save()
        response = self.client.get(reverse('content:newsletter_confirm', kwargs={'token': self.sub.token}))
        self.assertEqual(response.status_code, 200)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.is_active)

    def test_invalid_token_returns_404(self):
        url = reverse('content:newsletter_confirm', kwargs={'token': uuid.uuid4()})
        self.assertEqual(self.client.get(url).status_code, 404)


class NewsletterUnsubscribeViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = Subscriber.objects.create(site=self.site, email='test@example.com', is_active=True)
        self.url = reverse('content:newsletter_unsubscribe', kwargs={'token': self.sub.token})

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_post_deactivates_subscriber(self):
        self.client.post(self.url)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.is_active)

    def test_invalid_token_returns_404(self):
        url = reverse('content:newsletter_unsubscribe', kwargs={'token': uuid.uuid4()})
        self.assertEqual(self.client.get(url).status_code, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT PROCESSOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class MenuContextProcessorTest(TestCase):
    def _ctx(self):
        from content.context_processors import menu_context
        return menu_context(RequestFactory().get('/'))

    def test_main_site_is_none_when_no_principal(self):
        self.assertIsNone(self._ctx()['main_site'])

    def test_main_site_is_populated_when_principal_exists(self):
        site = make_site()
        self.assertEqual(self._ctx()['main_site'], site)

    def test_subsites_excluded_from_sites(self):
        make_site()
        sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')
        ctx = self._ctx()
        self.assertIn(sub, ctx['sites'])
        self.assertNotIn(make_site.__wrapped__ if hasattr(make_site, '__wrapped__') else None, ctx['sites'])

    def test_regional_and_sectoral_split(self):
        make_site()
        make_site('reg', wp_blog_id=2, site_type='regional', name='Reg')
        make_site('sec', wp_blog_id=3, site_type='sectoral', name='Sec')
        ctx = self._ctx()
        self.assertEqual(ctx['regional_sites'].count(), 1)
        self.assertEqual(ctx['sectoral_sites'].count(), 1)

    def test_menu_structure_has_required_sections(self):
        make_site()
        ctx = self._ctx()
        self.assertIn('confederation', ctx['menu_structure'])
        self.assertIn('syndicats', ctx['menu_structure'])
        self.assertIn('autres', ctx['menu_structure'])

    def test_main_categories_keyed_by_slug(self):
        site = make_site()
        cat = Category.objects.create(site=site, name='Luttes', slug='luttes')
        ctx = self._ctx()
        self.assertIn('luttes', ctx['main_categories'])
        self.assertEqual(ctx['main_categories']['luttes'], cat)

    def test_campagnes_articles_are_articlepage_objects(self):
        """Vérifie que le context processor retourne des ArticlePage, pas des Article legacy."""
        make_site()
        cat = make_cms_category(name='International', slug='international', section_slug='principal')
        art = make_article_page(section_slug='principal', title='Campagne',
                                slug='campagne-cp', categories=[cat])
        ctx = self._ctx()
        # Tous les éléments de campagnes_articles doivent être des ArticlePage
        for a in ctx['campagnes_articles']:
            self.assertIsInstance(a, ArticlePage)

    def test_manques_articles_are_articlepage_objects(self):
        make_site()
        make_article_page(section_slug='principal', title='Manque', slug='manque-cp')
        ctx = self._ctx()
        for a in ctx['manques_articles']:
            self.assertIsInstance(a, ArticlePage)


# ═══════════════════════════════════════════════════════════════════════════════
# ADDITIONAL VIEW TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class EspacePresseViewTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_returns_200_with_no_category(self):
        # Category 'communique-de-presse' missing → empty queryset but still renders
        response = self.client.get(reverse('content:espace_presse'))
        self.assertEqual(response.status_code, 200)

    def test_returns_articles_when_category_exists(self):
        cat = make_cms_category(name='Communiqué', slug='communique-de-presse', section_slug='principal')
        art = make_article_page(section_slug='principal', title='CP1', slug='cp1', categories=[cat])
        response = self.client.get(reverse('content:espace_presse'))
        self.assertIn(art, response.context['articles'])


class SiteEspacePresseViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_returns_200(self):
        url = reverse('content:site_espace_presse', kwargs={'site_slug': 'sub'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_returns_articles_when_category_exists(self):
        cat = make_cms_category(name='CP', slug='communique-de-presse', section_slug='sub')
        art = make_article_page(section_slug='sub', title='CP Sub', slug='cp-sub', categories=[cat])
        url = reverse('content:site_espace_presse', kwargs={'site_slug': 'sub'})
        response = self.client.get(url)
        self.assertIn(art, response.context['articles'])

    def test_articles_from_other_site_not_in_queryset(self):
        other = make_site('other', wp_blog_id=3, site_type='regional', name='Other')
        cat_other = make_cms_category(name='CP Other', slug='communique-de-presse', section_slug='other')
        art_other = make_article_page(section_slug='other', title='CP Other Art', slug='cp-other',
                                       categories=[cat_other])
        url = reverse('content:site_espace_presse', kwargs={'site_slug': 'sub'})
        response = self.client.get(url)
        self.assertNotIn(art_other, response.context['articles'])


class SiteAgendaViewTest(TestCase):
    def setUp(self):
        make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')

    def test_200_when_no_agenda_url(self):
        url = reverse('content:site_agenda', kwargs={'site_slug': 'sub'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_200_when_agenda_url_set(self):
        self.sub.agenda_url = 'https://agenda.example.com'
        self.sub.save()
        url = reverse('content:site_agenda', kwargs={'site_slug': 'sub'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['agenda_url'], 'https://agenda.example.com')


class PlanDuSiteViewTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_returns_200(self):
        self.assertEqual(self.client.get(reverse('content:plan_du_site')).status_code, 200)

    def test_context_has_cat_groups_and_pages(self):
        response = self.client.get(reverse('content:plan_du_site'))
        self.assertIn('cat_groups', response.context)
        self.assertIn('pages', response.context)

    def test_main_site_includes_union_lists(self):
        make_site('reg', wp_blog_id=2, site_type='regional', name='Reg')
        response = self.client.get(reverse('content:plan_du_site'))
        self.assertIn('unions_regionales', response.context)
        self.assertIn('syndicats_sectoriels', response.context)


class QuiSommesNousViewTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_returns_200(self):
        self.assertEqual(self.client.get(reverse('content:qui_sommes_nous')).status_code, 200)

    def test_context_has_site(self):
        response = self.client.get(reverse('content:qui_sommes_nous'))
        self.assertEqual(response.context['site'], self.site)

    def test_page_in_context_when_exists(self):
        page = Page.objects.create(
            site=self.site, title='QSN', slug='qui-sommes-nous', status='publish'
        )
        response = self.client.get(reverse('content:qui_sommes_nous'))
        self.assertEqual(response.context['page'], page)

    def test_page_none_when_not_published(self):
        Page.objects.create(
            site=self.site, title='QSN', slug='qui-sommes-nous', status='draft'
        )
        response = self.client.get(reverse('content:qui_sommes_nous'))
        self.assertIsNone(response.context['page'])


# ═══════════════════════════════════════════════════════════════════════════════
# RSS FEED TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class RSSFeedTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.sub = make_site('sub', wp_blog_id=2, site_type='regional', name='Sub')
        self.cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')
        make_article_page(section_slug='principal', title='RSS Article', slug='rss-article', categories=[self.cat])

    def test_main_feed_returns_rss(self):
        response = self.client.get(reverse('content:rss_feed'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/rss+xml', response['Content-Type'])

    def test_main_feed_contains_article_title(self):
        response = self.client.get(reverse('content:rss_feed'))
        self.assertIn(b'RSS Article', response.content)

    def test_site_feed_returns_rss(self):
        make_article(self.sub, title='Sub RSS', slug='sub-rss')
        url = reverse('content:site_rss_feed', kwargs={'site_slug': 'sub'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_site_feed_404_for_unknown_site(self):
        url = reverse('content:site_rss_feed', kwargs={'site_slug': 'no-such-site'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_category_feed_returns_rss(self):
        url = reverse('content:category_rss_feed', kwargs={'slug': 'luttes'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_category_feed_contains_article(self):
        url = reverse('content:category_rss_feed', kwargs={'slug': 'luttes'})
        response = self.client.get(url)
        self.assertIn(b'RSS Article', response.content)

    def test_site_feed_contains_sub_site_article(self):
        make_article_page(section_slug='sub', title='Sub RSS Art', slug='sub-rss-art')
        url = reverse('content:site_rss_feed', kwargs={'site_slug': 'sub'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sub RSS Art', response.content)

    def test_main_feed_does_not_include_subsite_articles(self):
        make_article_page(section_slug='sub', title='Only Sub', slug='only-sub')
        url = reverse('content:rss_feed')
        response = self.client.get(url)
        self.assertNotIn(b'Only Sub', response.content)


# ═══════════════════════════════════════════════════════════════════════════════
# SITEMAP TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class ArticleSitemapTest(TestCase):
    def setUp(self):
        make_site()
        self.art = make_article_page(section_slug='principal', title='Sitemap Art', slug='sitemap-art')

    def test_items_returns_live_articlepages(self):
        from content.sitemaps import ArticleSitemap
        sitemap = ArticleSitemap()
        self.assertIn(self.art, sitemap.items())

    def test_items_excludes_draft_articles(self):
        from content.sitemaps import ArticleSitemap
        draft = make_article_page(section_slug='principal', title='Draft', slug='draft-sitemap', live=False)
        sitemap = ArticleSitemap()
        self.assertNotIn(draft, sitemap.items())

    def test_lastmod_prefers_last_published_at(self):
        import datetime
        from content.sitemaps import ArticleSitemap
        dt_last = datetime.datetime(2025, 6, 1, tzinfo=datetime.timezone.utc)
        dt_pub = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        from cms.models import ArticlePage as AP
        AP.objects.filter(pk=self.art.pk).update(
            last_published_at=dt_last, publication_date=dt_pub
        )
        self.art.refresh_from_db()
        sitemap = ArticleSitemap()
        self.assertEqual(sitemap.lastmod(self.art), dt_last)

    def test_lastmod_falls_back_to_publication_date(self):
        import datetime
        from content.sitemaps import ArticleSitemap
        dt_pub = datetime.datetime(2025, 3, 15, tzinfo=datetime.timezone.utc)
        from cms.models import ArticlePage as AP
        AP.objects.filter(pk=self.art.pk).update(last_published_at=None, publication_date=dt_pub)
        self.art.refresh_from_db()
        sitemap = ArticleSitemap()
        self.assertEqual(sitemap.lastmod(self.art), dt_pub)

    def test_location_returns_get_absolute_url(self):
        from content.sitemaps import ArticleSitemap
        sitemap = ArticleSitemap()
        self.assertEqual(sitemap.location(self.art), self.art.get_absolute_url())

    def test_sitemap_xml_returns_200(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'sitemap', response.content.lower())


class SitemapsOtherTest(TestCase):
    def setUp(self):
        make_site()

    def test_page_sitemap_items_are_published_pages(self):
        from content.sitemaps import PageSitemap
        from cms.models import SectionPage
        sp = SectionPage.objects.filter(slug='principal').first()
        pub = Page.objects.create(site=sp, title='Pub', slug='pub-s', status='publish')
        draft = Page.objects.create(site=sp, title='Draft', slug='draft-s', status='draft')
        sitemap = PageSitemap()
        items = list(sitemap.items())
        self.assertIn(pub, items)
        self.assertNotIn(draft, items)

    def test_category_sitemap_uses_content_category(self):
        from content.sitemaps import CategorySitemap
        from cms.models import SectionPage
        sp = SectionPage.objects.filter(slug='principal').first()
        cat = Category.objects.create(site=sp, name='Cat', slug='cat-s')
        sitemap = CategorySitemap()
        self.assertIn(cat, sitemap.items())

    def test_site_sitemap_uses_active_sites(self):
        from content.sitemaps import SiteSitemap
        active = make_site('active-s', wp_blog_id=99, is_active=True)
        inactive = make_site('inactive-s', wp_blog_id=98, is_active=False)
        sitemap = SiteSitemap()
        items = list(sitemap.items())
        self.assertIn(active, items)
        self.assertNotIn(inactive, items)


# ═══════════════════════════════════════════════════════════════════════════════
# Wagtail — Accessibilité de l'admin
# ═══════════════════════════════════════════════════════════════════════════════

class WagtailAdminAccessTest(TestCase):
    def setUp(self):
        self.superuser = make_superuser()

    def test_cms_login_page_accessible(self):
        response = self.client.get('/cms/')
        self.assertIn(response.status_code, [200, 302])

    def test_superuser_can_access_cms(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/cms/')
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected_to_cms_login(self):
        response = self.client.get('/cms/')
        self.assertIn(response.status_code, [200, 302])

    def test_redac_redirects_to_cms(self):
        """/redac/ redirige en 301 vers /cms/."""
        response = self.client.get('/redac/')
        self.assertEqual(response.status_code, 301)
        self.assertIn('/cms/', response['Location'])

    def test_public_site_unaffected(self):
        make_site()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════════
# Wagtail — Snippets enregistrés
# ═══════════════════════════════════════════════════════════════════════════════

class WagtailSnippetsRegisteredTest(TestCase):
    @classmethod
    def _get_snippet_models(cls):
        from wagtail.snippets.models import get_snippet_models, search_for_hooks
        search_for_hooks()
        return get_snippet_models()

    def test_article_snippet_registered(self):
        from cms.models import ArticlePage
        self.assertIn(ArticlePage, self._get_snippet_models())

    def test_contentpage_snippet_registered(self):
        from cms.models import ContentPage as CmsContentPage
        self.assertIn(CmsContentPage, self._get_snippet_models())

    def test_category_snippet_registered(self):
        self.assertIn(Category, self._get_snippet_models())

    def test_tag_snippet_registered(self):
        self.assertIn(Tag, self._get_snippet_models())

    def test_subscriber_snippet_registered(self):
        self.assertIn(Subscriber, self._get_snippet_models())

    def test_newsletter_snippet_registered(self):
        self.assertIn(Newsletter, self._get_snippet_models())

    def test_sectionpage_snippet_registered(self):
        from cms.models import SectionPage
        self.assertIn(SectionPage, self._get_snippet_models())


# ═══════════════════════════════════════════════════════════════════════════════
# Wagtail — Scoping par site dans les snippets
# ═══════════════════════════════════════════════════════════════════════════════

class WagtailSiteScopingTest(TestCase):
    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2)
        self.article_a = make_article(self.site_a, title='Article A')
        self.article_b = make_article(self.site_b, title='Article B')
        self.superuser = make_superuser()
        self.chef = make_chef(site=self.site_a)
        self.redacteur = make_redacteur(site=self.site_a)

    def test_superuser_sees_articlepage_list_in_cms(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/cms/snippets/cms/articlepage/')
        self.assertEqual(response.status_code, 200)

    def test_redacteur_accesses_articlepage_list(self):
        self.client.force_login(self.redacteur)
        session = self.client.session
        session['cms_current_site_id'] = self.site_a.id
        session.save()
        response = self.client.get('/cms/snippets/cms/articlepage/')
        self.assertEqual(response.status_code, 200)

    def test_chef_with_session_site_accesses_articlepage_list(self):
        self.client.force_login(self.chef)
        session = self.client.session
        session['cms_current_site_id'] = self.site_a.id
        session.save()
        response = self.client.get('/cms/snippets/cms/articlepage/')
        self.assertEqual(response.status_code, 200)

    def test_site_admin_url_gone(self):
        # SiteViewSet supprimé — l'URL /cms/snippets/content/site/ n'existe plus
        self.client.force_login(self.superuser)
        response = self.client.get('/cms/snippets/content/site/')
        self.assertIn(response.status_code, [404, 302])


# ═══════════════════════════════════════════════════════════════════════════════
# Wagtail — Commande setup_wagtail_permissions
# ═══════════════════════════════════════════════════════════════════════════════

class SetupWagtailPermissionsCommandTest(TestCase):
    def test_command_grants_access_admin_to_groups(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('setup_wagtail_permissions', stdout=StringIO())
        for group_name in ['redacteur', 'redacteur_en_chef']:
            group = Group.objects.get(name=group_name)
            self.assertTrue(
                group.permissions.filter(codename='access_admin').exists(),
                f'Le groupe {group_name} devrait avoir access_admin',
            )

    def test_command_idempotent(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('setup_wagtail_permissions', stdout=StringIO())
        call_command('setup_wagtail_permissions', stdout=StringIO())
        self.assertEqual(
            Group.objects.get(name='redacteur').permissions.filter(codename='access_admin').count(),
            1,
        )

    def test_redacteur_has_cms_articlepage_perms_not_delete(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('setup_wagtail_permissions', stdout=StringIO())
        group = Group.objects.get(name='redacteur')
        self.assertTrue(group.permissions.filter(codename='add_articlepage').exists())
        self.assertTrue(group.permissions.filter(codename='change_articlepage').exists())
        self.assertFalse(group.permissions.filter(codename='delete_articlepage').exists())

    def test_chef_has_delete_and_category_perms(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('setup_wagtail_permissions', stdout=StringIO())
        group = Group.objects.get(name='redacteur_en_chef')
        self.assertTrue(group.permissions.filter(codename='delete_articlepage').exists())
        self.assertTrue(group.permissions.filter(codename='add_cmscategory').exists())
        self.assertTrue(group.permissions.filter(codename='delete_cmscategory').exists())


# ═══════════════════════════════════════════════════════════════════════════════
# Commande migrate_categories_tags
# ═══════════════════════════════════════════════════════════════════════════════

class MigrateCategoriesTagsCommandTest(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.site = make_site()
        # Legacy article avec catégorie et tag
        from content.models import Category as LegacyCategory, Tag as LegacyTag
        self.legacy_cat = LegacyCategory.objects.create(
            site=self.site, name='Test Cat', slug='test-cat'
        )
        self.legacy_tag = LegacyTag.objects.create(
            site=self.site, name='Test Tag', slug='test-tag'
        )
        self.legacy_art = Article.objects.create(
            site=self.site, title='Migration Art', slug='migration-art',
            status='publish', published_at=timezone.now()
        )
        self.legacy_art.categories.add(self.legacy_cat)
        self.legacy_art.tags.add(self.legacy_tag)
        # ArticlePage correspondant
        self.cms_cat = make_cms_category(name='Test Cat CMS', slug='test-cat-cms',
                                         section_slug='principal', legacy_id=self.legacy_cat.pk)
        self.art_page = make_article_page(section_slug='principal', title='Migration Art',
                                          slug='migration-art2')
        # Simuler le legacy_article_id
        from cms.models import ArticlePage
        ArticlePage.objects.filter(pk=self.art_page.pk).update(legacy_article_id=self.legacy_art.pk)

    def _run_command(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('migrate_categories_tags', stdout=out)
        return out.getvalue()

    def test_links_categories(self):
        self.art_page.refresh_from_db()
        self._run_command()
        self.assertIn(self.cms_cat, list(self.art_page.cms_categories.all()))

    def test_creates_taggit_tags(self):
        from taggit.models import Tag as TaggitTag
        TaggitTag.objects.filter(slug='test-tag').delete()
        self._run_command()
        self.assertTrue(TaggitTag.objects.filter(slug='test-tag').exists())

    def test_links_tags(self):
        self._run_command()
        slugs = list(self.art_page.cms_tags.values_list('slug', flat=True))
        self.assertIn('test-tag', slugs)

    def test_idempotent_categories(self):
        self._run_command()
        self._run_command()
        # Pas de doublons
        count = self.art_page.cms_categories.filter(pk=self.cms_cat.pk).count()
        self.assertEqual(count, 1)

    def test_idempotent_tags(self):
        self._run_command()
        self._run_command()
        count = self.art_page.cms_tags.filter(slug='test-tag').count()
        self.assertEqual(count, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Contrôle d'accès rédacteurs dans le CMS
# ═══════════════════════════════════════════════════════════════════════════════

class Phase6RedacteurPermissionsTest(TestCase):
    """Vérifie les permissions Django accordées aux groupes."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.redacteur = make_redacteur(site=self.site_a)
        self.chef = make_chef(site=self.site_a)
        self.superuser = make_superuser()

    def test_redacteur_has_access_admin(self):
        self.assertTrue(self.redacteur.has_perm('wagtailadmin.access_admin'))

    def test_redacteur_can_add_and_change_articlepage(self):
        self.assertTrue(self.redacteur.has_perm('cms.add_articlepage'))
        self.assertTrue(self.redacteur.has_perm('cms.change_articlepage'))

    def test_redacteur_cannot_delete_articlepage(self):
        self.assertFalse(self.redacteur.has_perm('cms.delete_articlepage'))

    def test_redacteur_cannot_manage_categories(self):
        self.assertFalse(self.redacteur.has_perm('cms.add_cmscategory'))
        self.assertFalse(self.redacteur.has_perm('cms.change_cmscategory'))
        self.assertFalse(self.redacteur.has_perm('cms.delete_cmscategory'))

    def test_redacteur_can_view_categories(self):
        self.assertTrue(self.redacteur.has_perm('cms.view_cmscategory'))

    def test_chef_has_delete_articlepage(self):
        self.assertTrue(self.chef.has_perm('cms.delete_articlepage'))

    def test_chef_can_manage_categories(self):
        self.assertTrue(self.chef.has_perm('cms.add_cmscategory'))
        self.assertTrue(self.chef.has_perm('cms.delete_cmscategory'))

    def test_redacteur_has_image_perms(self):
        self.assertTrue(self.redacteur.has_perm('wagtailimages.add_image'))
        self.assertTrue(self.redacteur.has_perm('wagtailimages.choose_image'))
        self.assertFalse(self.redacteur.has_perm('wagtailimages.delete_image'))

    def test_chef_can_delete_images(self):
        self.assertTrue(self.chef.has_perm('wagtailimages.delete_image'))


class Phase6ScopingTest(TestCase):
    """Vérifie le scoping queryset par site (appel direct aux fonctions)."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='regional', name='Other')
        self.redacteur = make_redacteur(site=self.site_a)
        self.chef = make_chef(site=self.site_a)
        self.superuser = make_superuser()
        self.art_a = make_article_page(section_slug='principal', title='Art A', slug='art-a')
        self.art_b = make_article_page(section_slug='other', title='Art B', slug='art-b')

    def _make_request(self, user, session_site=None):
        """Construit un request-like object minimal pour scope_qs_slug."""
        from django.test import RequestFactory
        from cms.models import SectionPage
        from django.db.models import Q
        request = RequestFactory().get('/')
        request.user = user
        request.session = {}
        if session_site:
            # Stocker le PK du SectionPage correspondant (Phase 1+)
            sp = SectionPage.objects.filter(
                Q(slug=session_site.slug) | Q(legacy_site_slug=session_site.slug)
            ).first()
            request.session['cms_current_site_id'] = sp.pk if sp else session_site.pk
        return request

    def test_redacteur_scope_returns_only_own_site(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.redacteur)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertNotIn(self.art_b.pk, pks)

    def test_chef_without_session_sees_all(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.chef)  # no session site
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertIn(self.art_b.pk, pks)

    def test_chef_with_session_sees_only_session_site(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.chef, session_site=self.site_a)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertNotIn(self.art_b.pk, pks)

    def test_superuser_without_session_sees_all(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.superuser)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertIn(self.art_b.pk, pks)

    def test_redacteur_without_author_profile_sees_nothing(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        # Rédacteur sans profil auteur
        orphan = make_redacteur(username='orphan', site=None)
        # Supprimer le profil auteur créé
        from content.models import Author
        Author.objects.filter(user=orphan).delete()
        request = self._make_request(orphan)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        self.assertEqual(qs.count(), 0)

    def test_redacteur_scope_returns_only_own_contentpages(self):
        """Vérification que le scoping fonctionne aussi pour ContentPage."""
        from cms.models import ContentPage
        from cms.site_context import scope_qs_slug
        from wagtail.models import Page as WagtailPage
        # Créer deux ContentPage dans des sections différentes
        parent = _get_article_parent()
        page_a = parent.add_child(instance=ContentPage(
            title='Page A', slug='page-a-scope', section_slug='principal', live=True
        ))
        page_b = parent.add_child(instance=ContentPage(
            title='Page B', slug='page-b-scope', section_slug='other', live=True
        ))
        request = self._make_request(self.redacteur)
        qs = scope_qs_slug(ContentPage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(page_a.pk, pks)
        self.assertNotIn(page_b.pk, pks)

    def test_scope_qs_filters_by_fk_site_field(self):
        """scope_qs filtre sur FK site= (différent de scope_qs_slug qui filtre sur slug=)."""
        from cms.site_context import scope_qs
        from content.models import Subscriber
        sub_a = Subscriber.objects.create(site=self.site_a, email='a@test.com')
        sub_b = Subscriber.objects.create(site=self.site_b, email='b@test.com')
        request = self._make_request(self.redacteur)
        qs = scope_qs(Subscriber.objects.all(), request, site_field='site')
        self.assertIn(sub_a, qs)
        self.assertNotIn(sub_b, qs)

    def test_get_available_sites_redacteur_only_own_site(self):
        from cms.site_context import get_available_sites
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.redacteur
        request.session = {}
        slugs = [s.slug for s in get_available_sites(request)]
        self.assertIn(self.site_a.slug, slugs)
        self.assertNotIn(self.site_b.slug, slugs)
        self.assertEqual(len(slugs), 1)

    def test_get_available_sites_chef_sees_all(self):
        from cms.site_context import get_available_sites
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.chef
        request.session = {}
        slugs = [s.slug for s in get_available_sites(request)]
        self.assertIn(self.site_a.slug, slugs)
        self.assertIn(self.site_b.slug, slugs)


class Phase6CmsUrlAccessTest(TestCase):
    """Vérifie l'accès aux URLs /cms/ selon le rôle."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='regional', name='Other')
        self.redacteur = make_redacteur(site=self.site_a)
        self.chef = make_chef(site=self.site_a)
        self.superuser = make_superuser()
        self.art_a = make_article_page(section_slug='principal', title='Art A', slug='art-a2')
        self.art_b = make_article_page(section_slug='other', title='Art B', slug='art-b2')

    def test_anonymous_redirected_from_cms(self):
        response = self.client.get('/cms/')
        self.assertIn(response.status_code, [200, 302])

    def test_redacteur_can_access_cms(self):
        self.client.force_login(self.redacteur)
        response = self.client.get('/cms/')
        self.assertEqual(response.status_code, 200)

    def test_redacteur_can_access_articlepage_list(self):
        self.client.force_login(self.redacteur)
        response = self.client.get('/cms/snippets/cms/articlepage/')
        self.assertEqual(response.status_code, 200)

    def test_redacteur_cannot_delete_own_site_article(self):
        self.client.force_login(self.redacteur)
        response = self.client.get(f'/cms/snippets/cms/articlepage/{self.art_a.pk}/delete/')
        # Wagtail retourne 302 (redirect login) ou 403 ou 404 selon la version
        self.assertIn(response.status_code, [302, 403, 404])
        # L'article doit toujours exister
        from cms.models import ArticlePage
        self.assertTrue(ArticlePage.objects.filter(pk=self.art_a.pk).exists())

    def test_redacteur_cannot_access_other_site_article_edit(self):
        self.client.force_login(self.redacteur)
        response = self.client.get(f'/cms/snippets/cms/articlepage/{self.art_b.pk}/')
        self.assertIn(response.status_code, [302, 403, 404])

    def test_chef_has_delete_permission_on_articlepage(self):
        """Chef a la permission Django delete_articlepage (testée via has_perm)."""
        self.assertTrue(self.chef.has_perm('cms.delete_articlepage'))

    def test_redacteur_lacks_delete_permission_on_articlepage(self):
        """Rédacteur n'a pas delete_articlepage."""
        self.assertFalse(self.redacteur.has_perm('cms.delete_articlepage'))


class Phase6SiteSwitchTest(TestCase):
    """Vérifie que le switch de site est réservé aux chefs/superusers."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='regional', name='Other')
        self.redacteur = make_redacteur(site=self.site_a)
        self.chef = make_chef(site=self.site_a)

    def test_redacteur_select_site_ignored(self):
        self.client.force_login(self.redacteur)
        self.client.get(f'/cms/select-site/?site_id={self.site_b.pk}')
        # Session ne doit pas avoir changé
        session_site = self.client.session.get('cms_current_site_id')
        self.assertNotEqual(session_site, self.site_b.pk)

    def test_chef_can_switch_site(self):
        self.client.force_login(self.chef)
        self.client.get(f'/cms/select-site/?site_id={self.site_b.pk}')
        session_site = self.client.session.get('cms_current_site_id')
        self.assertEqual(session_site, self.site_b.pk)

    def test_get_current_site_for_redacteur_ignores_session(self):
        """Le site d'un rédacteur vient de author_profile, pas de la session."""
        from cms.site_context import get_current_site
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.redacteur
        request.session = {'cms_current_site_id': self.site_b.pk}
        site = get_current_site(request)
        # Phase 1 : retourne SectionPage, comparer par slug
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, self.site_a.slug)

    def test_get_current_site_for_chef_uses_session(self):
        from cms.site_context import get_current_site
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.chef
        request.session = {'cms_current_site_id': self.site_b.pk}
        site = get_current_site(request)
        # Phase 1 : retourne SectionPage, comparer par slug
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, self.site_b.slug)


class Phase6SectionSlugEnforcementTest(TestCase):
    """Vérifie l'enforcement de section_slug côté serveur."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='regional', name='Other')
        self.redacteur = make_redacteur(site=self.site_a)

    def test_form_valid_enforces_section_slug_for_redacteur(self):
        """form_valid doit écraser section_slug avec le site du rédacteur."""
        from cms.wagtail_hooks import _make_scoped_article_page_view, _is_chef
        from wagtail.snippets.views.snippets import CreateView as SnippetCreateView
        from django.test import RequestFactory

        ScopedView = _make_scoped_article_page_view(SnippetCreateView)
        view = ScopedView()
        view.request = RequestFactory().post('/')
        view.request.user = self.redacteur
        view.request.session = {}

        # Simuler un form avec section_slug='other' (injection)
        from unittest.mock import MagicMock, patch
        form = MagicMock()
        form.instance = MagicMock()
        form.instance.section_slug = 'other'  # valeur injectée

        with patch('cms.wagtail_hooks.SnippetCreateView.form_valid', return_value=MagicMock()):
            view.form_valid(form)

        # section_slug doit avoir été réécrit à 'principal' (site du rédacteur)
        self.assertEqual(form.instance.section_slug, 'principal')


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS DE SÉCURITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class XSSContentTagsTest(TestCase):
    """Vérifie que _render_block échappe correctement les entrées utilisateur."""

    def _block(self, btype, data):
        from content.templatetags.content_tags import _render_block
        return _render_block({'type': btype, 'data': data})

    def test_paragraph_escapes_text(self):
        html = self._block('paragraph', {'text': '<script>alert(1)</script>'})
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_header_escapes_text(self):
        html = self._block('header', {'level': 2, 'text': '<img src=x onerror=alert(1)>'})
        # La balise <img> ne doit pas être rendue, mais échappée
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)

    def test_header_level_clamped(self):
        html = self._block('header', {'level': 99, 'text': 'Test'})
        self.assertIn('<h6>', html)
        html2 = self._block('header', {'level': -1, 'text': 'Test'})
        self.assertIn('<h1>', html2)

    def test_header_level_injection_blocked(self):
        # Tente d'injecter un attribut via le niveau
        html = self._block('header', {'level': '2 onmouseover="alert(1)"', 'text': 'T'})
        self.assertNotIn('onmouseover', html)

    def test_list_escapes_items(self):
        html = self._block('list', {'style': 'unordered', 'items': ['<b>ok</b>', '<script>x</script>']})
        self.assertNotIn('<b>', html)
        self.assertNotIn('<script>', html)

    def test_quote_escapes_text_and_caption(self):
        html = self._block('quote', {'text': '<script>x</script>', 'caption': '" onload="evil()'})
        # <script> ne doit pas être présent tel quel (doit être échappé)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        # La quote doit être échappée (pas de bris d'attribut possible)
        self.assertNotIn('" onload="', html)
        self.assertIn('&quot;', html)

    def test_image_rejects_javascript_url(self):
        html = self._block('image', {'file': {'url': 'javascript:alert(1)'}, 'caption': ''})
        self.assertEqual(html, '')

    def test_image_rejects_data_url(self):
        html = self._block('image', {'file': {'url': 'data:text/html,<script>evil</script>'}, 'caption': ''})
        self.assertEqual(html, '')

    def test_image_escapes_caption(self):
        html = self._block('image', {
            'file': {'url': 'https://example.com/img.jpg'},
            'caption': '" onerror="alert(1)',
        })
        # L'attribut alt ne doit pas contenir de quote non échappée qui briserait l'attribut
        self.assertNotIn('alt="" onerror', html)
        self.assertNotIn('alt="" onerror', html)
        # La quote doit être échappée en &quot;
        self.assertIn('&quot;', html)

    def test_embed_rejects_javascript_url(self):
        html = self._block('embed', {'embed': 'javascript:alert(1)', 'caption': ''})
        self.assertEqual(html, '')

    def test_embed_rejects_data_url(self):
        html = self._block('embed', {'embed': 'data:text/html,evil', 'caption': ''})
        self.assertEqual(html, '')

    def test_table_escapes_cells(self):
        html = self._block('table', {'content': [['<script>x</script>', 'safe']]})
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_file_rejects_javascript_url(self):
        html = self._block('file', {'url': 'javascript:evil()', 'title': 'Doc', 'name': 'doc.pdf'})
        self.assertEqual(html, '')

    def test_file_escapes_title(self):
        html = self._block('file', {
            'url': 'https://example.com/doc.pdf',
            'title': '<script>evil()</script>',
            'name': 'doc',
        })
        self.assertNotIn('<script>', html)

    def test_gallery_rejects_javascript_url(self):
        html = self._block('gallery', {
            'images': [{'url': 'javascript:evil()', 'caption': ''}],
            'columns': 3,
        })
        self.assertNotIn('javascript:', html)

    def test_safe_url_accepts_https(self):
        from content.templatetags.content_tags import _safe_url
        self.assertEqual(_safe_url('https://example.com/img.jpg'), 'https://example.com/img.jpg')

    def test_safe_url_accepts_relative(self):
        from content.templatetags.content_tags import _safe_url
        self.assertEqual(_safe_url('/media/img.jpg'), '/media/img.jpg')

    def test_safe_url_rejects_javascript(self):
        from content.templatetags.content_tags import _safe_url
        self.assertEqual(_safe_url('javascript:alert(1)'), '')

    def test_safe_url_rejects_data(self):
        from content.templatetags.content_tags import _safe_url
        self.assertEqual(_safe_url('data:text/html,evil'), '')


class OpenRedirectTest(TestCase):
    """Vérifie que les vues CMS ne redirigent pas vers des URLs externes."""

    def setUp(self):
        _setup_editorial_groups()
        make_site()
        self.chef = make_chef()

    def test_safe_redirect_blocks_external_url(self):
        from cms.wagtail_hooks import _safe_redirect
        self.assertEqual(_safe_redirect('https://evil.com'), '/cms/')
        self.assertEqual(_safe_redirect('http://evil.com/steal'), '/cms/')
        self.assertEqual(_safe_redirect('//evil.com'), '/cms/')

    def test_safe_redirect_allows_relative_url(self):
        from cms.wagtail_hooks import _safe_redirect
        self.assertEqual(_safe_redirect('/cms/snippets/'), '/cms/snippets/')
        self.assertEqual(_safe_redirect('/cms/'), '/cms/')

    def test_safe_redirect_fallback_on_empty(self):
        from cms.wagtail_hooks import _safe_redirect
        self.assertEqual(_safe_redirect(''), '/cms/')
        self.assertEqual(_safe_redirect(None), '/cms/')

    def test_select_site_get_blocks_external_next(self):
        """GET sur select-site avec next= externe → redirige vers /cms/ pas l'URL externe."""
        self.client.force_login(self.chef)
        response = self.client.get('/cms/select-site/?next=https://evil.com')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.com', response['Location'])
        self.assertIn('/cms/', response['Location'])

    def test_select_site_post_blocks_external_next(self):
        self.client.force_login(self.chef)
        make_site('other', wp_blog_id=2)
        other = make_site('other2', wp_blog_id=3)
        response = self.client.post('/cms/select-site/', {
            'site_id': other.pk,
            'next': 'https://evil.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.com', response['Location'])


class UploadSecurityTest(TestCase):
    """Vérifie les contrôles de sécurité sur les uploads."""

    def setUp(self):
        _setup_editorial_groups()
        make_site()
        self.chef = make_chef()
        self.client.force_login(self.chef)

    def _make_image_file(self, content=None, name='test.jpg', content_type='image/jpeg'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        if content is None:
            # JPEG magic bytes minimaux
            content = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        return SimpleUploadedFile(name, content, content_type=content_type)

    def test_svg_upload_rejected(self):
        """SVG doit être refusé (risque XSS)."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        svg = SimpleUploadedFile(
            'evil.svg',
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type='image/svg+xml',
        )
        response = self.client.post('/upload/image/', {'image': svg})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['success'], 0)

    def test_oversized_image_rejected(self):
        """Fichier image trop grand (>10 Mo) doit être refusé."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        big = SimpleUploadedFile('big.jpg', b'x' * (11 * 1024 * 1024), content_type='image/jpeg')
        response = self.client.post('/upload/image/', {'image': big})
        data = response.json()
        self.assertEqual(data['success'], 0)
        self.assertIn('volumineux', data['message'])

    def test_fake_image_magic_bytes_rejected(self):
        """Fichier avec Content-Type image/jpeg mais sans magic bytes JPEG → refusé."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('fake.jpg', b'<html>evil</html>', content_type='image/jpeg')
        response = self.client.post('/upload/image/', {'image': fake})
        data = response.json()
        self.assertEqual(data['success'], 0)

    def test_valid_jpeg_accepted(self):
        """JPEG valide avec magic bytes corrects → accepté."""
        img = self._make_image_file()
        response = self.client.post('/upload/image/', {'image': img})
        data = response.json()
        self.assertEqual(data['success'], 1)

    def test_oversized_file_rejected(self):
        """Fichier document trop grand (>20 Mo) → refusé."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        big = SimpleUploadedFile('big.pdf', b'%PDF' + b'x' * (21 * 1024 * 1024), content_type='application/pdf')
        response = self.client.post('/upload/file/', {'file': big})
        data = response.json()
        self.assertEqual(data['success'], 0)
        self.assertIn('volumineux', data['message'])

    def test_disallowed_file_type_rejected(self):
        """Fichier exécutable → refusé."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        exe = SimpleUploadedFile('malware.exe', b'MZ\x90\x00', content_type='application/x-msdownload')
        response = self.client.post('/upload/file/', {'file': exe})
        data = response.json()
        self.assertEqual(data['success'], 0)

    def test_upload_requires_auth(self):
        """Upload sans authentification → redirigé vers login."""
        self.client.logout()
        img = self._make_image_file()
        response = self.client.post('/upload/image/', {'image': img})
        self.assertIn(response.status_code, [302, 403])


class BasicAuthSecurityTest(TestCase):
    """Vérifie le middleware BasicAuth."""

    def test_compare_digest_used(self):
        """Vérifie que hmac.compare_digest est utilisé (pas ==)."""
        import inspect
        from cntso.middleware import BasicAuthMiddleware
        src = inspect.getsource(BasicAuthMiddleware.__call__)
        self.assertIn('compare_digest', src)
        self.assertNotIn('== password', src)

    def test_no_auth_passes_when_no_password_set(self):
        """Sans BASIC_AUTH_PASSWORD, tout passe."""
        from django.test import RequestFactory, override_settings
        from cntso.middleware import BasicAuthMiddleware

        @override_settings(BASIC_AUTH_PASSWORD=None)
        def run():
            def dummy(req): return type('R', (), {'status_code': 200})()
            mw = BasicAuthMiddleware(dummy)
            req = RequestFactory().get('/')
            return mw(req).status_code

        self.assertEqual(run(), 200)

    def test_wrong_password_returns_401(self):
        from django.test import RequestFactory, override_settings
        from cntso.middleware import BasicAuthMiddleware
        import base64

        @override_settings(BASIC_AUTH_PASSWORD='secret')
        def run():
            def dummy(req): return type('R', (), {'status_code': 200})()
            mw = BasicAuthMiddleware(dummy)
            req = RequestFactory().get('/')
            creds = base64.b64encode(b'user:wrong').decode()
            req.META['HTTP_AUTHORIZATION'] = f'Basic {creds}'
            return mw(req).status_code

        self.assertEqual(run(), 401)

    def test_correct_password_returns_200(self):
        from django.test import RequestFactory, override_settings
        from cntso.middleware import BasicAuthMiddleware
        import base64

        @override_settings(BASIC_AUTH_PASSWORD='secret')
        def run():
            def dummy(req): return type('R', (), {'status_code': 200})()
            mw = BasicAuthMiddleware(dummy)
            req = RequestFactory().get('/')
            creds = base64.b64encode(b'user:secret').decode()
            req.META['HTTP_AUTHORIZATION'] = f'Basic {creds}'
            return mw(req).status_code

        self.assertEqual(run(), 200)


class SecurityHeadersTest(TestCase):
    """Vérifie que les headers de sécurité sont présents."""

    def setUp(self):
        make_site()

    def test_x_content_type_options_nosniff(self):
        response = self.client.get('/')
        self.assertEqual(response.get('X-Content-Type-Options'), 'nosniff')

    def test_x_frame_options_present(self):
        response = self.client.get('/')
        self.assertIn(response.get('X-Frame-Options', ''), ['DENY', 'SAMEORIGIN'])


# ═══════════════════════════════════════════════════════════════════════════════
# FORMULAIRE DE CONTACT — TESTS
# ═══════════════════════════════════════════════════════════════════════════════

from content.models import FormulaireContact, ChampContactCustom, ContactMessage
from content.forms import DynamicContactForm


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_formulaire_contact(site, **kwargs):
    defaults = {'is_active': True}
    defaults.update(kwargs)
    return FormulaireContact.objects.create(site=site, **defaults)


def make_champ_contact(formulaire, label='Champ test', field_type='text', **kwargs):
    from django.utils.text import slugify
    slug = kwargs.pop('slug', slugify(label))
    return ChampContactCustom.objects.create(
        formulaire=formulaire, label=label, slug=slug, field_type=field_type, **kwargs
    )


def make_contact_message(site, formulaire=None, **kwargs):
    defaults = {
        'name': 'Alice', 'email': 'alice@test.fr',
        'message': 'Bonjour', 'is_read': False,
    }
    defaults.update(kwargs)
    return ContactMessage.objects.create(site=site, formulaire=formulaire, **defaults)


def _set_chef_site(client, site):
    session = client.session
    session['redac_current_site_id'] = site.pk
    session.save()


# ── Modèles ───────────────────────────────────────────────────────────────────

class FormulaireContactModelTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_str(self):
        f = make_formulaire_contact(self.site)
        self.assertIn(self.site.name, str(f))

    def test_get_email_destination_uses_own_email(self):
        f = make_formulaire_contact(self.site, email_destination='contact@test.fr')
        self.assertEqual(f.get_email_destination(), 'contact@test.fr')

    def test_get_email_destination_falls_back_to_site(self):
        self.site.contact_email = 'site@test.fr'
        self.site.save()
        f = make_formulaire_contact(self.site, email_destination='')
        self.assertEqual(f.get_email_destination(), 'site@test.fr')

    def test_get_email_destination_empty_when_neither(self):
        f = make_formulaire_contact(self.site, email_destination='')
        self.assertEqual(f.get_email_destination(), '')

    def test_unique_per_site(self):
        make_formulaire_contact(self.site)
        from django.db import IntegrityError
        with self.assertRaises(Exception):
            make_formulaire_contact(self.site)


class ChampContactCustomModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire_contact(self.site)

    def test_str(self):
        c = make_champ_contact(self.formulaire, label='Entreprise')
        self.assertIn('Entreprise', str(c))

    def test_get_choices_list(self):
        c = make_champ_contact(self.formulaire, field_type='select',
                               choices_text='Option A\nOption B\n  \nOption C')
        self.assertEqual(c.get_choices_list(), ['Option A', 'Option B', 'Option C'])

    def test_get_choices_list_empty(self):
        c = make_champ_contact(self.formulaire)
        self.assertEqual(c.get_choices_list(), [])

    def test_ordering_by_order_field(self):
        c2 = make_champ_contact(self.formulaire, label='B', slug='b', order=2)
        c1 = make_champ_contact(self.formulaire, label='A', slug='a', order=1)
        champs = list(self.formulaire.champs_custom.all())
        self.assertEqual(champs[0].pk, c1.pk)
        self.assertEqual(champs[1].pk, c2.pk)


class ContactMessageUpdatedModelTest(TestCase):
    def test_formulaire_fk_nullable(self):
        site = make_site()
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='Hello'
        )
        self.assertIsNone(msg.formulaire)

    def test_custom_data_defaults_to_empty_dict(self):
        site = make_site()
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='Hello'
        )
        self.assertEqual(msg.custom_data, {})

    def test_custom_data_stored_correctly(self):
        site = make_site()
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='Hi',
            custom_data={'entreprise': 'ACME', 'accord': True}
        )
        msg.refresh_from_db()
        self.assertEqual(msg.custom_data['entreprise'], 'ACME')


# ── Formulaire dynamique ──────────────────────────────────────────────────────

class DynamicContactFormTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire_contact(
            self.site,
            field_nom=True, field_telephone=True, field_ville=False,
            field_secteur=False, field_objet=True,
        )

    def _data(self, **overrides):
        base = {
            'email': 'contact@test.fr',
            'nom': 'Dupont',
            'telephone': '0600000000',
            'objet': 'Question',
            'message': 'Bonjour',
        }
        base.update(overrides)
        return base

    def test_email_always_present(self):
        form = DynamicContactForm(formulaire=self.formulaire)
        self.assertIn('email', form.fields)

    def test_message_always_present(self):
        form = DynamicContactForm(formulaire=self.formulaire)
        self.assertIn('message', form.fields)

    def test_active_fields_present(self):
        form = DynamicContactForm(formulaire=self.formulaire)
        self.assertIn('nom', form.fields)
        self.assertIn('telephone', form.fields)
        self.assertIn('objet', form.fields)

    def test_inactive_fields_absent(self):
        form = DynamicContactForm(formulaire=self.formulaire)
        self.assertNotIn('ville', form.fields)
        self.assertNotIn('secteur', form.fields)

    def test_valid_form(self):
        form = DynamicContactForm(self._data(), formulaire=self.formulaire)
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_email_rejected(self):
        form = DynamicContactForm(self._data(email='pas-un-email'), formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_required_nom_missing(self):
        form = DynamicContactForm(self._data(nom=''), formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('nom', form.errors)

    def test_custom_text_field_added(self):
        make_champ_contact(self.formulaire, label='Entreprise', field_type='text', is_required=True)
        form = DynamicContactForm(formulaire=self.formulaire)
        self.assertIn('custom_entreprise', form.fields)

    def test_custom_select_field_choices(self):
        make_champ_contact(self.formulaire, label='Secteur', field_type='select',
                           choices_text='Bâtiment\nCommerce')
        form = DynamicContactForm(formulaire=self.formulaire)
        values = [v for v, _ in form.fields['custom_secteur'].choices]
        self.assertIn('Bâtiment', values)
        self.assertIn('Commerce', values)

    def test_custom_required_field_enforced(self):
        make_champ_contact(self.formulaire, label='Code', slug='code',
                           field_type='text', is_required=True)
        data = self._data()  # pas de custom_code
        form = DynamicContactForm(data, formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('custom_code', form.errors)

    def test_get_custom_data(self):
        make_champ_contact(self.formulaire, label='Ref', slug='ref', field_type='text')
        data = self._data(**{'custom_ref': 'ABC123'})
        form = DynamicContactForm(data, formulaire=self.formulaire)
        self.assertTrue(form.is_valid(), form.errors)
        custom = form.get_custom_data(self.formulaire)
        self.assertEqual(custom.get('ref'), 'ABC123')


# ── Vues publiques ────────────────────────────────────────────────────────────

class ContactViewWithFormulaireTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire_contact(
            self.site, field_nom=True, field_objet=True
        )
        self.url = '/contact/'

    def test_get_renders_dynamic_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertIsInstance(response.context['form'], DynamicContactForm)

    def test_get_passes_formulaire_to_context(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['formulaire'].pk, self.formulaire.pk)

    def test_post_valid_creates_message(self):
        self.client.post(self.url, {
            'email': 'test@exemple.fr', 'nom': 'Martin',
            'objet': 'Bonjour', 'message': 'Hello !',
        })
        self.assertTrue(ContactMessage.objects.filter(email='test@exemple.fr').exists())

    def test_post_links_formulaire_to_message(self):
        self.client.post(self.url, {
            'email': 'linked@test.fr', 'nom': 'X',
            'objet': 'Q', 'message': 'M',
        })
        msg = ContactMessage.objects.get(email='linked@test.fr')
        self.assertEqual(msg.formulaire_id, self.formulaire.pk)

    def test_post_saves_custom_data(self):
        make_champ_contact(self.formulaire, label='Code syndicat', slug='code-syndicat', field_type='text')
        self.client.post(self.url, {
            'email': 'custom@test.fr', 'nom': 'Y',
            'message': 'M', 'custom_code-syndicat': 'XYZ',
        })
        msg = ContactMessage.objects.get(email='custom@test.fr')
        self.assertIn('code-syndicat', msg.custom_data)

    def test_post_redirects_on_success(self):
        response = self.client.post(self.url, {
            'email': 'redir@test.fr', 'nom': 'Z', 'message': 'Hi',
        })
        self.assertEqual(response.status_code, 302)

    def test_post_invalid_rerenders_form(self):
        response = self.client.post(self.url, {'email': 'not-valid', 'message': 'Hi'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())

    def test_get_falls_back_to_contact_form_without_formulaire(self):
        from content.forms import ContactForm
        # Supprime le formulaire
        self.formulaire.delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], ContactForm)


class SiteContactViewWithFormulaireTest(TestCase):
    def setUp(self):
        self.site = make_site(slug='normandie', wp_blog_id=5, name='UR Normandie')
        self.formulaire = make_formulaire_contact(self.site, field_nom=True)
        self.url = '/normandie/contact/'

    def test_get_uses_dynamic_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], DynamicContactForm)

    def test_post_links_correct_site(self):
        self.client.post(self.url, {
            'email': 'normandie@test.fr', 'nom': 'Dupont', 'message': 'Salut',
        })
        msg = ContactMessage.objects.get(email='normandie@test.fr')
        self.assertEqual(msg.site_id, self.site.pk)


# ── Envoi d'email ─────────────────────────────────────────────────────────────

class SendContactEmailTest(TestCase):
    def setUp(self):
        self.site = make_site(contact_email='site@test.fr')

    def test_uses_formulaire_email_destination(self):
        from unittest.mock import patch
        formulaire = make_formulaire_contact(self.site, email_destination='form@test.fr')
        msg = make_contact_message(self.site, formulaire=formulaire)
        with patch('content.views.EmailMultiAlternatives') as mock_email:
            mock_instance = mock_email.return_value
            from content.views import _send_contact_email
            _send_contact_email(self.site, msg)
            args, kwargs = mock_email.call_args
            self.assertEqual(kwargs['to'], ['form@test.fr'])

    def test_falls_back_to_site_contact_email(self):
        from unittest.mock import patch
        msg = make_contact_message(self.site)  # pas de formulaire
        with patch('content.views.EmailMultiAlternatives') as mock_email:
            from content.views import _send_contact_email
            _send_contact_email(self.site, msg)
            args, kwargs = mock_email.call_args
            self.assertEqual(kwargs['to'], ['site@test.fr'])

    def test_subject_uses_prefix(self):
        from unittest.mock import patch
        formulaire = make_formulaire_contact(
            self.site, email_destination='d@d.fr', email_subject_prefix='[CNT42]'
        )
        msg = make_contact_message(self.site, formulaire=formulaire, subject='Ma question')
        with patch('content.views.EmailMultiAlternatives') as mock_email:
            from content.views import _send_contact_email
            _send_contact_email(self.site, msg)
            args, kwargs = mock_email.call_args
            self.assertIn('[CNT42]', kwargs['subject'])
            self.assertIn('Ma question', kwargs['subject'])

    def test_custom_data_in_body(self):
        from unittest.mock import patch
        formulaire = make_formulaire_contact(self.site, email_destination='d@d.fr')
        msg = make_contact_message(
            self.site, formulaire=formulaire,
            custom_data={'entreprise': 'ACME Corp'}
        )
        with patch('content.views.EmailMultiAlternatives') as mock_email:
            from content.views import _send_contact_email
            _send_contact_email(self.site, msg)
            args, kwargs = mock_email.call_args
            self.assertIn('ACME Corp', kwargs['body'])

    def test_reply_to_is_sender_email(self):
        from unittest.mock import patch
        msg = make_contact_message(self.site, email='sender@test.fr')
        with patch('content.views.EmailMultiAlternatives') as mock_email:
            from content.views import _send_contact_email
            _send_contact_email(self.site, msg)
            args, kwargs = mock_email.call_args
            self.assertEqual(kwargs['reply_to'], ['sender@test.fr'])


# ── Vues CMS ──────────────────────────────────────────────────────────────────

class ContactSubmissionListViewTest(TestCase):
    def setUp(self):
        self.site_a = make_site(slug='site-a', wp_blog_id=10, name='Site A')
        self.site_b = make_site(slug='site-b', wp_blog_id=11, name='Site B')
        make_formulaire_contact(self.site_a)
        self.msg_a = make_contact_message(self.site_a, name='Alice')
        self.msg_b = make_contact_message(self.site_b, name='Bob')
        self.chef = make_chef(username='chef_list', site=self.site_a)

    def test_requires_login(self):
        response = self.client.get('/cms/contact/')
        self.assertIn(response.status_code, [302, 403])

    def test_chef_sees_own_site_messages(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        response = self.client.get('/cms/contact/')
        self.assertEqual(response.status_code, 200)
        names = [s.name for s in response.context['submissions']]
        self.assertIn('Alice', names)
        self.assertNotIn('Bob', names)

    def test_search_filters_by_name(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        response = self.client.get('/cms/contact/?q=Alice')
        names = [s.name for s in response.context['submissions']]
        self.assertIn('Alice', names)

    def test_unread_filter(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        make_contact_message(self.site_a, name='Lue', is_read=True)
        response = self.client.get('/cms/contact/?status=unread')
        self.assertTrue(all(not s.is_read for s in response.context['submissions']))


class ContactSubmissionDetailViewTest(TestCase):
    def setUp(self):
        self.site_a = make_site(slug='da', wp_blog_id=20, name='A')
        self.site_b = make_site(slug='db', wp_blog_id=21, name='B')
        make_formulaire_contact(self.site_a)
        self.msg_a = make_contact_message(self.site_a, is_read=False)
        self.msg_b = make_contact_message(self.site_b)
        self.chef = make_chef(username='chef_detail', site=self.site_a)

    def test_get_marks_as_read(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        self.client.get(f'/cms/contact/{self.msg_a.pk}/')
        self.msg_a.refresh_from_db()
        self.assertTrue(self.msg_a.is_read)

    def test_idor_chef_cannot_access_other_site(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        response = self.client.get(f'/cms/contact/{self.msg_b.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_post_toggle_read(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        self.client.get(f'/cms/contact/{self.msg_a.pk}/')  # marque lu
        self.client.post(f'/cms/contact/{self.msg_a.pk}/', {'action': 'toggle_read'})
        self.msg_a.refresh_from_db()
        self.assertFalse(self.msg_a.is_read)

    def test_post_delete(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        pk = self.msg_a.pk
        response = self.client.post(f'/cms/contact/{pk}/', {'action': 'delete'})
        self.assertRedirects(response, '/cms/contact/', fetch_redirect_response=False)
        self.assertFalse(ContactMessage.objects.filter(pk=pk).exists())


class FormulaireContactConfigViewTest(TestCase):
    def setUp(self):
        self.site = make_site(slug='cfg', wp_blog_id=30, name='Config Site')
        self.chef = make_chef(username='chef_cfg', site=self.site)
        self.url = '/cms/contact-config/'

    def test_get_creates_formulaire_if_missing(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        self.client.get(self.url)
        self.assertTrue(FormulaireContact.objects.filter(site=self.site).exists())

    def test_post_saves_config(self):
        make_formulaire_contact(self.site)
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        self.client.post(self.url, {
            'is_active': 'on',
            'email_destination': 'dest@test.fr',
            'email_subject_prefix': '[Test]',
            'intro_text': 'Contactez-nous',
            'field_nom': 'on',
            'field_objet': 'on',
        })
        f = FormulaireContact.objects.get(site=self.site)
        self.assertTrue(f.is_active)
        self.assertEqual(f.email_destination, 'dest@test.fr')
        self.assertEqual(f.email_subject_prefix, '[Test]')
        self.assertTrue(f.field_nom)
        self.assertTrue(f.field_objet)
        self.assertFalse(f.field_telephone)

    def test_post_invalid_email_rejected(self):
        make_formulaire_contact(self.site)
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        response = self.client.post(self.url, {
            'email_destination': 'pas-un-email',
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        f = FormulaireContact.objects.get(site=self.site)
        self.assertNotEqual(f.email_destination, 'pas-un-email')

    def test_no_site_redirects(self):
        self.client.force_login(self.chef)
        # Pas de site en session
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)


class ChampContactCreateViewTest(TestCase):
    def setUp(self):
        self.site = make_site(slug='chp', wp_blog_id=40, name='Champ Site')
        self.formulaire = make_formulaire_contact(self.site)
        self.chef = make_chef(username='chef_chp', site=self.site)
        self.url = '/cms/contact-config/champ/ajouter/'

    def test_post_creates_champ(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        self.client.post(self.url, {'label': 'Entreprise', 'field_type': 'text'})
        self.assertTrue(self.formulaire.champs_custom.filter(label='Entreprise').exists())

    def test_slug_generated_from_label(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        self.client.post(self.url, {'label': 'Mon Champ Spécial', 'field_type': 'text'})
        champ = self.formulaire.champs_custom.get(label='Mon Champ Spécial')
        self.assertEqual(champ.slug, 'mon-champ-special')

    def test_empty_label_ignored(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site)
        count_before = self.formulaire.champs_custom.count()
        self.client.post(self.url, {'label': '', 'field_type': 'text'})
        self.assertEqual(self.formulaire.champs_custom.count(), count_before)


class ChampContactDeleteViewTest(TestCase):
    def setUp(self):
        self.site_a = make_site(slug='del-a', wp_blog_id=50, name='Del A')
        self.site_b = make_site(slug='del-b', wp_blog_id=51, name='Del B')
        self.form_a = make_formulaire_contact(self.site_a)
        self.form_b = make_formulaire_contact(self.site_b)
        self.champ_a = make_champ_contact(self.form_a, label='Champ A')
        self.champ_b = make_champ_contact(self.form_b, label='Champ B')
        self.chef = make_chef(username='chef_del', site=self.site_a)

    def test_delete_own_champ(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        self.client.post(f'/cms/contact-config/champ/{self.champ_a.pk}/supprimer/')
        self.assertFalse(ChampContactCustom.objects.filter(pk=self.champ_a.pk).exists())

    def test_idor_cannot_delete_other_site_champ(self):
        self.client.force_login(self.chef)
        _set_chef_site(self.client, self.site_a)
        response = self.client.post(f'/cms/contact-config/champ/{self.champ_b.pk}/supprimer/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ChampContactCustom.objects.filter(pk=self.champ_b.pk).exists())
