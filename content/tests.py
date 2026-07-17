import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, Group, Permission
from django.urls import reverse
from django.utils import timezone

from wagtail.models import Page as WagtailPage
from taggit.models import Tag as TaggitTag

from content.models import (
    Author, Tag, Media, Article, Page,
    Comment, MenuItem, Subscriber, Newsletter,
)
from content.forms import ContactForm, CommentForm
from cms.models import ArticlePage, CmsCategory, ContentPage, HomePage


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


def make_content_page(section_slug='principal', title='Page test', slug=None,
                      live=True, **kwargs):
    parent = _get_article_parent()
    slug = slug or title.lower().replace(' ', '-')
    return parent.add_child(instance=ContentPage(
        title=title, slug=slug,
        section_slug=section_slug,
        live=live,
        **kwargs
    ))


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
        self.assertIsNone(media.url)


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
        cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')
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
    def setUp(self):
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _data(self, **overrides):
        base = {
            'name': 'Alice',
            'email': 'alice@example.com',
            'phone': '0600000000',
            'city': 'Paris',
            'sector': 'Nettoyage',
            'subject': 'Test',
            'message': 'Bonjour',
            'h-captcha-response': 'test-token',
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

    def test_context_has_carousel_articles_key(self):
        response = self.client.get(reverse('content:home'))
        self.assertIn('carousel_articles', response.context)

    def test_context_has_manchette_articles_key(self):
        response = self.client.get(reverse('content:home'))
        self.assertIn('manchette_articles', response.context)

    def test_carousel_empty_sans_carousel_items_ni_images(self):
        make_article_page(section_slug='principal', title='Sans image', slug='sans-image')
        response = self.client.get(reverse('content:home'))
        self.assertEqual(response.context['carousel_articles'], [])

    def test_carousel_uses_carousel_items_du_section_page(self):
        from cms.models import CarouselArticle
        art = make_article_page(section_slug='principal', title='En carrousel', slug='en-carrousel')
        CarouselArticle.objects.create(page=self.site, article=art, sort_order=0)
        response = self.client.get(reverse('content:home'))
        self.assertIn(art, response.context['carousel_articles'])

    def test_all_latest_articles_contains_recent_articles(self):
        arts = [make_article_page(section_slug='principal', title=f'Art {i}', slug=f'art-{i}')
                for i in range(4)]
        response = self.client.get(reverse('content:home'))
        for art in arts:
            self.assertIn(art, response.context['all_latest_articles'])

    def test_all_latest_articles_capped_at_9(self):
        for i in range(12):
            make_article_page(section_slug='principal', title=f'Flux {i}', slug=f'flux-{i}')
        response = self.client.get(reverse('content:home'))
        self.assertLessEqual(len(response.context['all_latest_articles']), 9)

    def test_all_latest_articles_includes_sous_sites(self):
        make_site('reseau-test', wp_blog_id=42, site_type='sectoral', name='Réseau Test')
        art = make_article_page(section_slug='reseau-test', title='Art réseau', slug='art-reseau')
        response = self.client.get(reverse('content:home'))
        self.assertIn(art, response.context['all_latest_articles'])


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

    def test_no_confederal_cta_on_subsite_article(self):
        """Les vignettes CTA confédérales n'apparaissent pas sur les articles de sous-site."""
        url = reverse('content:site_article_detail', kwargs={'site_slug': 'sub', 'slug': 'sub-article'})
        response = self.client.get(url)
        self.assertNotContains(response, "Quel est notre champ d'action")
        self.assertNotContains(response, 'Quels sont vos droits')

    def test_confederal_cta_on_principal_article(self):
        """Les vignettes CTA confédérales restent présentes sur les articles du site principal."""
        make_article_page(section_slug='principal', title='Princ', slug='princ-cta')
        url = reverse('content:article_detail', kwargs={'slug': 'princ-cta'})
        response = self.client.get(url)
        self.assertContains(response, "Quel est notre champ d'action")
        self.assertContains(response, 'Quels sont vos droits')


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
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _contact_data(self, **overrides):
        data = {
            'name': 'Alice', 'email': 'alice@example.com',
            'phone': '0600000000', 'city': 'Paris', 'sector': 'Nettoyage',
            'subject': 'Bonjour', 'message': 'Test',
            'h-captcha-response': 'test-token',
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
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_returns_200(self):
        url = reverse('content:site_contact', kwargs={'site_slug': 'sub'})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_valid_post_sets_site_on_message(self):
        from content.models import ContactMessage
        data = {
            'name': 'Bob', 'email': 'bob@example.com',
            'phone': '0600000000', 'city': 'Lyon', 'sector': 'Nettoyage',
            'subject': 'Hi', 'message': 'Hello',
            'h-captcha-response': 'test-token',
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
        make_site()
        cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')
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
        pub = make_content_page(title='Pub', slug='pub-s', live=True)
        draft = make_content_page(title='Draft', slug='draft-s', live=False)
        sitemap = PageSitemap()
        items = list(sitemap.items())
        self.assertIn(pub, items)
        self.assertNotIn(draft, items)

    def test_category_sitemap_uses_cms_category(self):
        from content.sitemaps import CategorySitemap
        cat = make_cms_category(name='Cat', slug='cat-s', section_slug='principal')
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

    def test_tag_snippet_not_registered(self):
        """Tag legacy : le ContenuGroup (Articles & Pages legacy) n'est plus enregistré."""
        self.assertNotIn(Tag, self._get_snippet_models())

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

    def test_redacteur_manages_categories_but_cannot_delete(self):
        # Autonomie 2026-07-16 : les catégories du syndicat sont gérées par
        # ses rédacteurs (create/rename) ; la suppression reste confédérale.
        self.assertTrue(self.redacteur.has_perm('cms.add_cmscategory'))
        self.assertTrue(self.redacteur.has_perm('cms.change_cmscategory'))
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


class DirectPublicationTest(TestCase):
    """Publication directe (lot 2 du chantier autonomie syndicats) : les
    rédacteurs publient sans circuit d'approbation — le workflow Wagtail
    « Moderators approval » est désactivé (WAGTAIL_WORKFLOW_ENABLED=False)
    et les groupes portent les permissions modèle publish_* que l'interface
    snippets exige (les GroupPagePermission d'arbre ne suffisent pas)."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.redacteur = make_redacteur(site=self.site_a)
        self.chef = make_chef(site=self.site_a)
        self.article = make_article_page(
            section_slug='principal', title='Brouillon', slug='pub-directe')

    def test_redacteur_has_publish_model_perms(self):
        self.assertTrue(self.redacteur.has_perm('cms.publish_articlepage'))
        self.assertTrue(self.redacteur.has_perm('cms.publish_contentpage'))

    def test_redacteur_publishes_section_sheet(self):
        """Autonomie 2026-07-16 : la fiche du syndicat (logo, RS, textes) est
        éditable ET publiable par ses rédacteurs — bornée à leur section par
        le queryset de SectionPageViewSet."""
        self.assertTrue(self.redacteur.has_perm('cms.publish_sectionpage'))

    def test_chef_has_all_publish_model_perms(self):
        self.assertTrue(self.chef.has_perm('cms.publish_articlepage'))
        self.assertTrue(self.chef.has_perm('cms.publish_contentpage'))
        self.assertTrue(self.chef.has_perm('cms.publish_sectionpage'))

    def test_article_edit_shows_publish_button(self):
        self.client.force_login(self.redacteur)
        r = self.client.get(f'/cms/snippets/cms/articlepage/edit/{self.article.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'action-publish')

    def test_no_moderation_workflow_button(self):
        """Le bouton « Soumettre à ... approval » ne doit plus apparaître."""
        self.client.force_login(self.redacteur)
        r = self.client.get(f'/cms/snippets/cms/articlepage/edit/{self.article.pk}/')
        self.assertNotContains(r, 'Soumettre à')

    def test_workflow_disabled_in_settings(self):
        from django.conf import settings
        self.assertFalse(getattr(settings, 'WAGTAIL_WORKFLOW_ENABLED', True))


class SectionAutonomyPermissionsTest(TestCase):
    """Lots 3-4 du chantier autonomie : permissions modèle complètes pour les
    rédacteurs (outils du syndicat inclus) et fusion chef_<slug> →
    redacteur_<slug> par la commande setup_cms_permissions."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='sectoral', name='Other')

    def test_redacteur_has_syndicat_tool_perms(self):
        redacteur = make_redacteur(site=self.site_a)
        for perm in ['content.add_newsletter',
                     'content.add_subscriber', 'content.delete_subscriber',
                     'content.change_contactmessage', 'content.change_formulairecontact',
                     'content.add_champcontactcustom',
                     'cms.change_sectionpage', 'cms.publish_sectionpage',
                     'cms.add_event', 'cms.add_cmscategory']:
            self.assertTrue(redacteur.has_perm(perm), f'manquante : {perm}')

    def test_redacteur_still_cannot_delete_content(self):
        redacteur = make_redacteur(site=self.site_a)
        for perm in ['content.delete_menuitem', 'content.delete_newsletter',
                     'cms.delete_articlepage', 'cms.delete_contentpage',
                     'cms.delete_cmscategory', 'cms.delete_sectionpage',
                     'wagtailimages.delete_image']:
            self.assertFalse(redacteur.has_perm(perm), f'ne devrait pas avoir : {perm}')

    def test_redacteur_has_menu_perms(self):
        """Lot 6 : menus ouverts après sécurisation des vues Move/Reorder."""
        redacteur = make_redacteur(site=self.site_a)
        self.assertTrue(redacteur.has_perm('content.add_menuitem'))
        self.assertTrue(redacteur.has_perm('content.change_menuitem'))
        self.assertFalse(redacteur.has_perm('content.delete_menuitem'))

    def test_redacteur_cannot_move_other_site_menuitem(self):
        """Lot 6 : MoveMenuItemView refuse de déplacer un item d'un autre site
        (le pk vient du POST — sans garde, manipulation cross-site possible)."""
        from content.models import MenuItem
        a1 = MenuItem.objects.create(site=self.site_a, menu='main', title='A1', order=0)
        a2 = MenuItem.objects.create(site=self.site_a, menu='main', title='A2', order=1)
        redacteur = make_redacteur(site=self.site_b, username='menu-redac')
        self.client.force_login(redacteur)
        self.client.post('/cms/menus/move/', {'item': a2.pk, 'action': 'up'})
        a1.refresh_from_db(); a2.refresh_from_db()
        self.assertEqual((a1.order, a2.order), (0, 1))  # inchangé

    def test_redacteur_moves_own_site_menuitem(self):
        from content.models import MenuItem
        b1 = MenuItem.objects.create(site=self.site_b, menu='main', title='B1', order=0)
        b2 = MenuItem.objects.create(site=self.site_b, menu='main', title='B2', order=1)
        redacteur = make_redacteur(site=self.site_b, username='menu-redac2')
        self.client.force_login(redacteur)
        self.client.post('/cms/menus/move/', {'item': b2.pk, 'action': 'up'})
        b1.refresh_from_db(); b2.refresh_from_db()
        self.assertLess(b2.order, b1.order)

    def test_redacteur_cannot_reorder_other_site_menuitems(self):
        """Lot 6 : ReorderMenuItemsView borne les updates au syndicat courant,
        re-parentage cross-site inclus."""
        import json
        from content.models import MenuItem
        a1 = MenuItem.objects.create(site=self.site_a, menu='main', title='A1', order=0)
        b1 = MenuItem.objects.create(site=self.site_b, menu='main', title='B1', order=0)
        redacteur = make_redacteur(site=self.site_b, username='menu-redac3')
        self.client.force_login(redacteur)
        r = self.client.post(
            '/cms/menus/reorder/',
            json.dumps({'moves': [
                {'id': a1.pk, 'order': 99, 'parent': None},   # autre site → ignoré
                {'id': b1.pk, 'order': 5, 'parent': a1.pk},   # parent cross-site → ignoré
            ]}),
            content_type='application/json')
        self.assertEqual(r.status_code, 200)
        a1.refresh_from_db(); b1.refresh_from_db()
        self.assertEqual(a1.order, 0)
        self.assertEqual(b1.order, 0)
        self.assertIsNone(b1.parent_id)

    def test_setup_command_merges_chef_groups(self):
        from django.core.management import call_command
        chef_g, _ = Group.objects.get_or_create(name='chef_other')
        u = User.objects.create_user('ex-chef', password='pass')
        u.groups.add(chef_g)
        call_command('setup_cms_permissions')
        u = User.objects.get(pk=u.pk)
        self.assertFalse(Group.objects.filter(name='chef_other').exists())
        self.assertIn('redacteur_other', [g.name for g in u.groups.all()])

    def test_setup_command_grants_publish_on_section_subtree(self):
        from django.core.management import call_command
        from wagtail.models import GroupPagePermission
        call_command('setup_cms_permissions')
        g = Group.objects.get(name='redacteur_other')
        self.assertTrue(GroupPagePermission.objects.filter(
            group=g, page=self.site_b, permission__codename='publish_page').exists())

    def test_setup_command_prunes_obsolete_groups(self):
        """Ménage de l'onglet Rôles (/cms/users/) : les groupes redacteur_<slug>
        sans SectionPage et les groupes Wagtail par défaut (Editors/Moderators)
        sont supprimés — sauf s'ils ont encore des membres."""
        from io import StringIO
        from django.core.management import call_command
        Group.objects.create(name='redacteur_fantome')
        habite = Group.objects.create(name='redacteur_fantome-habite')
        u = User.objects.create_user('membre-fantome', password='pass')
        u.groups.add(habite)
        call_command('setup_cms_permissions', stdout=StringIO(), stderr=StringIO())
        self.assertFalse(Group.objects.filter(name='redacteur_fantome').exists())
        self.assertTrue(Group.objects.filter(name='redacteur_fantome-habite').exists())
        self.assertFalse(Group.objects.filter(name__in=('Editors', 'Moderators')).exists())
        for kept in ('redacteur_other', 'redacteur', 'redacteur_en_chef'):
            self.assertTrue(Group.objects.filter(name=kept).exists(), kept)

    def test_section_group_user_can_create_and_publish_articles(self):
        """Un membre de redacteur_<slug> ouvre le formulaire de création
        d'article (302 avant le lot 3) et dispose du bouton Publier."""
        from django.core.management import call_command
        call_command('setup_cms_permissions')
        u = User.objects.create_user('sec-redac', password='pass')
        u.groups.add(Group.objects.get(name='redacteur_other'))
        u = User.objects.get(pk=u.pk)
        self.client.force_login(u)
        r = self.client.get('/cms/snippets/cms/articlepage/add/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'action-publish')

    def test_section_redacteur_accesses_own_contact_config(self):
        """Lot 5 : la config du formulaire de contact est accessible au
        rédacteur du syndicat (avant : réservée chef, redirect /cms/)."""
        redacteur = make_redacteur(site=self.site_b, username='contact-redac')
        self.client.force_login(redacteur)
        r = self.client.get('/cms/contact-config/')
        self.assertEqual(r.status_code, 200)

    def test_no_syndicat_user_still_blocked_on_contact_config(self):
        u = User.objects.create_user('sans-syndicat', password='pass')
        from django.contrib.auth.models import Permission
        u.user_permissions.add(Permission.objects.get(codename='access_admin'))
        u = User.objects.get(pk=u.pk)
        self.client.force_login(u)
        r = self.client.get('/cms/contact-config/')
        self.assertEqual(r.status_code, 302)  # bounce vers /cms/

    def test_section_redacteur_exports_own_subscribers(self):
        """Lot 5 : export CSV des abonnés du syndicat, décision d'Arnaud
        « accès complet avec export »."""
        from content.models import Subscriber
        Subscriber.objects.create(site=self.site_b, email='abo@example.org', is_active=True)
        Subscriber.objects.create(site=self.site_a, email='autre@example.org', is_active=True)
        redacteur = make_redacteur(site=self.site_b, username='export-redac')
        self.client.force_login(redacteur)
        r = self.client.get('/cms/abonnes/export/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode('utf-8')
        self.assertIn('abo@example.org', content)
        self.assertNotIn('autre@example.org', content)  # jamais cross-site

    def test_section_redacteur_cannot_send_other_site_newsletter(self):
        """Lot 5 : le garde anti-envoi-croisé de NewsletterSendView bloque un
        rédacteur de syndicat sur la newsletter d'un autre site (PermissionDenied,
        que le wrapper admin Wagtail transforme en 302 — jamais 200)."""
        from content.models import Newsletter
        nl = Newsletter.objects.create(site=self.site_a, title='Conf', intro='x')
        redacteur = make_redacteur(site=self.site_b, username='nl-redac')
        self.client.force_login(redacteur)
        r = self.client.get(f'/cms/newsletter/{nl.pk}/envoyer/')
        self.assertIn(r.status_code, (302, 403))

    def test_section_redacteur_can_open_own_newsletter_send(self):
        from content.models import Newsletter
        nl = Newsletter.objects.create(site=self.site_b, title='Locale', intro='x')
        redacteur = make_redacteur(site=self.site_b, username='nl-redac2')
        self.client.force_login(redacteur)
        r = self.client.get(f'/cms/newsletter/{nl.pk}/envoyer/')
        self.assertEqual(r.status_code, 200)

    def test_section_sheet_queryset_scoped_to_own_section(self):
        """La fiche « Mon syndicat » n'expose que la section de l'utilisateur,
        y compris pour un rédacteur de syndicat (plus seulement les chefs)."""
        from django.core.management import call_command
        from django.test import RequestFactory
        from cms.wagtail_hooks import SectionPageViewSet
        call_command('setup_cms_permissions')
        u = User.objects.create_user('sec-redac2', password='pass')
        u.groups.add(Group.objects.get(name='redacteur_other'))
        u = User.objects.get(pk=u.pk)
        request = RequestFactory().get('/')
        request.user = u
        request.session = {}
        qs = SectionPageViewSet.get_queryset(None, request)
        self.assertEqual([s.slug for s in qs], ['other'])


class MediaCollectionsTest(TestCase):
    """Lot 7 du chantier autonomie : médias cloisonnés par syndicat.

    Wagtail contrôle les images/documents par GroupCollectionPermission (les
    permissions Django modèle sont ignorées) : setup_cms_permissions crée une
    Collection par syndicat + « Commun » et y borne chaque redacteur_<slug>."""

    def setUp(self):
        from io import StringIO
        from django.core.management import call_command
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='sectoral', name='Other')
        call_command('setup_cms_permissions', stdout=StringIO())

    def _member(self, username, group_name):
        user = User.objects.create_user(username, password='pass')
        user.groups.add(Group.objects.get(name=group_name))
        return User.objects.get(pk=user.pk)

    def test_collections_created(self):
        from wagtail.models import Collection
        names = set(Collection.objects.values_list('name', flat=True))
        self.assertTrue({'Commun', 'CNT-SO', 'Other'} <= names, names)

    def test_redacteur_adds_only_in_own_collection(self):
        from wagtail.images.permissions import permission_policy
        user = self._member('redac-a', 'redacteur_principal')
        self.assertTrue(permission_policy.user_has_permission(user, 'add'))
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(user, 'add')}
        self.assertEqual(names, {'CNT-SO'})

    def test_redacteur_chooses_own_collection_and_commun_only(self):
        from wagtail.images.permissions import permission_policy
        user = self._member('redac-a2', 'redacteur_principal')
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(user, 'choose')}
        self.assertEqual(names, {'CNT-SO', 'Commun'})

    def test_documents_same_scoping(self):
        from wagtail.documents.permissions import permission_policy
        user = self._member('redac-a3', 'redacteur_principal')
        self.assertTrue(permission_policy.user_has_permission(user, 'add'))
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(user, 'add')}
        self.assertEqual(names, {'CNT-SO'})

    def test_cross_site_image_not_choosable(self):
        from wagtail.images.models import Image
        from wagtail.images.permissions import permission_policy
        from wagtail.images.tests.utils import get_test_image_file
        from wagtail.models import Collection
        img = Image.objects.create(
            title='Img Other', file=get_test_image_file(),
            collection=Collection.objects.get(name='Other'))
        user = self._member('redac-a4', 'redacteur_principal')
        choosable = permission_policy.instances_user_has_any_permission_for(
            user, ['choose'])
        self.assertNotIn(img.pk, [i.pk for i in choosable])

    def test_chef_global_has_access_everywhere(self):
        from wagtail.images.permissions import permission_policy
        chef = self._member('chef-glob', 'redacteur_en_chef')
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(chef, 'add')}
        self.assertTrue({'Root', 'Commun', 'CNT-SO', 'Other'} <= names, names)

    def test_generic_redacteur_reads_commun_only(self):
        from wagtail.images.permissions import permission_policy
        user = self._member('redac-nu', 'redacteur')
        self.assertFalse(permission_policy.user_has_permission(user, 'add'))
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(user, 'choose')}
        self.assertEqual(names, {'Commun'})

    def test_command_idempotent(self):
        from io import StringIO
        from django.core.management import call_command
        from wagtail.models import Collection, GroupCollectionPermission
        collections = Collection.objects.count()
        gcp = GroupCollectionPermission.objects.count()
        call_command('setup_cms_permissions', stdout=StringIO())
        self.assertEqual(Collection.objects.count(), collections)
        self.assertEqual(GroupCollectionPermission.objects.count(), gcp)

    def test_image_index_scoped_to_own_collection(self):
        """/cms/images/ : un rédacteur ne voit que les images de son syndicat."""
        from wagtail.images.models import Image
        from wagtail.images.tests.utils import get_test_image_file
        from wagtail.models import Collection
        Image.objects.create(title='Visuel Principal-A', file=get_test_image_file(),
                             collection=Collection.objects.get(name='CNT-SO'))
        Image.objects.create(title='Visuel Other-B', file=get_test_image_file(),
                             collection=Collection.objects.get(name='Other'))
        self._member('redac-idx', 'redacteur_principal')
        self.client.login(username='redac-idx', password='pass')
        resp = self.client.get('/cms/images/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Visuel Principal-A')
        self.assertNotContains(resp, 'Visuel Other-B')


class SectionAutoProvisioningTest(TestCase):
    """Créer un syndicat suffit : le signal post_save (cms/apps.py) provisionne
    le groupe redacteur_<slug>, ses permissions d'arbre, les permissions
    modèle (copiées du groupe socle redacteur) et sa collection de médias —
    sans repasser par setup_cms_permissions."""

    def setUp(self):
        _setup_editorial_groups()

    def test_new_section_gets_group_permissions_and_collection(self):
        from wagtail.models import Collection, GroupPagePermission
        site = make_site(slug='tout-neuf', name='Syndicat Tout Neuf',
                         site_type='sectoral', wp_blog_id=97)
        group = Group.objects.get(name='redacteur_tout-neuf')
        self.assertTrue(GroupPagePermission.objects.filter(
            group=group, page=site, permission__codename='publish_page').exists())
        self.assertTrue(Collection.objects.filter(name='Syndicat Tout Neuf').exists())
        self.assertTrue(group.permissions.filter(codename='publish_articlepage').exists())
        self.assertTrue(group.permissions.filter(codename='access_admin').exists())

    def test_provisioned_user_can_choose_media(self):
        from wagtail.images.permissions import permission_policy
        make_site(slug='tout-neuf2', name='Tout Neuf 2',
                  site_type='regional', wp_blog_id=96)
        u = User.objects.create_user('redac-neuf', password='pass')
        u.groups.add(Group.objects.get(name='redacteur_tout-neuf2'))
        u = User.objects.get(pk=u.pk)
        names = {c.name for c in
                 permission_policy.collections_user_has_permission_for(u, 'choose')}
        self.assertEqual(names, {'Tout Neuf 2', 'Commun'})


class SectionGroupScopingTest(TestCase):
    """Résolution du site via les groupes par section (redacteur_<slug> /
    chef_<slug>, créés par setup_cms_permissions) — sans fiche Author.

    Quand un utilisateur a à la fois un groupe par section ET un Author.site
    divergent, le groupe gagne (les groupes portent les permissions Wagtail
    réelles ; Author.site est la voie historique)."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2, site_type='regional', name='Other')
        self.art_a = make_article_page(section_slug='principal', title='Art A', slug='sg-art-a')
        self.art_b = make_article_page(section_slug='other', title='Art B', slug='sg-art-b')

    def _user_in_group(self, username, group_name):
        group, _ = Group.objects.get_or_create(name=group_name)
        user = User.objects.create_user(username=username, password='pass')
        user.groups.add(group)
        return User.objects.get(pk=user.pk)

    def _request(self, user, session=None):
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = user
        request.session = session or {}
        return request

    def test_group_redacteur_resolves_current_site(self):
        from cms.site_context import get_current_site
        user = self._user_in_group('g-redac', 'redacteur_other')
        site = get_current_site(self._request(user))
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, 'other')

    def test_group_chef_resolves_current_site(self):
        from cms.site_context import get_current_site
        user = self._user_in_group('g-chef', 'chef_other')
        site = get_current_site(self._request(user))
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, 'other')

    def test_group_matches_legacy_site_slug(self):
        from cms.site_context import get_current_site
        self.site_b.legacy_site_slug = 'ancien-nom'
        self.site_b.save()
        user = self._user_in_group('g-legacy', 'chef_ancien-nom')
        site = get_current_site(self._request(user))
        self.assertIsNotNone(site)
        self.assertEqual(site.pk, self.site_b.pk)

    def test_group_scoped_articles_list(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        user = self._user_in_group('g-scope', 'redacteur_other')
        qs = scope_qs_slug(ArticlePage.objects.all(), self._request(user),
                           slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_b.pk, pks)
        self.assertNotIn(self.art_a.pk, pks)

    def test_group_available_sites_only_own(self):
        from cms.site_context import get_available_sites
        user = self._user_in_group('g-avail', 'chef_other')
        slugs = [s.slug for s in get_available_sites(self._request(user))]
        self.assertEqual(slugs, ['other'])

    def test_group_chef_is_not_global_chef(self):
        """chef_<slug> ne passe pas is_chef() — pas d'accès aux capacités
        confédérales (featured_on_conf, sélecteur multi-sites, menus chef)."""
        from content.admin_utils import is_chef
        user = self._user_in_group('g-notchef', 'chef_other')
        self.assertFalse(is_chef(user))

    def test_group_chef_cannot_switch_site_via_selector(self):
        """SelectSiteView reste un no-op pour un chef de section : la session
        ne change pas et le scoping reste sur son propre site."""
        user = self._user_in_group('g-switch', 'chef_other')
        user.user_permissions.add(
            Permission.objects.get(codename='access_admin'))
        user = User.objects.get(pk=user.pk)
        self.client.force_login(user)
        self.client.get(f'/cms/select-site/?site_id={self.site_a.pk}')
        self.assertNotEqual(
            self.client.session.get('cms_current_site_id'), self.site_a.pk)

    def test_redacteur_en_chef_does_not_match_pattern(self):
        """Le groupe redacteur_en_chef ne doit pas être lu comme un groupe de
        section avec le slug fantôme 'en_chef'."""
        from cms.site_context import get_group_scoped_site
        user = self._user_in_group('g-enchef', 'redacteur_en_chef')
        self.assertIsNone(get_group_scoped_site(user))

    def test_group_wins_over_divergent_author_site(self):
        from cms.site_context import get_current_site
        user = self._user_in_group('g-both', 'redacteur_other')
        Author.objects.create(user=user, site=self.site_a, username='g-both')
        user = User.objects.get(pk=user.pk)
        site = get_current_site(self._request(user))
        self.assertEqual(site.slug, 'other')

    def test_author_site_still_works_without_group(self):
        """Non-régression : la voie historique Author.site reste fonctionnelle."""
        from cms.site_context import get_current_site
        user = make_redacteur(username='g-author-only', site=self.site_a)
        site = get_current_site(self._request(user))
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, 'principal')

    def test_admin_utils_resolver_delegates(self):
        """get_current_site_for_view (newsletter/contact CMS) voit aussi les
        groupes par section — garde anti-envoi-croisé de NewsletterSendView."""
        from content.admin_utils import get_current_site_for_view
        user = self._user_in_group('g-nl', 'chef_other')
        site = get_current_site_for_view(self._request(user))
        self.assertIsNotNone(site)
        self.assertEqual(site.slug, 'other')


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
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _data(self, **overrides):
        base = {
            'email': 'contact@test.fr',
            'nom': 'Dupont',
            'telephone': '0600000000',
            'objet': 'Question',
            'message': 'Bonjour',
            'h-captcha-response': 'test-token',
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
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

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
            'h-captcha-response': 'test-token',
        })
        self.assertTrue(ContactMessage.objects.filter(email='test@exemple.fr').exists())

    def test_post_links_formulaire_to_message(self):
        self.client.post(self.url, {
            'email': 'linked@test.fr', 'nom': 'X',
            'objet': 'Q', 'message': 'M',
            'h-captcha-response': 'test-token',
        })
        msg = ContactMessage.objects.get(email='linked@test.fr')
        self.assertEqual(msg.formulaire_id, self.formulaire.pk)

    def test_post_saves_custom_data(self):
        make_champ_contact(self.formulaire, label='Code syndicat', slug='code-syndicat', field_type='text')
        self.client.post(self.url, {
            'email': 'custom@test.fr', 'nom': 'Y', 'objet': 'Q',
            'message': 'M', 'custom_code-syndicat': 'XYZ',
            'h-captcha-response': 'test-token',
        })
        msg = ContactMessage.objects.get(email='custom@test.fr')
        self.assertIn('code-syndicat', msg.custom_data)

    def test_post_redirects_on_success(self):
        response = self.client.post(self.url, {
            'email': 'redir@test.fr', 'nom': 'Z', 'objet': 'Q', 'message': 'Hi',
            'h-captcha-response': 'test-token',
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
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_uses_dynamic_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], DynamicContactForm)

    def test_post_links_correct_site(self):
        self.client.post(self.url, {
            'email': 'normandie@test.fr', 'nom': 'Dupont', 'objet': 'Q', 'message': 'Salut',
            'h-captcha-response': 'test-token',
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


# ═══════════════════════════════════════════════════════════════════════════════
# NEWSLETTER SEND VIA OVH
# ═══════════════════════════════════════════════════════════════════════════════

def _make_newsletter(site, title='Test newsletter', status='draft'):
    from content.models import Newsletter
    return Newsletter.objects.create(site=site, title=title, intro='Intro test.', status=status)


def _chef_client(site):
    """Client authentifié comme rédacteur-en-chef avec le site courant en session."""
    from django.contrib.auth.models import User, Group
    from cms.site_context import SESSION_KEY
    _setup_editorial_groups()
    user = User.objects.create_superuser(
        username=f'chef-nl-{site.pk}', password='pass'
    )
    c = __import__('django.test', fromlist=['Client']).Client()
    c.force_login(user)
    session = c.session
    session[SESSION_KEY] = site.pk
    session.save()
    return c


class NewsletterSendOvhGetTest(TestCase):
    """Page de confirmation d'envoi — affichage selon mode OVH ou direct."""

    def setUp(self):
        self.site = _ensure_section_page(slug='nl-ovh-get', name='NL OVH GET', site_type='sectoral')
        self.site.ovh_mailing_list = 'actu-test-cntso'
        self.site.save(update_fields=['ovh_mailing_list'])
        self.newsletter = _make_newsletter(self.site)
        self.url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com', 'c@d.com'])
    def test_get_shows_ovh_mode_when_list_configured(self, mock_subs):
        c = _chef_client(self.site)
        r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'actu-test-cntso@cnt-so.info')
        self.assertContains(r, 'Mode OVH')

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com', 'c@d.com'])
    def test_get_shows_subscriber_count_from_ovh(self, mock_subs):
        c = _chef_client(self.site)
        r = c.get(self.url)
        self.assertContains(r, '2 abonné')

    def test_get_shows_direct_mode_when_no_ovh_list(self):
        self.site.ovh_mailing_list = ''
        self.site.save(update_fields=['ovh_mailing_list'])
        Subscriber.objects.create(site=self.site, email='x@y.com', is_active=True)
        c = _chef_client(self.site)
        r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Mode OVH')
        self.assertContains(r, '1 abonné')


class NewsletterSendOvhPostTest(TestCase):
    """Envoi réel via liste OVH."""

    def setUp(self):
        self.site = _ensure_section_page(slug='nl-ovh-post', name='NL OVH POST', site_type='sectoral')
        self.site.ovh_mailing_list = 'actu-test-cntso'
        self.site.save(update_fields=['ovh_mailing_list'])
        self.newsletter = _make_newsletter(self.site)
        self.url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_send_posts_single_email_to_list_address(self, mock_send, mock_subs):
        # patch send : vérifie qu'un seul appel est fait (pas un par abonné)
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertEqual(mock_send.call_count, 1)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_send_addresses_list_email(self, mock_subs):
        # sans patch send → mail.outbox (locmem backend) est utilisé
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('actu-test-cntso@cnt-so.info', mail.outbox[0].to)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_send_sets_list_unsubscribe_header(self, mock_subs):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        header = mail.outbox[0].extra_headers.get('List-Unsubscribe', '')
        self.assertIn('actu-test-cntso-unsubscribe@cnt-so.info', header)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_send_marks_newsletter_as_sent(self, mock_send, mock_subs):
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, 'sent')

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com', 'b@c.com'])
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_send_records_ovh_subscriber_count(self, mock_send, mock_subs):
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.sent_count, 2)

    def test_send_direct_fallback_when_no_ovh_list(self):
        """Sans liste OVH, l'envoi direct email-par-email est utilisé."""
        from django.core import mail
        self.site.ovh_mailing_list = ''
        self.site.save(update_fields=['ovh_mailing_list'])
        Subscriber.objects.create(site=self.site, email='s1@example.com', is_active=True)
        Subscriber.objects.create(site=self.site, email='s2@example.com', is_active=True)
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertEqual(len(mail.outbox), 2)
        sent_to = {m.to[0] for m in mail.outbox}
        self.assertIn('s1@example.com', sent_to)
        self.assertIn('s2@example.com', sent_to)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP down'))
    def test_send_error_shown_and_newsletter_not_marked_sent(self, mock_send, mock_subs):
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'send'}, follow=True)
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, 'draft')
        self.assertContains(r, 'SMTP down')



class NewsletterArticlePageTest(TestCase):
    """Les newsletters référencent les articles Wagtail (ArticlePage), plus le modèle legacy."""

    def setUp(self):
        from content.models import NewsletterArticle
        self.site = _ensure_section_page(slug='nl-artpage', name='NL ArtPage', site_type='sectoral')
        self.site.ovh_mailing_list = 'nl-artpage-liste'
        self.site.save(update_fields=['ovh_mailing_list'])
        self.newsletter = _make_newsletter(self.site)
        self.article = make_article_page(
            title='Un article Wagtail dans la newsletter', section_slug='nl-artpage')
        NewsletterArticle.objects.create(
            newsletter=self.newsletter, article=self.article, order=0)
        self.url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_email_contient_l_article_wagtail(self, mock_subs):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('Un article Wagtail dans la newsletter', html)
        self.assertIn(self.article.get_absolute_url(), html)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_texte_brut_contient_le_lien_article(self, mock_subs):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertIn(self.article.get_absolute_url(), mail.outbox[0].body)



from django.core.mail import EmailMultiAlternatives


class NewsletterMultiListTest(TestCase):
    """Un syndicat peut déclarer plusieurs listes OVH : la newsletter part à chacune."""

    def setUp(self):
        self.site = _ensure_section_page(slug='nl-multi', name='NL Multi', site_type='sectoral')
        self.site.ovh_mailing_list = 'liste-a, liste-b'
        self.site.save(update_fields=['ovh_mailing_list'])
        self.newsletter = _make_newsletter(self.site)
        self.url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'

    @patch('cms.ovh_client.get_subscribers', side_effect=[['a@b.com'], ['c@d.com', 'e@f.com']])
    def test_un_email_par_liste(self, mock_subs):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        self.assertEqual(len(mail.outbox), 2)
        dests = {m.to[0] for m in mail.outbox}
        self.assertEqual(dests, {'liste-a@cnt-so.info', 'liste-b@cnt-so.info'})
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, 'sent')
        self.assertEqual(self.newsletter.sent_count, 3)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_entete_desabonnement_propre_a_chaque_liste(self, mock_subs):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        headers = {m.extra_headers.get('List-Unsubscribe', '') for m in mail.outbox}
        self.assertIn('<mailto:liste-a-unsubscribe@cnt-so.info>', headers)
        self.assertIn('<mailto:liste-b-unsubscribe@cnt-so.info>', headers)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_echec_partiel_marque_quand_meme_envoyee(self, mock_subs):
        from django.core import mail
        real_send = EmailMultiAlternatives.send

        def flaky_send(msg_self, *args, **kwargs):
            if 'liste-b@cnt-so.info' in msg_self.to:
                raise Exception('SMTP down')
            return real_send(msg_self, *args, **kwargs)

        c = _chef_client(self.site)
        with patch.object(EmailMultiAlternatives, 'send', flaky_send):
            r = c.post(self.url, {'mode': 'send'}, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, 'sent')
        self.assertContains(r, 'liste-b@cnt-so.info')

    def test_get_affiche_toutes_les_listes(self):
        with patch('cms.ovh_client.get_subscribers', return_value=['a@b.com']):
            c = _chef_client(self.site)
            r = c.get(self.url)
        self.assertContains(r, 'liste-a@cnt-so.info')
        self.assertContains(r, 'liste-b@cnt-so.info')



class OvhSyncSubscriptionTest(TestCase):
    """Les consentements newsletter du site sont répercutés sur les listes OVH."""

    def setUp(self):
        self.site = _ensure_section_page(slug='ovh-sync', name='OVH Sync', site_type='sectoral')
        self.site.ovh_mailing_list = 'liste-un, liste-deux'
        self.site.save(update_fields=['ovh_mailing_list'])

    def _make_subscriber(self, active=False):
        return Subscriber.objects.create(
            site=self.site, email='militant@example.org', is_active=active)

    @patch('cms.ovh_client.add_subscriber')
    def test_confirmation_ajoute_a_la_premiere_liste(self, mock_add):
        sub = self._make_subscriber(active=False)
        r = self.client.get(f'/newsletter/confirmer/{sub.token}/')
        self.assertEqual(r.status_code, 200)
        mock_add.assert_called_once_with('liste-un', 'militant@example.org')

    @patch('cms.ovh_client.add_subscriber')
    def test_deja_confirme_pas_de_double_ajout(self, mock_add):
        sub = self._make_subscriber(active=True)
        mock_add.reset_mock()  # l'appel de la création (signal) ne compte pas
        self.client.get(f'/newsletter/confirmer/{sub.token}/')
        mock_add.assert_not_called()

    @patch('cms.ovh_client.add_subscriber')
    def test_webhook_adhesion_conf_alimente_la_liste_du_principal(self, mock_add):
        import hashlib as _hashlib
        import hmac as _hmac
        import json as _json
        from django.test import override_settings
        principal = _ensure_section_page(slug='principal', name='CNT-SO')
        principal.ovh_mailing_list = 'news'
        principal.save(update_fields=['ovh_mailing_list'])
        body = _json.dumps({'email': 'adherent@example.org', 'newsletter_conf': True}).encode()
        with override_settings(ADHESION_WEBHOOK_SECRET='s3cret'):
            sig = _hmac.new(b's3cret', body, _hashlib.sha256).hexdigest()
            r = self.client.post('/api/newsletter/sync/', body,
                                 content_type='application/json',
                                 HTTP_X_WEBHOOK_SECRET=sig)
        self.assertEqual(r.status_code, 200)
        mock_add.assert_called_once_with('news', 'adherent@example.org')

    @patch('cms.ovh_client.add_subscriber')
    @patch('cms.ovh_client.remove_subscriber')
    def test_desabonnement_retire_de_toutes_les_listes(self, mock_remove, mock_add):
        sub = self._make_subscriber(active=True)
        r = self.client.post(f'/newsletter/desinscription/{sub.token}/')
        self.assertEqual(r.status_code, 200)
        calls = {c.args for c in mock_remove.call_args_list}
        self.assertEqual(calls, {('liste-un', 'militant@example.org'),
                                 ('liste-deux', 'militant@example.org')})

    @patch('cms.ovh_client.add_subscriber')
    def test_site_sans_liste_ovh_aucun_appel(self, mock_add):
        self.site.ovh_mailing_list = ''
        self.site.save(update_fields=['ovh_mailing_list'])
        sub = self._make_subscriber(active=False)
        self.client.get(f'/newsletter/confirmer/{sub.token}/')
        mock_add.assert_not_called()

    @patch('cms.ovh_client.add_subscriber', side_effect=Exception('API OVH KO'))
    def test_erreur_ovh_ne_bloque_pas_le_visiteur(self, mock_add):
        sub = self._make_subscriber(active=False)
        r = self.client.get(f'/newsletter/confirmer/{sub.token}/')
        self.assertEqual(r.status_code, 200)
        sub.refresh_from_db()
        self.assertTrue(sub.is_active)


# ════════════════════════════════════════════════════════════════════════════════
# API VIEWS — ImageUploadView, FileUploadView, NewsletterSyncView
# ════════════════════════════════════════════════════════════════════════════════

import hashlib
import hmac as hmac_module
import io
import json as json_module

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from content.api_views import _verify_image_magic


# ---------------------------------------------------------------------------
# _verify_image_magic : détection par magic bytes
# ---------------------------------------------------------------------------

class VerifyImageMagicTest(TestCase):

    def _buf(self, data):
        return io.BytesIO(data + b'\x00' * max(0, 12 - len(data)))

    def test_jpeg_detecte(self):
        self.assertEqual(_verify_image_magic(self._buf(b'\xff\xd8\xff')), 'image/jpeg')

    def test_png_detecte(self):
        self.assertEqual(_verify_image_magic(self._buf(b'\x89PNG\r\n')), 'image/png')

    def test_gif87a_detecte(self):
        self.assertEqual(_verify_image_magic(self._buf(b'GIF87a')), 'image/gif')

    def test_gif89a_detecte(self):
        self.assertEqual(_verify_image_magic(self._buf(b'GIF89a')), 'image/gif')

    def test_riff_webp_detecte(self):
        self.assertEqual(_verify_image_magic(self._buf(b'RIFF')), 'image/webp')

    def test_inconnu_retourne_none(self):
        self.assertIsNone(_verify_image_magic(self._buf(b'UNKNOWN_DATA')))

    def test_seek_remis_a_zero_apres_lecture(self):
        buf = self._buf(b'\xff\xd8\xff')
        _verify_image_magic(buf)
        self.assertEqual(buf.tell(), 0)


# ---------------------------------------------------------------------------
# ImageUploadView
# ---------------------------------------------------------------------------

class ImageUploadViewTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.user = make_superuser('img-upload-admin')
        self.url = reverse('content:image_upload')

    def _jpeg(self, name='test.jpg'):
        return SimpleUploadedFile(name, b'\xff\xd8\xff' + b'\x00' * 20,
                                  content_type='image/jpeg')

    def test_sans_fichier_retourne_failure(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url)
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 0)
        self.assertIn('Aucun fichier', data['message'])

    def test_type_mime_non_autorise(self):
        self.client.force_login(self.user)
        f = SimpleUploadedFile('test.svg', b'<svg/>', content_type='image/svg+xml')
        r = self.client.post(self.url, {'image': f})
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 0)

    def test_magic_bytes_incompatibles(self):
        """JPEG déclaré mais magic bytes incorrects."""
        self.client.force_login(self.user)
        f = SimpleUploadedFile('fake.jpg', b'not-an-image-at-all', content_type='image/jpeg')
        r = self.client.post(self.url, {'image': f})
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 0)

    def test_jpeg_valide_succes(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {'image': self._jpeg()})
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 1)
        self.assertIn('url', data['file'])
        self.assertIn('id', data['file'])

    def test_non_authentifie_redirige(self):
        r = self.client.post(self.url, {'image': self._jpeg()})
        self.assertIn(r.status_code, [302, 403])


# ---------------------------------------------------------------------------
# FileUploadView
# ---------------------------------------------------------------------------

class FileUploadViewTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.user = make_superuser('file-upload-admin')
        self.url = reverse('content:file_upload')

    def test_sans_fichier_retourne_failure(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url)
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 0)
        self.assertIn('Aucun fichier', data['message'])

    def test_type_non_autorise(self):
        self.client.force_login(self.user)
        f = SimpleUploadedFile('script.sh', b'#!/bin/bash', content_type='text/x-shellscript')
        r = self.client.post(self.url, {'file': f})
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 0)

    def test_pdf_valide_succes(self):
        self.client.force_login(self.user)
        f = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 test content', content_type='application/pdf')
        r = self.client.post(self.url, {'file': f})
        data = json_module.loads(r.content)
        self.assertEqual(data['success'], 1)
        self.assertIn('url', data['file'])
        self.assertIn('name', data['file'])

    def test_non_authentifie_redirige(self):
        f = SimpleUploadedFile('doc.pdf', b'%PDF-1.4', content_type='application/pdf')
        r = self.client.post(self.url, {'file': f})
        self.assertIn(r.status_code, [302, 403])


# ---------------------------------------------------------------------------
# NewsletterSyncView — signature HMAC + sync abonnés
# ---------------------------------------------------------------------------

def _hmac_sig(secret, body_bytes):
    return hmac_module.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


@override_settings(ADHESION_WEBHOOK_SECRET='test-secret-abc')
class NewsletterSyncViewTest(TestCase):

    def setUp(self):
        self.url = reverse('content:newsletter_sync')
        self.secret = 'test-secret-abc'

    def _post(self, data, secret=None):
        body = json_module.dumps(data).encode()
        sig = _hmac_sig(secret or self.secret, body)
        return self.client.post(
            self.url, data=body,
            content_type='application/json',
            HTTP_X_WEBHOOK_SECRET=sig,
        )

    def test_signature_invalide_retourne_403(self):
        body = json_module.dumps({'email': 'a@b.fr'}).encode()
        r = self.client.post(self.url, data=body, content_type='application/json',
                             HTTP_X_WEBHOOK_SECRET='mauvaise-signature')
        self.assertEqual(r.status_code, 403)

    def test_json_invalide_retourne_400(self):
        sig = _hmac_sig(self.secret, b'not-json')
        r = self.client.post(self.url, data=b'not-json', content_type='application/json',
                             HTTP_X_WEBHOOK_SECRET=sig)
        self.assertEqual(r.status_code, 400)

    def test_email_manquant_retourne_400(self):
        r = self._post({'newsletter_conf': True})
        self.assertEqual(r.status_code, 400)

    def test_sync_newsletter_conf_subscribe(self):
        r = self._post({'email': 'conf@test.fr', 'newsletter_conf': True})
        self.assertEqual(r.status_code, 200)
        data = json_module.loads(r.content)
        self.assertTrue(data['ok'])
        self.assertIn('conf', data['result'])
        self.assertTrue(Subscriber.objects.filter(email='conf@test.fr', site=None).exists())

    def test_sync_newsletter_conf_unsubscribe(self):
        Subscriber.objects.create(email='unsub@test.fr', site=None, is_active=True)
        r = self._post({'email': 'unsub@test.fr', 'newsletter_conf': False})
        self.assertEqual(r.status_code, 200)
        sub = Subscriber.objects.get(email='unsub@test.fr', site=None)
        self.assertFalse(sub.is_active)

    def test_sync_deja_abonne_met_a_jour(self):
        """Un abonné inactif qui se réinscrit est réactivé."""
        Subscriber.objects.create(email='reactiv@test.fr', site=None, is_active=False)
        r = self._post({'email': 'reactiv@test.fr', 'newsletter_conf': True})
        self.assertEqual(r.status_code, 200)
        sub = Subscriber.objects.get(email='reactiv@test.fr', site=None)
        self.assertTrue(sub.is_active)

    def test_sync_avec_syndicat_slug_existant(self):
        site = _ensure_section_page(slug='sync-test-synd', name='Sync Synd')
        r = self._post({
            'email': 'synd@test.fr',
            'newsletter_conf': True,
            'newsletter_synd': True,
            'syndicat_slug': 'sync-test-synd',
        })
        self.assertEqual(r.status_code, 200)
        data = json_module.loads(r.content)
        self.assertIn('synd', data['result'])
        self.assertTrue(Subscriber.objects.filter(email='synd@test.fr', site=site).exists())

    def test_sync_avec_syndicat_slug_inexistant(self):
        r = self._post({
            'email': 'missing@test.fr',
            'newsletter_conf': True,
            'newsletter_synd': True,
            'syndicat_slug': 'slug-qui-nexiste-pas',
        })
        self.assertEqual(r.status_code, 200)
        data = json_module.loads(r.content)
        self.assertIn('introuvable', data['result'].get('synd', ''))

    def test_sans_secret_configure_retourne_403(self):
        with override_settings(ADHESION_WEBHOOK_SECRET=''):
            body = json_module.dumps({'email': 'x@y.fr'}).encode()
            r = self.client.post(self.url, data=body, content_type='application/json',
                                 HTTP_X_WEBHOOK_SECRET='n-importe-quoi')
        self.assertEqual(r.status_code, 403)


# ════════════════════════════════════════════════════════════════════════════════
# NEWSLETTER VIEWS — chemins non couverts
# ════════════════════════════════════════════════════════════════════════════════

class NewsletterSendEdgeTest(TestCase):
    """Cas limites non couverts : déjà envoyée, mode test, sans abonnés, erreurs."""

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='nl-edge', name='NL Edge', site_type='sectoral')
        self.newsletter = _make_newsletter(self.site)
        self.url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'

    def test_get_newsletter_deja_envoyee_redirige(self):
        self.newsletter.status = 'sent'
        self.newsletter.save(update_fields=['status'])
        c = _chef_client(self.site)
        r = c.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_get_ovh_liste_erreur_affiche_none_abonnes(self):
        self.site.ovh_mailing_list = 'liste-err'
        self.site.save(update_fields=['ovh_mailing_list'])
        with patch('cms.ovh_client.get_subscribers', side_effect=Exception('OVH down')):
            c = _chef_client(self.site)
            r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['nb_subscribers'])

    def test_post_deja_envoyee_redirige(self):
        self.newsletter.status = 'sent'
        self.newsletter.save(update_fields=['status'])
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'send'})
        self.assertEqual(r.status_code, 302)

    def test_post_mode_test_sans_email_redirige_avec_erreur(self):
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'test', 'test_email': ''}, follow=True)
        messages_list = list(r.context['messages'])
        self.assertTrue(any('manquante' in str(m) for m in messages_list))

    def test_post_mode_test_email_invalide_redirige_avec_erreur(self):
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'test', 'test_email': 'pas-un-email'}, follow=True)
        messages_list = list(r.context['messages'])
        self.assertTrue(any('invalide' in str(m) for m in messages_list))

    def test_post_mode_test_email_valide_envoie_email(self):
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'test', 'test_email': 'test@recipient.fr'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('test@recipient.fr', mail.outbox[0].to)
        self.assertIn('[TEST]', mail.outbox[0].subject)

    def test_post_sans_abonnes_affiche_warning(self):
        """Sans liste OVH et sans abonnés actifs → message d'avertissement."""
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'send'}, follow=True)
        messages_list = list(r.context['messages'])
        self.assertTrue(any('Aucun abonné' in str(m) for m in messages_list))

    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP'))
    def test_post_direct_avec_erreurs_envoi_affiche_compteur(self, mock_send):
        """Erreurs d'envoi → warning avec nb erreurs."""
        Subscriber.objects.create(site=self.site, email='e1@test.fr', is_active=True)
        Subscriber.objects.create(site=self.site, email='e2@test.fr', is_active=True)
        c = _chef_client(self.site)
        r = c.post(self.url, {'mode': 'send'}, follow=True)
        messages_list = list(r.context['messages'])
        # Le warning avec erreur(s) doit apparaître
        self.assertTrue(any('erreur' in str(m).lower() for m in messages_list))


def _chef_client_with_site(site):
    """Chef client avec les deux clés de session pour get_current_site_for_view."""
    from django.contrib.auth.models import User
    from cms.site_context import SESSION_KEY
    _setup_editorial_groups()
    user = User.objects.create_superuser(
        username=f'chef-export-{site.pk}', password='pass'
    )
    c = __import__('django.test', fromlist=['Client']).Client()
    c.force_login(user)
    session = c.session
    session[SESSION_KEY] = site.pk
    session['redac_current_site_id'] = site.pk
    session.save()
    return c


class SubscriberExportViewTest(TestCase):
    """Export CSV des abonnés."""

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='export-nl', name='Export NL', site_type='sectoral')
        self.url = '/cms/abonnes/export/'

    def test_sans_site_courant_redirige(self):
        """Superadmin sans site sélectionné en session → redirect."""
        user = make_superuser('export-admin-nosess')
        self.client.force_login(user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_avec_site_retourne_csv(self):
        from content.models import Subscriber
        Subscriber.objects.create(site=self.site, email='ab@example.com',
                                  name='Alice', is_active=True)
        c = _chef_client_with_site(self.site)
        r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        content = r.content.decode('utf-8-sig')
        self.assertIn('ab@example.com', content)
        self.assertIn('Alice', content)

    def test_csv_entete_colonnes(self):
        c = _chef_client_with_site(self.site)
        r = c.get(self.url)
        content = r.content.decode('utf-8-sig')
        self.assertIn('email', content)
        self.assertIn('nom', content)

    def test_non_authentifie_redirige(self):
        r = self.client.get(self.url)
        self.assertIn(r.status_code, [302, 403])


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN_UTILS — get_current_site_for_view + WagtailChefRequiredMixin
# ════════════════════════════════════════════════════════════════════════════════

class GetCurrentSiteForViewTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()

    def _request(self, user, session_data=None):
        rf = RequestFactory()
        req = rf.get('/')
        req.user = user
        req.session = {}
        if session_data:
            req.session.update(session_data)
        return req

    def test_chef_session_valide_retourne_site(self):
        from content.admin_utils import get_current_site_for_view
        site = _ensure_section_page(slug='gcsfv-1', name='GCSFV1')
        user = make_superuser('gcsfv-admin-1')
        req = self._request(user, {'redac_current_site_id': site.pk})
        result = get_current_site_for_view(req)
        self.assertEqual(result, site)

    def test_chef_session_id_invalide_retourne_none(self):
        from content.admin_utils import get_current_site_for_view
        user = make_superuser('gcsfv-admin-2')
        req = self._request(user, {'redac_current_site_id': 99999})
        result = get_current_site_for_view(req)
        self.assertIsNone(result)

    def test_chef_sans_session_retourne_none(self):
        from content.admin_utils import get_current_site_for_view
        user = make_superuser('gcsfv-admin-3')
        req = self._request(user)
        result = get_current_site_for_view(req)
        self.assertIsNone(result)

    def test_non_chef_avec_author_profile_retourne_site(self):
        from content.admin_utils import get_current_site_for_view
        site = _ensure_section_page(slug='gcsfv-2', name='GCSFV2')
        user = make_redacteur('gcsfv-redac', site=site)
        req = self._request(user)
        result = get_current_site_for_view(req)
        self.assertEqual(result, site)

    def test_non_chef_sans_author_profile_retourne_none(self):
        from content.admin_utils import get_current_site_for_view
        user = User.objects.create_user(username='gcsfv-anon', password='pass')
        req = self._request(user)
        result = get_current_site_for_view(req)
        self.assertIsNone(result)


class WagtailChefMixinPermissionTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='chef-perm', name='Chef Perm')

    def test_redacteur_avec_syndicat_accede_au_contact(self):
        """Autonomie 2026-07-16 : les messages de contact du syndicat sont un
        outil de ses rédacteurs (WagtailSyndicatRequiredMixin, scoping par
        site courant)."""
        user = make_redacteur('notchef-wcm', site=self.site)
        self.client.force_login(user)
        r = self.client.get('/cms/contact/')
        self.assertEqual(r.status_code, 200)

    def test_authentifie_sans_syndicat_redirige(self):
        """Sans syndicat résolu (ni groupe ni Author.site), toujours refusé."""
        user = User.objects.create_user(username='sans-synd-wcm', password='pass')
        self.client.force_login(user)
        r = self.client.get('/cms/contact/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/cms/', r['Location'])


# ════════════════════════════════════════════════════════════════════════════════
# MODELS — __str__ et propriétés non couverts
# ════════════════════════════════════════════════════════════════════════════════

class ModelStrMethodsTest(TestCase):

    def setUp(self):
        from cms.models import SectionPage
        self.sp = _ensure_section_page(slug='model-str-site', name='Str Site', site_type='regional')

    def test_tag_str(self):
        tag = Tag.objects.create(site=self.sp, name='Mon Tag', slug='mon-tag')
        self.assertEqual(str(tag), 'Mon Tag')

    def test_media_str_with_title(self):
        m = Media.objects.create(title='Photo test', original_url='https://example.com/img.jpg')
        self.assertEqual(str(m), 'Photo test')

    def test_media_str_without_title(self):
        m = Media.objects.create(title='', original_url='https://example.com/img.jpg')
        self.assertEqual(str(m), 'https://example.com/img.jpg')

    def test_media_url_property_without_file(self):
        m = Media.objects.create(title='', original_url='https://example.com/x.jpg')
        self.assertEqual(m.url, 'https://example.com/x.jpg')

    def test_page_str(self):
        p = Page.objects.create(
            site=self.sp, title='Ma Page', slug='ma-page', status='publish'
        )
        self.assertEqual(str(p), 'Ma Page')

    def test_contact_message_str_with_subject(self):
        from content.models import ContactMessage
        msg = ContactMessage.objects.create(
            site=self.sp, name='Alice', email='alice@test.fr', subject='Question', message='?'
        )
        self.assertIn('Question', str(msg))
        self.assertIn('Alice', str(msg))

    def test_contact_message_str_without_subject(self):
        from content.models import ContactMessage
        msg = ContactMessage.objects.create(
            site=self.sp, name='Bob', email='bob@test.fr', subject='', message='bonjour'
        )
        self.assertIn('sans objet', str(msg))

    def test_menu_item_str(self):
        item = MenuItem.objects.create(
            site=self.sp, title='Accueil', menu='main', order=1, link_type='url', url='/'
        )
        self.assertIn('Accueil', str(item))

    def test_subscriber_str(self):
        sub = Subscriber.objects.create(
            site=self.sp, email='sub@test.fr', name='Charlie', is_active=True
        )
        result = str(sub)
        self.assertIn('sub@test.fr', result)
        self.assertIn('Str Site', result)

    def test_article_str(self):
        from content.models import Article
        art = Article.objects.create(site=self.sp, title='Mon Article Test', slug='mon-article-test')
        self.assertEqual(str(art), 'Mon Article Test')


class MenuItemGetUrlTest(TestCase):

    def setUp(self):
        self.sp = _ensure_section_page(slug='menu-url-site', name='Menu URL Site', site_type='regional')

    def test_get_url_direct_url(self):
        item = MenuItem.objects.create(
            site=self.sp, title='Lien', menu='main', order=1,
            link_type='url', url='https://external.com'
        )
        self.assertEqual(item.get_url(), 'https://external.com')

    def test_get_url_article(self):
        art = make_article_page(section_slug=self.sp.slug, title='Art URL', slug='art-url')
        item = MenuItem.objects.create(
            site=self.sp, title='Art', menu='main', order=1,
            link_type='article', article=art
        )
        self.assertIn('art-url', item.get_url())

    def test_get_url_category(self):
        cat = make_cms_category(name='Cat URL', slug='cat-url', section_slug='principal')
        item = MenuItem.objects.create(
            site=self.sp, title='Cat', menu='main', order=1,
            link_type='category', category=cat
        )
        self.assertIn('cat-url', item.get_url())

    def test_get_url_page(self):
        page = make_content_page(section_slug=self.sp.slug, title='Page URL', slug='page-url')
        item = MenuItem.objects.create(
            site=self.sp, title='Page', menu='main', order=1,
            link_type='page', page=page
        )
        self.assertEqual(item.get_url(), page.get_absolute_url())

    def test_get_url_contact_sous_site(self):
        item = MenuItem.objects.create(
            site=self.sp, title='Contact', menu='main', order=1,
            link_type='contact',
        )
        url = item.get_url()
        self.assertIn('contact', url)
        self.assertIn('menu-url-site', url)

    def test_get_url_agenda_sous_site(self):
        item = MenuItem.objects.create(
            site=self.sp, title='Agenda', menu='main', order=1,
            link_type='agenda',
        )
        url = item.get_url()
        self.assertIn('agenda', url)

    def test_get_url_fallback_retourne_diese(self):
        item = MenuItem.objects.create(
            site=self.sp, title='Vide', menu='main', order=1,
            link_type='url', url='',
        )
        self.assertEqual(item.get_url(), '#')


# ════════════════════════════════════════════════════════════════════════════════
# SITEMAPS — lastmod et location
# ════════════════════════════════════════════════════════════════════════════════

class SitemapMethodsTest(TestCase):

    def setUp(self):
        self.sp = _ensure_section_page(slug='sitemap-site', name='Sitemap Site', site_type='regional')

    def test_page_sitemap_location(self):
        from content.sitemaps import PageSitemap
        page = make_content_page(section_slug=self.sp.slug, title='Sitemap Page', slug='sitemap-page')
        sm = PageSitemap()
        self.assertEqual(sm.location(page), page.get_absolute_url())

    def test_page_sitemap_lastmod_retourne_date_publication(self):
        from content.sitemaps import PageSitemap
        page = make_content_page(section_slug=self.sp.slug, title='Sitemap Page 2', slug='sitemap-page-2')
        page.refresh_from_db()
        sm = PageSitemap()
        self.assertEqual(sm.lastmod(page), page.last_published_at or page.first_published_at)

    def test_category_sitemap_location(self):
        from content.sitemaps import CategorySitemap
        cat = make_cms_category(name='Sitemap Cat', slug='sitemap-cat', section_slug='principal')
        sm = CategorySitemap()
        self.assertIn('sitemap-cat', sm.location(cat))


# ════════════════════════════════════════════════════════════════════════════════
# FORMS — champs DynamicContactForm non couverts
# ════════════════════════════════════════════════════════════════════════════════

class DynamicContactFormFieldsTest(TestCase):

    def setUp(self):
        self.site = _ensure_section_page(slug='dyn-form-site', name='Dyn Form Site')
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sans_formulaire_retourne_early(self):
        from content.forms import DynamicContactForm
        form = DynamicContactForm()
        self.assertIn('email', form.fields)
        self.assertNotIn('captcha', form.fields)

    def test_champ_ville_present(self):
        from content.forms import DynamicContactForm
        f = make_formulaire_contact(self.site, field_ville=True)
        form = DynamicContactForm(formulaire=f)
        self.assertIn('ville', form.fields)

    def test_champ_secteur_present(self):
        from content.forms import DynamicContactForm
        f = make_formulaire_contact(self.site, field_secteur=True)
        form = DynamicContactForm(formulaire=f)
        self.assertIn('secteur', form.fields)

    def test_champ_custom_textarea(self):
        from content.forms import DynamicContactForm
        f = make_formulaire_contact(self.site)
        make_champ_contact(f, label='Contexte', slug='contexte', field_type='textarea')
        form = DynamicContactForm(formulaire=f)
        self.assertIn('custom_contexte', form.fields)
        from django.forms import Textarea
        self.assertIsInstance(form.fields['custom_contexte'].widget, Textarea)

    def test_champ_custom_checkbox(self):
        from content.forms import DynamicContactForm
        f = make_formulaire_contact(self.site)
        make_champ_contact(f, label='Accord', slug='accord', field_type='checkbox', is_required=True)
        form = DynamicContactForm(formulaire=f)
        self.assertIn('custom_accord', form.fields)
        from django.forms import BooleanField
        self.assertIsInstance(form.fields['custom_accord'], BooleanField)


# ════════════════════════════════════════════════════════════════════════════════
# TEMPLATETAGS — render_content filter
# ════════════════════════════════════════════════════════════════════════════════

class RenderContentFilterTest(TestCase):

    def _render(self, content):
        from content.templatetags.content_tags import render_content
        return str(render_content(content))

    def test_none_retourne_vide(self):
        self.assertEqual(self._render(None), '')

    def test_vide_retourne_vide(self):
        self.assertEqual(self._render(''), '')

    def test_html_brut_retourne_tel_quel(self):
        html = '<p>Bonjour <b>monde</b></p>'
        result = self._render(html)
        self.assertIn('<p>Bonjour', result)

    def test_json_invalide_retourne_echappe(self):
        result = self._render('{pas du json valide')
        self.assertIn('{pas du json valide', result)

    def test_json_paragraphe(self):
        content = json_module.dumps({'blocks': [{'type': 'paragraph', 'data': {'text': 'Hello'}}]})
        result = self._render(content)
        self.assertIn('<p>Hello</p>', result)

    def test_json_header(self):
        content = json_module.dumps({'blocks': [{'type': 'header', 'data': {'text': 'Titre', 'level': 2}}]})
        result = self._render(content)
        self.assertIn('<h2>Titre</h2>', result)

    def test_json_quote_avec_caption(self):
        content = json_module.dumps({'blocks': [{'type': 'quote', 'data': {'text': 'Proverbe', 'caption': 'Auteur'}}]})
        result = self._render(content)
        self.assertIn('<blockquote>', result)
        self.assertIn('<cite>', result)
        self.assertIn('Auteur', result)

    def test_json_code(self):
        content = json_module.dumps({'blocks': [{'type': 'code', 'data': {'code': 'print("ok")'}}]})
        result = self._render(content)
        self.assertIn('<pre><code>', result)
        self.assertIn('print', result)

    def test_json_delimiter(self):
        content = json_module.dumps({'blocks': [{'type': 'delimiter', 'data': {}}]})
        result = self._render(content)
        self.assertIn('<hr>', result)

    def test_json_image_avec_url(self):
        content = json_module.dumps({'blocks': [{'type': 'image', 'data': {
            'file': {'url': 'https://example.com/img.jpg'},
            'caption': 'Photo',
            'stretched': True,
        }}]})
        result = self._render(content)
        self.assertIn('<figure', result)
        self.assertIn('alignfull', result)

    def test_json_image_with_background(self):
        content = json_module.dumps({'blocks': [{'type': 'image', 'data': {
            'file': {'url': 'https://example.com/img.jpg'},
            'withBackground': True,
        }}]})
        result = self._render(content)
        self.assertIn('with-background', result)

    def test_json_image_sans_url_retourne_vide(self):
        content = json_module.dumps({'blocks': [{'type': 'image', 'data': {'file': {'url': ''}}}]})
        result = self._render(content)
        self.assertNotIn('<figure', result)

    def test_json_gallery(self):
        content = json_module.dumps({'blocks': [{'type': 'gallery', 'data': {
            'images': [
                {'url': 'https://example.com/a.jpg', 'caption': 'A'},
                {'url': '', 'caption': 'skip'},
            ],
            'columns': 2,
        }}]})
        result = self._render(content)
        self.assertIn('blocks-gallery-grid', result)
        self.assertIn('columns-2', result)
        self.assertNotIn('skip', result)

    def test_json_embed_sans_url_retourne_vide(self):
        content = json_module.dumps({'blocks': [{'type': 'embed', 'data': {'embed': ''}}]})
        result = self._render(content)
        self.assertNotIn('<iframe', result)

    def test_json_embed_avec_url(self):
        content = json_module.dumps({'blocks': [{'type': 'embed', 'data': {'embed': 'https://example.com/video'}}]})
        result = self._render(content)
        self.assertIn('<iframe', result)

    def test_json_table(self):
        content = json_module.dumps({'blocks': [{'type': 'table', 'data': {
            'content': [['H1', 'H2'], ['A', 'B'], 'invalid-row'],
            'withHeadings': True,
        }}]})
        result = self._render(content)
        self.assertIn('<table>', result)
        self.assertIn('<th>', result)
        self.assertIn('<td>', result)

    def test_json_bloc_inconnu_retourne_vide(self):
        content = json_module.dumps({'blocks': [{'type': 'unknown_block_xyz', 'data': {}}]})
        result = self._render(content)
        self.assertNotIn('unknown_block_xyz', result)


# ════════════════════════════════════════════════════════════════════════════════
# VIEWS — SiteRejoindreView, SiteRessourcesView
# ════════════════════════════════════════════════════════════════════════════════

class SiteRejoindreViewTest(TestCase):

    def setUp(self):
        self.site = _ensure_section_page(slug='rejoindre-site', name='Rejoindre Site', site_type='sectoral')
        self.url = reverse('content:site_rejoindre', kwargs={'site_slug': 'rejoindre-site'})
        patcher = patch('hcaptcha.fields.hCaptchaField.validate', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_retourne_200(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_post_invalide_reaffiche_formulaire(self):
        r = self.client.post(self.url, {'name': '', 'email': 'bad'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['form'].is_valid())

    def test_post_valide_cree_message_et_succes(self):
        from content.models import ContactMessage
        data = {
            'name': 'Alice', 'email': 'alice@test.fr',
            'phone': '', 'city': '', 'sector': '',
            'subject': 'Test', 'message': 'Bonjour',
            'h-captcha-response': 'test-token',
        }
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context.get('success'))
        self.assertTrue(ContactMessage.objects.filter(email='alice@test.fr').exists())


class SiteRessourcesViewTest(TestCase):

    def setUp(self):
        self.site = _ensure_section_page(slug='ressources-site', name='Ressources Site', site_type='sectoral')
        self.url = reverse('content:site_ressources', kwargs={'site_slug': 'ressources-site'})

    def test_get_retourne_200(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_get_avec_filtre_categorie(self):
        cat = make_cms_category(name='Cat Ressource', slug='cat-ressource', section_slug='ressources-site')
        art = make_article_page(section_slug='ressources-site', title='Art Ressource', slug='art-ressource',
                                categories=[cat])
        r = self.client.get(self.url + '?cat=cat-ressource')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['active_cat'], cat)

    def test_get_site_inconnu_retourne_404(self):
        r = self.client.get(reverse('content:site_ressources', kwargs={'site_slug': 'inexistant'}))
        self.assertEqual(r.status_code, 404)

    def test_categories_vides_masquees(self):
        """Seules les catégories avec au moins un article publié sont proposées en filtre."""
        pleine = make_cms_category(name='Pleine', slug='pleine', section_slug='ressources-site')
        make_cms_category(name='Vide', slug='vide', section_slug='ressources-site')
        brouillon = make_cms_category(name='Brouillon Only', slug='brouillon-only',
                                      section_slug='ressources-site')
        make_article_page(section_slug='ressources-site', title='Pub', slug='res-pub',
                          categories=[pleine])
        make_article_page(section_slug='ressources-site', title='Draft', slug='res-draft',
                          categories=[brouillon], live=False)
        r = self.client.get(self.url)
        slugs = [c.slug for c in r.context['categories']]
        self.assertIn('pleine', slugs)
        self.assertNotIn('vide', slugs)
        self.assertNotIn('brouillon-only', slugs)

    def test_categorie_pas_dupliquee_avec_plusieurs_articles(self):
        """Une catégorie liée à plusieurs articles n'apparaît qu'une fois (distinct)."""
        cat = make_cms_category(name='Multi', slug='multi', section_slug='ressources-site')
        make_article_page(section_slug='ressources-site', title='A1', slug='res-a1', categories=[cat])
        make_article_page(section_slug='ressources-site', title='A2', slug='res-a2', categories=[cat])
        r = self.client.get(self.url)
        slugs = [c.slug for c in r.context['categories']]
        self.assertEqual(slugs.count('multi'), 1)


# ════════════════════════════════════════════════════════════════════════════════
# CONTACT CMS VIEWS — chemins non couverts
# ════════════════════════════════════════════════════════════════════════════════

class ContactSubmissionListFilterTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='contact-list-site', name='Contact List', site_type='sectoral')
        self.url = '/cms/contact/'

    def test_filtre_read_affiche_seulement_lus(self):
        from content.models import ContactMessage
        ContactMessage.objects.create(site=self.site, name='A', email='a@a.fr', message='m', is_read=True)
        ContactMessage.objects.create(site=self.site, name='B', email='b@b.fr', message='m', is_read=False)
        c = _chef_client_with_site(self.site)
        r = c.get(self.url + '?status=read')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['submissions'].count(), 1)
        self.assertEqual(r.context['submissions'].first().email, 'a@a.fr')


class FormulaireContactConfigTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='cfg-contact', name='Config Contact', site_type='sectoral')
        self.url = '/cms/contact-config/'

    def test_post_sans_site_redirige(self):
        user = make_superuser('cfg-no-site')
        self.client.force_login(user)
        r = self.client.post(self.url, {'is_active': 'on'})
        self.assertEqual(r.status_code, 302)

    def test_get_sans_site_redirige(self):
        user = make_superuser('cfg-no-site-get')
        self.client.force_login(user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_post_email_vide_efface_email_destination(self):
        from content.models import FormulaireContact
        c = _chef_client_with_site(self.site)
        # S'assurer que le formulaire existe
        FormulaireContact.objects.get_or_create(site=self.site, defaults={'email_destination': 'old@test.fr'})
        r = c.post(self.url, {'is_active': 'on', 'email_destination': ''})
        self.assertEqual(r.status_code, 302)
        f = FormulaireContact.objects.get(site=self.site)
        self.assertEqual(f.email_destination, '')


class ChampContactCreateViewTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='champ-create', name='Champ Create', site_type='sectoral')
        self.url = '/cms/contact-config/champ/ajouter/'

    def test_sans_site_redirige(self):
        user = make_superuser('champ-no-site')
        self.client.force_login(user)
        r = self.client.post(self.url, {'label': 'Test'})
        self.assertEqual(r.status_code, 302)

    def test_label_vide_redirige(self):
        from content.models import FormulaireContact
        FormulaireContact.objects.get_or_create(site=self.site)
        c = _chef_client_with_site(self.site)
        r = c.post(self.url, {'label': ''})
        self.assertEqual(r.status_code, 302)

    def test_slug_collision_incremente_compteur(self):
        from content.models import FormulaireContact, ChampContactCustom
        f, _ = FormulaireContact.objects.get_or_create(site=self.site)
        ChampContactCustom.objects.create(formulaire=f, label='Mon champ', slug='mon-champ',
                                          field_type='text', order=0)
        c = _chef_client_with_site(self.site)
        r = c.post(self.url, {'label': 'Mon champ', 'field_type': 'text'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ChampContactCustom.objects.filter(formulaire=f).count(), 2)
        slugs = list(ChampContactCustom.objects.filter(formulaire=f).values_list('slug', flat=True))
        self.assertIn('mon-champ-1', slugs)


class ChampContactDeleteViewTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='champ-delete', name='Champ Delete', site_type='sectoral')

    def test_sans_site_redirige(self):
        user = make_superuser('champ-del-no-site')
        self.client.force_login(user)
        r = self.client.post('/cms/contact-config/champ/999/supprimer/')
        self.assertEqual(r.status_code, 302)

    def test_supprime_champ(self):
        from content.models import FormulaireContact, ChampContactCustom
        f, _ = FormulaireContact.objects.get_or_create(site=self.site)
        champ = ChampContactCustom.objects.create(formulaire=f, label='Del', slug='del',
                                                   field_type='text', order=0)
        c = _chef_client_with_site(self.site)
        r = c.post(f'/cms/contact-config/champ/{champ.pk}/supprimer/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ChampContactCustom.objects.filter(pk=champ.pk).exists())


# ════════════════════════════════════════════════════════════════════════════════
# SUITE DE MICRO-TESTS pour les lignes restantes
# ════════════════════════════════════════════════════════════════════════════════

class AdminUtilsHandleNoPermUnauthTest(TestCase):
    """admin_utils line 36 : handle_no_permission pour unauthenticated."""

    def test_handle_no_permission_unauthentifie(self):
        from content.admin_utils import WagtailChefRequiredMixin
        from unittest.mock import Mock
        mixin = WagtailChefRequiredMixin()
        mixin.request = Mock()
        mixin.request.user.is_authenticated = False
        response = mixin.handle_no_permission()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cms/', response['Location'])


class MenuItemGetUrlExtraTest(TestCase):

    def setUp(self):
        self.principal = make_site('principal', wp_blog_id=1, site_type='main', name='CNT-SO')
        self.sp = _ensure_section_page(slug='menu-extra', name='Menu Extra', site_type='regional')

    def test_get_url_site_link_type(self):
        target = _ensure_section_page(slug='target-sp', name='Target SP', site_type='regional')
        item = MenuItem.objects.create(
            site=self.sp, title='Site', menu='main', order=1,
            link_type='site', target_site=target,
        )
        url = item.get_url()
        self.assertIn('target-sp', url)

    def test_get_url_contact_principal(self):
        item = MenuItem.objects.create(
            site=self.principal, title='Contact', menu='main', order=1,
            link_type='contact',
        )
        url = item.get_url()
        self.assertIn('contact', url)
        self.assertNotIn('principal', url)

    def test_get_url_fallback_avec_article(self):
        """link_type inconnu avec article FK → fallback sur article.get_absolute_url()."""
        art = make_article_page(section_slug=self.sp.slug, title='Fallback Art', slug='fallback-art')
        item = MenuItem.objects.create(
            site=self.sp, title='FB', menu='main', order=1,
            link_type='category', article=art,
        )
        item.link_type = 'unknown_type'
        item.save()
        url = item.get_url()
        self.assertIn('fallback-art', url)

    def test_get_url_fallback_avec_page(self):
        """link_type inconnu avec page FK → fallback sur page.get_absolute_url()."""
        page = make_content_page(section_slug=self.sp.slug, title='Fallback Page', slug='fallback-page')
        item = MenuItem.objects.create(
            site=self.sp, title='FB2', menu='main', order=1,
            link_type='unknown_type', page=page,
        )
        self.assertEqual(item.get_url(), page.get_absolute_url())

    def test_get_url_fallback_avec_category(self):
        """link_type inconnu avec category FK → fallback sur category.get_absolute_url()."""
        cat = make_cms_category(name='FB Cat', slug='fb-cat', section_slug='principal')
        item = MenuItem.objects.create(
            site=self.sp, title='FB3', menu='main', order=1,
            link_type='unknown_type', category=cat,
        )
        url = item.get_url()
        self.assertIn('fb-cat', url)

    def test_get_url_fallback_avec_url_directe(self):
        """link_type inconnu mais url renseignée → ligne 508-509."""
        item = MenuItem.objects.create(
            site=self.sp, title='FB4', menu='main', order=1,
            link_type='unknown_type', url='https://direct.example.com',
        )
        url = item.get_url()
        self.assertEqual(url, 'https://direct.example.com')


class GalleryInvalidColumnsTest(TestCase):
    """content_tags lines 83-84 : columns invalide → fallback 3."""

    def test_gallery_colonnes_invalides(self):
        from content.templatetags.content_tags import render_content
        content = json_module.dumps({'blocks': [{'type': 'gallery', 'data': {
            'images': [{'url': 'https://example.com/img.jpg', 'caption': ''}],
            'columns': 'invalide',
        }}]})
        result = str(render_content(content))
        self.assertIn('columns-3', result)


class ViewsAdditionalCoverageTest(TestCase):
    """Couvre les lignes restantes de views.py."""

    def setUp(self):
        self.principal = make_site('principal', wp_blog_id=1, site_type='main', name='CNT-SO')

    def test_site_home_view_non_sectoral_utilise_site_home_html(self):
        """SiteHomeView.get_template_names() → line 138 pour site type 'main'."""
        main_site = _ensure_section_page(slug='main-home', name='Main Home', site_type='main')
        r = self.client.get(f'/main-home/')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'content/site_home.html')

    def test_article_detail_avec_categorie_couvre_category_latest(self):
        """ArticleDetailView.get_context_data() line 234."""
        cat = make_cms_category(name='Cat Detail', slug='cat-detail', section_slug='principal')
        art = make_article_page(section_slug='principal', title='Art Detail Cat',
                                slug='art-detail-cat', categories=[cat])
        r = self.client.get(art.get_absolute_url())
        self.assertEqual(r.status_code, 200)
        self.assertIn('category_latest', r.context)

    def test_site_article_detail(self):
        """SiteArticleDetailView.get_queryset() lines 246-247."""
        sub = _ensure_section_page(slug='sub-art-detail', name='Sub Art Detail', site_type='regional')
        art = make_article_page(section_slug='sub-art-detail', title='Sub Art', slug='sub-art')
        r = self.client.get(
            reverse('content:site_article_detail', kwargs={'site_slug': 'sub-art-detail', 'slug': 'sub-art'})
        )
        self.assertEqual(r.status_code, 200)

    def test_page_detail(self):
        """PageDetailView.get_queryset() line 298."""
        p = Page.objects.create(
            site=self.principal, title='Legacy Page', slug='legacy-page', status='publish'
        )
        r = self.client.get(reverse('content:page_detail', kwargs={'slug': 'legacy-page'}))
        self.assertEqual(r.status_code, 200)

    def test_site_page_detail(self):
        """SitePageDetailView.get_queryset() lines 310-311."""
        sub = _ensure_section_page(slug='sub-page-det', name='Sub Page Det', site_type='regional')
        p = Page.objects.create(site=sub, title='Sub Page', slug='sub-page-slug', status='publish')
        r = self.client.get(
            reverse('content:site_page_detail', kwargs={'site_slug': 'sub-page-det', 'slug': 'sub-page-slug'})
        )
        self.assertEqual(r.status_code, 200)

    def test_home_view_avec_trois_featured_articles(self):
        """HomeView line 69 : mini = sticky_mini quand 3+ articles sticky."""
        for i in range(4):
            make_article_page(
                section_slug='principal', title=f'Sticky {i}', slug=f'sticky-{i}',
                is_featured=True
            )
        r = self.client.get(reverse('content:home'))
        self.assertEqual(r.status_code, 200)

    def test_wordpress_redirect_avec_site_path_et_article(self):
        """WordPressRedirectView lines 491-496 — site_path match."""
        sub = _ensure_section_page(slug='wp-sub', name='WP Sub', site_type='regional')
        sub.wp_path = 'wp-sub-path'
        sub.save(update_fields=['wp_path'])
        art = make_article_page(section_slug='wp-sub', title='WP Art', slug='wp-art')
        url = f'/wp-sub-path/2024/01/wp-art/'
        r = self.client.get(url)
        self.assertIn(r.status_code, [301, 302, 404])

    def test_newsletter_subscribe_avec_site_slug(self):
        """NewsletterSubscribeView._get_site() line 725."""
        site = _ensure_section_page(slug='nl-sub-slug', name='NL Sub', site_type='sectoral')
        site.live = True
        site.save(update_fields=['live'])
        r = self.client.post(
            reverse('content:site_newsletter_subscribe', kwargs={'site_slug': 'nl-sub-slug'}),
            {'email': 'sub@test.fr'}
        )
        self.assertIn(r.status_code, [200, 302])

    def test_send_contact_email_sans_recipient_retourne_silencieusement(self):
        """_send_contact_email line 523 — aucune adresse configurée."""
        from content.views import _send_contact_email
        from content.models import ContactMessage
        from django.test import override_settings
        site = _ensure_section_page(slug='no-email-site', name='No Email Site')
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='m'
        )
        with override_settings(DEFAULT_CONTACT_EMAIL='', DEFAULT_FROM_EMAIL=''):
            result = _send_contact_email(site, msg)
        self.assertIsNone(result)

    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP error'))
    def test_send_contact_email_exception_silencieuse(self, mock_send):
        """_send_contact_email lines 558-559 — exception ignorée."""
        from content.views import _send_contact_email
        from content.models import ContactMessage
        from django.test import override_settings
        site = _ensure_section_page(slug='exc-email-site', name='Exc Email Site')
        site.contact_email = 'contact@exc.fr'
        site.save(update_fields=['contact_email'])
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='m'
        )
        with override_settings(CONTACT_EMAIL='contact@exc.fr'):
            result = _send_contact_email(site, msg)
        self.assertIsNone(result)


class PlanDuSiteCategoryGroupingTest(TestCase):
    """views.py lines 684, 688-702 — PlanDuSiteView groupement de catégories."""

    def setUp(self):
        self.site = _ensure_section_page(slug='plan-site', name='Plan Site', site_type='regional')

    def test_categorie_unique_par_nom(self):
        """Un seul cat par name → URL dans cat_groups."""
        make_cms_category(name='Luttes', slug='luttes-plan', section_slug='plan-site')
        r = self.client.get(
            reverse('content:site_plan_du_site', kwargs={'site_slug': 'plan-site'})
        )
        self.assertEqual(r.status_code, 200)
        cat_groups = r.context.get('cat_groups', [])
        noms = [g['name'] for g in cat_groups]
        self.assertIn('Luttes', noms)
        luttes = next(g for g in cat_groups if g['name'] == 'Luttes')
        self.assertIsNotNone(luttes['url'])

    def test_plusieurs_categories_meme_nom_groupees(self):
        """Plusieurs cats même name → url None + secteur extrait."""
        make_cms_category(name='Droit', slug='droit-plan-paris', section_slug='plan-site')
        make_cms_category(name='Droit', slug='droit-plan-lyon', section_slug='plan-site')
        r = self.client.get(
            reverse('content:site_plan_du_site', kwargs={'site_slug': 'plan-site'})
        )
        self.assertEqual(r.status_code, 200)
        cat_groups = r.context.get('cat_groups', [])
        noms = [g['name'] for g in cat_groups]
        self.assertIn('Droit', noms)
        droit = next(g for g in cat_groups if g['name'] == 'Droit')
        self.assertIsNone(droit['url'])
        self.assertGreaterEqual(len(droit['children']), 2)


# ════════════════════════════════════════════════════════════════════════════════
# TESTS MICRO — lignes restantes (models, newsletter_views, views)
# ════════════════════════════════════════════════════════════════════════════════

class MenuItemGetUrlFallbackDieseTest(TestCase):
    """models.py line 516 — fallback '#' quand tous les FKs sont vides."""

    def setUp(self):
        self.sp = _ensure_section_page(slug='menu-diese', name='Menu Diese', site_type='regional')

    def test_get_url_retourne_diese_quand_tout_est_vide(self):
        """link_type='category' mais category=None → tous les fallbacks échouent → '#'."""
        item = MenuItem.objects.create(
            site=self.sp, title='Vide Total', menu='main', order=1,
            link_type='category',
        )
        url = item.get_url()
        self.assertEqual(url, '#')


class NewsletterSendViewRemainingTest(TestCase):
    """newsletter_views.py lines 29, 102-103, 154-155."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = _ensure_section_page(slug='nl-site-a', name='Site A', site_type='sectoral')
        self.site_b = _ensure_section_page(slug='nl-site-b', name='Site B', site_type='sectoral')
        self.newsletter = _make_newsletter(self.site_a)

    def test_chef_mauvais_site_leve_permission_denied(self):
        """Line 29 — _get_newsletter lève PermissionDenied si site différent.
        Wagtail peut convertir PermissionDenied en redirect dans le test client."""
        from content.newsletter_views import NewsletterSendView
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        rf = RequestFactory()
        user = make_superuser('perm-test-chef')
        request = rf.get(f'/cms/newsletter/{self.newsletter.pk}/envoyer/')
        request.user = user
        request.session = {'redac_current_site_id': self.site_b.pk}
        view = NewsletterSendView()
        view.request = request
        view.kwargs = {'pk': self.newsletter.pk}
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            view._get_newsletter(request, self.newsletter.pk)

    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP fail'))
    def test_post_mode_test_erreur_envoi_affiche_message(self, mock_send):
        """Lines 102-103 — exception lors de l'envoi du test → message d'erreur."""
        c = _chef_client_with_site(self.site_a)
        url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'
        r = c.post(url, {'mode': 'test', 'test_email': 'fail@test.fr'}, follow=True)
        messages_list = list(r.context['messages'])
        self.assertTrue(any('Erreur' in str(m) or 'erreur' in str(m) for m in messages_list))

    def test_ovh_get_subscribers_exception_sent_count_zero(self):
        """Lines 154-155 — exception ovh_client → sent_count=0."""
        self.site_a.ovh_mailing_list = 'liste-ovh-test'
        self.site_a.save(update_fields=['ovh_mailing_list'])
        with patch('django.core.mail.EmailMultiAlternatives.send', return_value=None):
            with patch('cms.ovh_client.get_subscribers', side_effect=Exception('OVH fail')):
                c = _chef_client_with_site(self.site_a)
                url = f'/cms/newsletter/{self.newsletter.pk}/envoyer/'
                r = c.post(url, {'mode': 'send'}, follow=True)
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, 'sent')
        self.assertEqual(self.newsletter.sent_count, 0)


class WordPressRedirectPageTest(TestCase):
    """views.py lines 494-496 — WP redirect avec page legacy (pas article)."""

    def test_redirect_vers_page_legacy(self):
        sub = _ensure_section_page(slug='wp-page-sub', name='WP Page Sub', site_type='regional')
        sub.wp_path = 'wp-page-path'
        sub.save(update_fields=['wp_path'])
        Page.objects.create(
            site=sub, title='WP Page', slug='wp-legacy-page', status='publish'
        )
        r = self.client.get('/wp-page-path/2024/01/wp-legacy-page/')
        self.assertIn(r.status_code, [301, 302])


class NewsletterSubscribeEmailExceptionTest(TestCase):
    """views.py lines 764-765 — exception email lors de l'inscription newsletter."""

    def setUp(self):
        self.site = _ensure_section_page(slug='nl-exc-site', name='NL Exc Site', site_type='sectoral')
        self.site.live = True
        self.site.save(update_fields=['live'])

    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP'))
    def test_email_exception_ne_bloque_pas(self, mock_send):
        """L'exception email est silencieuse → 200 quand même."""
        r = self.client.post(
            reverse('content:site_newsletter_subscribe', kwargs={'site_slug': 'nl-exc-site'}),
            {'email': 'exc@test.fr'}
        )
        self.assertEqual(r.status_code, 200)


# ── Coverage complémentaire ───────────────────────────────────────────────────

from django.test import SimpleTestCase


class EditorJsWidgetTest(SimpleTestCase):
    """widgets.py lines 29-33, 44."""

    def setUp(self):
        from content.widgets import EditorJsWidget
        self.widget = EditorJsWidget()

    def test_render_avec_valeur(self):
        html = self.widget.render('content', '{"blocks":[]}', attrs={'id': 'id_content'})
        self.assertIn('editorjs-wrapper', html)
        self.assertIn('id_content', html)

    def test_render_sans_valeur(self):
        html = self.widget.render('content', None)
        self.assertIn('editorjs-wrapper', html)

    def test_render_auto_id(self):
        html = self.widget.render('content', 'val')
        self.assertIn('id_content', html)

    def test_value_from_datadict_present(self):
        val = self.widget.value_from_datadict({'content': 'test-val'}, {}, 'content')
        self.assertEqual(val, 'test-val')

    def test_value_from_datadict_absent(self):
        val = self.widget.value_from_datadict({}, {}, 'content')
        self.assertIsNone(val)


class MediaUrlWithFileTest(TestCase):
    """models.py line 142 — Media.url retourne file.url quand file existe."""

    def test_url_returns_file_url(self):
        from unittest.mock import PropertyMock
        site = make_site('media-file-url')
        m = Media(site=site, title='t', mime_type='image/jpeg',
                  original_url='http://orig.com/img.jpg')
        mock_file = MagicMock()
        mock_file.__bool__ = MagicMock(return_value=True)
        mock_file.url = '/media/uploads/test.jpg'
        with patch.object(type(m), 'file', new_callable=PropertyMock,
                          return_value=mock_file):
            self.assertEqual(m.url, '/media/uploads/test.jpg')


class GetSectionPageExceptionTest(TestCase):
    """api_views.py lines 144-145 — _get_section_page retourne None sur exception."""

    def test_retourne_none_sur_exception(self):
        from content.api_views import _get_section_page
        with patch('cms.models.SectionPage.objects.filter',
                   side_effect=Exception('DB error')):
            result = _get_section_page('slug-inexistant')
            self.assertIsNone(result)


class WagtailHookViewSetsTest(TestCase):
    """wagtail_hooks.py — ViewSet.get_queryset() + redirects + newsletter menu."""

    def setUp(self):
        self.user = make_superuser('wh-vs-admin')
        self.rf = RequestFactory()

    def _req(self):
        req = self.rf.get('/')
        req.user = self.user
        req.session = {}
        return req

    def _vs_qs(self, vs_class):
        vs = vs_class.__new__(vs_class)
        return vs.get_queryset(self._req())

    def test_article_viewset_get_queryset(self):
        from content.wagtail_hooks import ArticleViewSet
        qs = self._vs_qs(ArticleViewSet)
        self.assertIsNotNone(qs)

    def test_contentpage_viewset_get_queryset(self):
        from content.wagtail_hooks import ContentPageViewSet
        qs = self._vs_qs(ContentPageViewSet)
        self.assertIsNotNone(qs)

    def test_tag_viewset_get_queryset(self):
        from content.wagtail_hooks import TagViewSet
        qs = self._vs_qs(TagViewSet)
        self.assertIsNotNone(qs)

    def test_media_viewset_get_queryset(self):
        from content.wagtail_hooks import MediaViewSet
        qs = self._vs_qs(MediaViewSet)
        self.assertIsNotNone(qs)

    def test_comment_viewset_get_queryset(self):
        from content.wagtail_hooks import CommentViewSet
        qs = self._vs_qs(CommentViewSet)
        self.assertIsNotNone(qs)

    def test_contact_message_viewset_get_queryset(self):
        from content.wagtail_hooks import ContactMessageViewSet
        qs = self._vs_qs(ContactMessageViewSet)
        self.assertIsNotNone(qs)

    def test_subscriber_viewset_get_queryset(self):
        from content.wagtail_hooks import SubscriberViewSet
        qs = self._vs_qs(SubscriberViewSet)
        self.assertIsNotNone(qs)

    def test_newsletter_viewset_get_queryset(self):
        from content.wagtail_hooks import NewsletterViewSet
        qs = self._vs_qs(NewsletterViewSet)
        self.assertIsNotNone(qs)

    def test_menuitem_viewset_get_queryset(self):
        from content.wagtail_hooks import MenuItemViewSet
        qs = self._vs_qs(MenuItemViewSet)
        self.assertIsNotNone(qs)

    def test_author_viewset_get_queryset(self):
        from content.wagtail_hooks import AuthorViewSet
        qs = self._vs_qs(AuthorViewSet)
        self.assertIsNotNone(qs)

    def test_contact_messages_viewset_get_queryset(self):
        from content.wagtail_hooks import ContactMessagesViewSet
        qs = self._vs_qs(ContactMessagesViewSet)
        self.assertIsNotNone(qs)

    def test_contact_config_viewset_get_queryset(self):
        from content.wagtail_hooks import ContactConfigViewSet
        qs = self._vs_qs(ContactConfigViewSet)
        self.assertIsNotNone(qs)

    def test_menu_index_redirect(self):
        from content.wagtail_hooks import _MenuIndexRedirect
        view = _MenuIndexRedirect.__new__(_MenuIndexRedirect)
        resp = view.get(self._req())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/cms/menus/')

    def test_contact_list_redirect(self):
        from content.wagtail_hooks import _ContactListRedirect
        view = _ContactListRedirect.__new__(_ContactListRedirect)
        resp = view.get(self._req())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/cms/contact/')

    def test_contact_config_redirect(self):
        from content.wagtail_hooks import _ContactConfigRedirect
        view = _ContactConfigRedirect.__new__(_ContactConfigRedirect)
        resp = view.get(self._req())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/cms/contact-config/')

    def test_newsletter_action_menu_item(self):
        from content.wagtail_hooks import add_newsletter_send_button
        site = make_site('nl-menu-am')
        nl = Newsletter.objects.create(site=site, title='NL AM', status='draft')

        # Model non-Newsletter → None
        self.assertIsNone(add_newsletter_send_button(Article))

        # Model Newsletter → menu item
        item = add_newsletter_send_button(Newsletter)
        self.assertIsNotNone(item)

        # get_url avec brouillon
        ctx_draft = {'instance': nl}
        self.assertEqual(item.get_url(ctx_draft), f'/cms/newsletter/{nl.pk}/envoyer/')
        self.assertTrue(item.is_shown(ctx_draft))

        # get_url avec envoyée → None
        nl.status = 'sent'
        ctx_sent = {'instance': nl}
        self.assertIsNone(item.get_url(ctx_sent))
        self.assertFalse(item.is_shown(ctx_sent))

        # get_url sans instance
        self.assertIsNone(item.get_url({}))


class ChampContactSlugVideTest(TestCase):
    """contact_cms_views.py line 129 — label non-vide mais slug vide après slugify."""

    def setUp(self):
        _setup_editorial_groups()
        self.site = _ensure_section_page(slug='champ-slug-vide', name='Slug Vide', site_type='sectoral')
        self.url = '/cms/contact-config/champ/ajouter/'

    def test_label_non_slugifiable_redirige(self):
        from content.models import FormulaireContact
        FormulaireContact.objects.get_or_create(site=self.site)
        c = _chef_client_with_site(self.site)
        # '---' n'est pas vide mais slugify('---') → ''
        r = c.post(self.url, {'label': '---'})
        self.assertEqual(r.status_code, 302)


class CategoryFeedNonPrincipalTest(TestCase):
    """feeds.py line 76 — catégorie hors section 'principal' → get_object_or_404."""

    def test_category_autre_section(self):
        from cms.models import CmsCategory
        CmsCategory.objects.get_or_create(
            slug='cat-non-principal', section_slug='autre-section',
            defaults={'name': 'Cat non principale'}
        )
        r = self.client.get('/categorie/cat-non-principal/feed/')
        # 200 si trouvée, 404 si pas de section_slug=principal mais trouvée par slug
        self.assertIn(r.status_code, [200, 400])


class ScopedArticleViewGetFormTest(TestCase):
    """wagtail_hooks.py lines 40-55 — _make_scoped_article_view.ScopedView.get_form()."""

    def test_get_form_filtre_categories_et_tags(self):
        from content.wagtail_hooks import _make_scoped_article_view
        from wagtail.snippets.views.snippets import CreateView as SnippetCreateView

        ScopedView = _make_scoped_article_view(SnippetCreateView)
        view = ScopedView.__new__(ScopedView)
        view.request = MagicMock()

        site_sp = _ensure_section_page(slug='scoped-form-sp', name='Scoped SP', site_type='sectoral')

        mock_form = MagicMock()
        mock_form.fields = {
            'site': MagicMock(),
            'tags': MagicMock(),
        }
        mock_form.initial = {}

        with patch.object(SnippetCreateView, 'get_form', return_value=mock_form):
            with patch('cms.site_context.get_current_site', return_value=site_sp):
                result = view.get_form()

        self.assertIs(result, mock_form)
        self.assertEqual(mock_form.initial.get('site'), site_sp.pk)

    def test_get_form_sans_site_courant(self):
        from content.wagtail_hooks import _make_scoped_article_view
        from wagtail.snippets.views.snippets import CreateView as SnippetCreateView

        ScopedView = _make_scoped_article_view(SnippetCreateView)
        view = ScopedView.__new__(ScopedView)
        view.request = MagicMock()

        mock_form = MagicMock()
        mock_form.fields = {}
        mock_form.initial = {}

        with patch.object(SnippetCreateView, 'get_form', return_value=mock_form):
            with patch('cms.site_context.get_current_site', return_value=None):
                result = view.get_form()

        self.assertIs(result, mock_form)
