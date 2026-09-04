import os
import re
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings
from django.http import Http404
from django.contrib.auth.models import User, Group, Permission
from django.urls import reverse
from django.utils import timezone

from wagtail.models import Page as WagtailPage
from taggit.models import Tag as TaggitTag

from content.models import (
    Author, Tag, Media, Article, Page,
    Comment, MenuItem, Subscriber, Newsletter, ExternalArticle, FicheSyndicat,
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
        # Comme en production : seule la confédération propose une newsletter.
        # Un test qui en veut une sur un syndicat la coche explicitement.
        newsletter_active=(slug == 'principal'),
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


def ajoute_a_la_newsletter(newsletter, article, rubrique='', order=None):
    """Range un article dans une rubrique de la lettre, en la créant au besoin.

    Depuis le 18/08/2026, la rubrique est un bloc qui porte ses articles : on
    ne la répète plus sur chaque ligne.
    """
    from content.models import NewsletterArticle, NewsletterRubrique
    bloc = newsletter.rubriques.filter(rubrique=rubrique).first()
    if bloc is None:
        bloc = NewsletterRubrique.objects.create(
            newsletter=newsletter, rubrique=rubrique,
            sort_order=newsletter.rubriques.count())
    if order is None:
        order = bloc.articles.count()
    return NewsletterArticle.objects.create(bloc=bloc, article=article, sort_order=order)


def make_article_page(section_slug='principal', title='Article test', slug=None,
                      live=True, categories=None, **kwargs):
    parent = _get_article_parent()
    slug = slug or title.lower().replace(' ', '-')
    art = parent.add_child(instance=ArticlePage(
        title=title, slug=slug,
        section_slug=section_slug,
        live=live,
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
        # Wagtail ne set pas first_published_at via add_child en test — on le force.
        # `publication_date` est remis à None dans le même UPDATE : depuis le
        # 15/08/2026, `save()` date tout article mis en ligne, et le repli ne
        # peut plus se produire par une simple création. Il reste la situation
        # des lignes héritées de l'import, que cette propriété sert toujours —
        # c'est bien elle qu'on veut couvrir ici.
        from cms.models import ArticlePage as AP
        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        AP.objects.filter(pk=art.pk).update(first_published_at=dt,
                                            publication_date=None)
        art.refresh_from_db()
        self.assertEqual(art.published_at, dt)

    def test_published_at_is_none_when_no_dates(self):
        art = make_article_page(section_slug='principal', title='Nodates', slug='nodates')
        art.publication_date = None
        art.first_published_at = None
        self.assertIsNone(art.published_at)

    def test_get_absolute_url_principal(self):
        """Absolue : le contenu confédéral s'affiche aussi sur les domaines de
        fédération (carrousel, étiquettes de catégorie), où une adresse
        relative viserait le mauvais hôte — 7 liens morts au crawl du
        05/08/2026. Même règle que les sections à domaine."""
        from django.conf import settings
        art = make_article_page(section_slug='principal', title='Art URL', slug='art-url')
        chemin = reverse('content:article_detail', kwargs={'slug': 'art-url'})
        self.assertEqual(art.get_absolute_url(),
                         f'{settings.MAIN_SITE_BASE_URL}{chemin}')

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
        """Absolue, pour la même raison que l'article : 31 articles de
        sous-site portent une catégorie confédérale, dont l'étiquette
        renvoyait vers l'hôte du sous-site."""
        from django.conf import settings
        cat = make_cms_category(name='Luttes', slug='luttes', section_slug='principal')
        chemin = reverse('content:category_detail', kwargs={'slug': 'luttes'})
        self.assertEqual(cat.get_absolute_url(),
                         f'{settings.MAIN_SITE_BASE_URL}{chemin}')

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

    def test_all_latest_articles_exclut_la_confederation(self):
        """« Le réseau » donne la parole aux syndicats et fédérations. La conf
        tient déjà le carrousel, la sélection et les colonnes : l'y remettre
        repoussait les sous-sites hors des 9 places."""
        make_site('reseau-test', wp_blog_id=42, site_type='sectoral', name='Réseau Test')
        conf = [make_article_page(section_slug='principal', title=f'Art {i}', slug=f'art-{i}')
                for i in range(4)]
        sous_site = make_article_page(section_slug='reseau-test',
                                      title='Art fédé', slug='art-fede')
        response = self.client.get(reverse('content:home'))
        reseau = response.context['all_latest_articles']
        self.assertIn(sous_site, reseau)
        for art in conf:
            self.assertNotIn(art, reseau)

    def test_all_latest_articles_capped_at_9(self):
        make_site('reseau-test', wp_blog_id=42, site_type='sectoral', name='Réseau Test')
        for i in range(12):
            make_article_page(section_slug='reseau-test', title=f'Flux {i}', slug=f'flux-{i}')
        response = self.client.get(reverse('content:home'))
        self.assertEqual(len(response.context['all_latest_articles']), 9)

    def test_le_reseau_ne_laisse_pas_un_site_bavard_tout_rafler(self):
        """Un tour de table entre sites : une place chacun avant d'en donner
        une deuxième à quiconque. À prendre les 9 plus récents tels quels, le
        syndicat le plus actif occupait les 9 places et les autres
        n'apparaissaient nulle part sur l'accueil."""
        for blog_id, (slug, nom) in enumerate((('bavard', 'Le Bavard'),
                                               ('discret', 'Le Discret')), start=51):
            make_site(slug, wp_blog_id=blog_id, site_type='sectoral', name=nom)
        for i in range(15):
            make_article_page(section_slug='bavard', title=f'Bavard {i}', slug=f'bavard-{i}')
        discret = make_article_page(section_slug='discret',
                                    title='Discret 0', slug='discret-0')

        reseau = self.client.get(reverse('content:home')).context['all_latest_articles']

        self.assertIn(discret, reseau,
                      "le site discret doit avoir sa place malgré le bavard")
        bavards = [a for a in reseau if a.section_slug == 'bavard']
        self.assertEqual(len(bavards), 8,
                         "le bavard prend les places restantes, pas toutes")

    def test_le_reseau_remplit_les_places_meme_avec_un_seul_site(self):
        """Le tour de table ne doit pas laisser de trous : s'il n'y a qu'un
        site, il remplit les 9 places comme avant."""
        make_site('solo', wp_blog_id=77, site_type='sectoral', name='Solo')
        for i in range(12):
            make_article_page(section_slug='solo', title=f'Solo {i}', slug=f'solo-{i}')
        reseau = self.client.get(reverse('content:home')).context['all_latest_articles']
        self.assertEqual(len(reseau), 9)

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

    def test_un_article_hors_conf_est_renvoye_chez_son_syndicat(self):
        """L'adresse de la conf ne sert plus le contenu d'un syndicat.

        Elle le faisait — et par un `get_object_or_404` sur un champ non
        unique, qui rendait un **500** dès que deux syndicats partageaient le
        slug : 43 adresses dans ce cas en production (03/09/2026). Même
        correction que pour les catégories le 01/09 : on redirige vers le
        syndicat propriétaire.
        """
        make_site('other', wp_blog_id=2, site_type='regional', name='Other')
        art = make_article_page(section_slug='other', title='Other Art',
                                slug='other-art-fallback')
        url = reverse('content:article_detail', kwargs={'slug': 'other-art-fallback'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], art.get_absolute_url())


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

    def test_une_categorie_dun_autre_syndicat_est_renvoyee_chez_lui(self):
        """L'adresse de la conf servait la catégorie du voisin sous l'identité
        de la conf. Elle redirige désormais (01/09/2026)."""
        make_site('other', wp_blog_id=2, site_type='regional', name='Other')
        subcat = make_cms_category(name='SubOnly', slug='sub-only', section_slug='other')
        url = reverse('content:category_detail', kwargs={'slug': 'sub-only'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], subcat.get_absolute_url())


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
        from django.core.cache import caches
        # La limite par IP vit dans le cache, qui survit d'un test à l'autre :
        # tous nos clients de test partagent 127.0.0.1.
        caches['limites'].clear()
        self.site = make_site()
        self.url = reverse('content:newsletter_subscribe')

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_valid_email_creates_inactive_subscriber(self, _captcha):
        # L'inscription se fait à la deuxième étape : la première ne crée plus
        # rien, elle mène au captcha (cf. NewsletterAntiAbusTest).
        self.client.post(self.url, {'email': 'new@example.com', 'name': 'Test'})
        self.client.post(reverse('content:newsletter_subscribe_verify'),
                         {'email': 'new@example.com', 'name': 'Test',
                          'h-captcha-response': 'ok'})
        sub = Subscriber.objects.filter(site=self.site, email='new@example.com').first()
        self.assertIsNotNone(sub)
        self.assertFalse(sub.is_active)

    def test_invalid_email_does_not_create_subscriber(self):
        self.client.post(self.url, {'email': 'not-an-email', 'name': ''})
        self.assertFalse(Subscriber.objects.exists())

    def test_invalid_email_redirects(self):
        response = self.client.post(self.url, {'email': 'bad', 'name': ''})
        self.assertEqual(response.status_code, 302)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_resubscribe_with_already_inactive_returns_200(self, _captcha):
        Subscriber.objects.create(site=self.site, email='exists@example.com', is_active=False)
        response = self.client.post(reverse('content:newsletter_subscribe_verify'),
                                    {'email': 'exists@example.com',
                                     'h-captcha-response': 'ok'})
        self.assertEqual(response.status_code, 200)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_subscribe_already_active_subscriber_returns_200(self, _captcha):
        Subscriber.objects.create(site=self.site, email='active@example.com', is_active=True)
        response = self.client.post(reverse('content:newsletter_subscribe_verify'),
                                    {'email': 'active@example.com',
                                     'h-captcha-response': 'ok'})
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

    def test_le_cartouche_presse_ne_peut_pas_etre_vide(self):
        """Le gabarit portait deux marqueurs « À compléter » jamais remplis :
        la page invitait les journalistes à contacter un service presse sans
        donner ni téléphone ni e-mail (constaté le 16/08/2026). À défaut de
        page rédigée, on retombe sur l'adresse de contact du site."""
        self.site.contact_email = 'presse@exemple.org'
        self.site.save(update_fields=['contact_email'])
        html = self.client.get(reverse('content:espace_presse')).content.decode()
        self.assertIn('presse@exemple.org', html)
        self.assertNotIn('À compléter', html)

    def test_le_texte_de_l_espace_presse_est_editable_depuis_le_cms(self):
        """Le chapô vivait dans le gabarit, hors de portée des rédacteurs. Il
        vient maintenant de la page statique « espace-presse »."""
        from wagtail.rich_text import RichText
        page = make_content_page(section_slug='principal',
                                 title='Espace Presse', slug='espace-presse')
        page.body = [('rich_text', RichText('<p>Contactez Camille au 01 02 03.</p>'))]
        page.save()

        html = self.client.get(reverse('content:espace_presse')).content.decode()
        self.assertIn('Contactez Camille au 01 02 03.', html)


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

    def test_location_rend_un_chemin_et_non_une_url_absolue(self):
        """Ce test exigeait l'inverse — `location() == get_absolute_url()` — et
        figeait ainsi le défaut : Django préfixe `location()` par
        `protocole://hôte`, si bien qu'une URL absolue en sortait doublée.
        83 % du sitemap de production était dans ce cas le 27/08/2026."""
        from content.sitemaps import ArticleSitemap
        chemin = ArticleSitemap().location(self.art)
        self.assertTrue(chemin.startswith('/'),
                        f"chemin nu attendu, reçu : {chemin!r}")
        self.assertNotIn('://', chemin)
        self.assertTrue(chemin.endswith(f'/article/{self.art.slug}/'),
                        f"le chemin doit mener à l'article : {chemin!r}")

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

    def test_redacteur_has_cms_articlepage_perms(self):
        # NB : cette commande est un reliquat, elle pose un jeu de droits plus
        # étroit que create_editorial_groups (post_migrate) et n'ôte jamais
        # rien. On ne vérifie donc que ce qu'elle ajoute.
        from django.core.management import call_command
        from io import StringIO
        call_command('setup_wagtail_permissions', stdout=StringIO())
        group = Group.objects.get(name='redacteur')
        self.assertTrue(group.permissions.filter(codename='add_articlepage').exists())
        self.assertTrue(group.permissions.filter(codename='change_articlepage').exists())

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

    def test_redacteur_can_delete_articlepage(self):
        self.assertTrue(self.redacteur.has_perm('cms.delete_articlepage'))

    def test_redacteur_manages_categories_deletion_included(self):
        # Autonomie complète sur son syndicat (décision du 02/08/2026).
        self.assertTrue(self.redacteur.has_perm('cms.add_cmscategory'))
        self.assertTrue(self.redacteur.has_perm('cms.change_cmscategory'))
        self.assertTrue(self.redacteur.has_perm('cms.delete_cmscategory'))

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
        # La suppression est bornée par la collection du syndicat, pas ici.
        self.assertTrue(self.redacteur.has_perm('wagtailimages.delete_image'))

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

    def test_chef_sans_session_est_cadre_sur_la_conf(self):
        """Sans choix en session, un chef confédéral voit la confédération.

        Il voyait auparavant les quatorze syndicats mêlés, dans un état que
        l'interface signalait elle-même « ⚠️ Aucun sélectionné » et où aucun
        bouton ne ramenait une fois qu'on en était sorti (31/08/2026).
        `site_a` est ici la page `principal`.
        """
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.chef)  # no session site
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertNotIn(self.art_b.pk, pks)

    def test_chef_with_session_sees_only_session_site(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.chef, session_site=self.site_a)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertNotIn(self.art_b.pk, pks)

    def test_sans_session_le_syndicat_courant_est_la_conf(self):
        """Le repli lui-même, et non son effet sur un queryset."""
        from cms.site_context import get_current_site
        for user in (self.chef, self.superuser):
            with self.subTest(user=user.username):
                courant = get_current_site(self._make_request(user))
                self.assertIsNotNone(courant)
                self.assertEqual(courant.slug, 'principal')

    def test_superuser_sans_session_est_cadre_sur_la_conf(self):
        from cms.site_context import scope_qs_slug
        from cms.models import ArticlePage
        request = self._make_request(self.superuser)
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.art_a.pk, pks)
        self.assertNotIn(self.art_b.pk, pks)

    def test_sans_page_principale_le_chef_voit_tout(self):
        """Repli : une base sans page `principal` retombe sur l'ancien
        comportement plutôt que de lever une exception ou de tout masquer."""
        from cms.site_context import scope_qs_slug, get_current_site
        from cms.models import ArticlePage, SectionPage
        SectionPage.objects.filter(slug='principal').delete()
        request = self._make_request(self.superuser)
        self.assertIsNone(get_current_site(request))
        qs = scope_qs_slug(ArticlePage.objects.all(), request, slug_field='section_slug')
        self.assertIn(self.art_b.pk, list(qs.values_list('pk', flat=True)))

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

    def test_redacteur_peut_supprimer_un_article_de_son_syndicat(self):
        """Autonomie complète depuis le 02/08/2026 ; le périmètre est borné
        par le cloisonnement, pas par la permission."""
        self.assertTrue(self.redacteur.has_perm('cms.delete_articlepage'))


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

    def test_redacteur_gere_son_syndicat_suppression_comprise(self):
        """Décision du 02/08/2026 : autonomie complète sur son syndicat.
        Ouvrable seulement parce que la suppression en masse est bornée et que
        tous les écrans par clé primaire refusent le contenu du voisin."""
        redacteur = make_redacteur(site=self.site_a)
        for perm in ['cms.delete_articlepage', 'cms.delete_contentpage',
                     'cms.delete_cmscategory', 'cms.delete_event',
                     'content.delete_menuitem', 'content.delete_newsletter',
                     'content.delete_subscriber', 'content.delete_comment',
                     'wagtailimages.delete_image', 'wagtaildocs.delete_document']:
            self.assertTrue(redacteur.has_perm(perm), f'manquante : {perm}')

    def test_redacteur_ne_peut_pas_supprimer_la_fiche_de_son_syndicat(self):
        """Seule exception à l'autonomie : supprimer la fiche détruirait le
        site entier du syndicat, toutes ses pages avec."""
        redacteur = make_redacteur(site=self.site_a)
        self.assertFalse(redacteur.has_perm('cms.delete_sectionpage'))

    def test_redacteur_modere_les_commentaires_de_ses_articles(self):
        redacteur = make_redacteur(site=self.site_a)
        self.assertTrue(redacteur.has_perm('content.view_comment'))
        self.assertTrue(redacteur.has_perm('content.change_comment'))

    def test_le_chef_peut_ouvrir_une_fiche_de_syndicat(self):
        """Il pouvait la publier sans pouvoir l'ouvrir : l'interface snippets
        s'appuie sur les permissions de modèle, pas sur les droits d'arbre."""
        chef = make_chef(site=self.site_a)
        for perm in ['cms.view_sectionpage', 'cms.change_sectionpage',
                     'cms.publish_sectionpage']:
            self.assertTrue(chef.has_perm(perm), f'manquante au chef : {perm}')

    def test_le_chef_gere_les_champs_du_formulaire_de_contact(self):
        chef = make_chef(site=self.site_a)
        for perm in ['content.add_champcontactcustom',
                     'content.change_champcontactcustom',
                     'content.delete_champcontactcustom',
                     'content.view_champcontactcustom']:
            self.assertTrue(chef.has_perm(perm), f'manquante au chef : {perm}')

    def test_redacteur_has_menu_perms(self):
        """Menus ouverts après sécurisation des vues Move/Reorder, suppression
        comprise depuis que la suppression en masse est bornée au syndicat."""
        redacteur = make_redacteur(site=self.site_a)
        for perm in ('add_menuitem', 'change_menuitem', 'delete_menuitem'):
            self.assertTrue(redacteur.has_perm(f'content.{perm}'))

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
        # Ce test porte sur le cloisonnement, pas sur l'arbitrage éditorial :
        # le syndicat doit donc proposer une newsletter pour qu'on puisse
        # vérifier que son rédacteur y accède.
        self.site_b.newsletter_active = True
        self.site_b.save(update_fields=['newsletter_active'])
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
        from cms.models import SectionPage
        call_command('setup_cms_permissions')
        u = User.objects.create_user('sec-redac2', password='pass')
        u.groups.add(Group.objects.get(name='redacteur_other'))
        u = User.objects.get(pk=u.pk)
        request = RequestFactory().get('/')
        request.user = u
        request.session = {}
        # Passer par le viewset enregistré : get_queryset lit désormais la
        # déclaration `cloisonnement` sur l'instance.
        qs = SectionPage.snippet_viewset.get_queryset(request)
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


class AssignMediaCollectionsTest(TestCase):
    """Ventilation des médias de Root vers les collections par syndicat
    (assign_media_collections) : un seul syndicat utilisateur → sa collection,
    plusieurs → « Commun », inutilisé → reste dans Root."""

    def setUp(self):
        _setup_editorial_groups()
        self.site_a = make_site(slug='principal', wp_blog_id=1)
        self.site_b = make_site(slug='other', wp_blog_id=2,
                                site_type='sectoral', name='Other')

    def _image(self, title, filename='test.png'):
        from wagtail.images.models import Image
        from wagtail.images.tests.utils import get_test_image_file
        return Image.objects.create(
            title=title, file=get_test_image_file(filename=filename))

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('assign_media_collections', *args, stdout=out)
        return out.getvalue()

    def test_single_section_usage_moves_to_section_collection(self):
        img = self._image('Visuel Other')
        make_article_page(section_slug='other', title='Art vent-o',
                          featured_image=img)
        self._run()
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Other')

    def test_multi_section_usage_goes_to_commun(self):
        img = self._image('Visuel partagé')
        make_article_page(section_slug='other', title='Art vent-m1',
                          featured_image=img)
        make_article_page(section_slug='principal', title='Art vent-m2',
                          featured_image=img)
        self._run()
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Commun')

    def test_unreferenced_stays_in_root(self):
        img = self._image('Visuel orphelin')
        out = self._run()
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Root')
        self.assertIn('restent dans Root', out)

    def test_dry_run_moves_nothing(self):
        img = self._image('Visuel dry')
        make_article_page(section_slug='other', title='Art vent-d',
                          featured_image=img)
        out = self._run('--dry-run')
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Root')
        self.assertIn('Dry-run', out)

    def test_url_embedded_in_legacy_content_counts(self):
        """Deuxième passe : un média cité par URL brute dans un contenu
        legacy WordPress (import Éducation…) est rattaché à ce syndicat,
        même sans référence structurée."""
        img = self._image('Visuel URL legacy', filename='vent-url-legacy.png')
        fname = img.file.name.rsplit('/', 1)[-1]
        make_article(self.site_b, title='Legacy vent',
                     content=f'<p><img src="/media/uploads/{fname}"></p>')
        self._run()
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Other')

    def test_section_page_logo_counts_for_its_section(self):
        img = self._image('Logo Other')
        self.site_b.logo = img
        self.site_b.save()
        self._run()
        img.refresh_from_db()
        self.assertEqual(img.collection.name, 'Other')


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

# `XSSContentTagsTest`, `RenderContentFilterTest` et `GalleryInvalidColumnsTest`
# ont disparu avec le code qu'ils couvraient : `_render_block`, `render_content`
# et `_safe_url`, retirés le 27/08/2026. Ils en étaient devenus les derniers
# appelants — aucun gabarit ne s'en servait plus. Leur objet, l'échappement du
# contenu legacy, n'a plus de sujet : les 1 701 articles et 63 pages hérités
# sont tous repris en Wagtail, dont les StreamField échappent d'eux-mêmes.


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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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

    @override_settings(NEWSLETTER_SEND_DELAY=18)
    @patch('content.newsletter_views.time.sleep')
    def test_lenvoi_direct_respecte_le_plafond_ovh(self, dormir):
        """OVH n'accepte qu'environ 200 courriels par heure : l'envoi direct
        marque une pause entre chacun. On compte les pauses plutôt que de les
        attendre."""
        self.site.ovh_mailing_list = ''
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
        Subscriber.objects.create(site=self.site, email='p1@example.com', is_active=True)
        Subscriber.objects.create(site=self.site, email='p2@example.com', is_active=True)
        _chef_client(self.site).post(self.url, {'mode': 'send'})
        self.assertEqual(dormir.call_count, 2)
        self.assertEqual(dormir.call_args[0][0], 18)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_send_sets_list_unsubscribe_header(self, mock_subs):
        # L'en-tête annonçait « <liste>-unsubscribe@ », convention Mailman non
        # vérifiée chez OVH ; il pointe désormais la page de désabonnement.
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        header = mail.outbox[0].extra_headers.get('List-Unsubscribe', '')
        self.assertIn('/newsletter/desabonnement/', header)
        self.assertTrue(header.startswith('<http'), header)

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

    @override_settings(NEWSLETTER_SEND_DELAY=0)
    def test_send_direct_fallback_when_no_ovh_list(self):
        """Sans liste OVH, l'envoi direct email-par-email est utilisé.

        Le délai est neutralisé : l'envoi direct respecte le plafond OVH de
        18 s entre deux courriels, et ce test dormait donc 36 secondes — à lui
        seul 12 % de la suite. Le plafond est vérifié par le test suivant, qui
        compte les pauses au lieu de les subir.
        """
        from django.core import mail
        self.site.ovh_mailing_list = ''
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
        self.newsletter = _make_newsletter(self.site)
        self.article = make_article_page(
            title='Un article Wagtail dans la newsletter', section_slug='nl-artpage')
        ajoute_a_la_newsletter(self.newsletter, self.article)
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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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
    def test_entete_desabonnement_pointe_la_page_de_sortie(self, mock_subs):
        """L'en-tête annonçait « <liste>-unsubscribe@ », une convention Mailman
        jamais vérifiée chez OVH. Un bouton « Se désabonner » qui échoue en
        silence renvoie le lecteur vers « indésirable » : on annonce désormais
        une page dont on sait qu'elle répond."""
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        headers = {m.extra_headers.get('List-Unsubscribe', '') for m in mail.outbox}
        self.assertEqual(headers, {'<http://testserver/nl-multi/newsletter/desabonnement/>'})
        for m in mail.outbox:
            self.assertIn('/nl-multi/newsletter/desabonnement/', m.body)

    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_le_pied_du_courriel_ne_mene_plus_a_une_erreur(self, mock_subs):
        """Il pointait vers /newsletter/inscription/, une vue en POST seul :
        le lien « Se désabonner » répondait 405 (constaté en production)."""
        from django.core import mail
        c = _chef_client(self.site)
        c.post(self.url, {'mode': 'send'})
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('/nl-multi/newsletter/desabonnement/', html)
        self.assertNotIn('/newsletter/inscription/', html)

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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])

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
    def test_webhook_adhesion_sans_cle_laisse_la_liste_intacte(self, mock_remove, mock_add):
        """Une clé absente ne vaut pas « désabonne ».

        cnt-adhesion pousse les préférences de l'adhérent à chaque
        encaissement. Tant qu'une clé absente valait « false », une sortie
        faite par le lien de désinscription tenait jusqu'au prélèvement
        suivant, puis l'adhérent était réinscrit sans rien demander.
        """
        import hashlib as _hashlib
        import hmac as _hmac
        import json as _json
        from django.test import override_settings

        principal = _ensure_section_page(slug='principal', name='CNT-SO')
        sorti = Subscriber.objects.create(
            site=None, email='sorti@example.org', is_active=False)

        body = _json.dumps({'email': 'sorti@example.org',
                            'newsletter_synd': False,
                            'syndicat_slug': 'principal'}).encode()
        with override_settings(ADHESION_WEBHOOK_SECRET='s3cret'):
            sig = _hmac.new(b's3cret', body, _hashlib.sha256).hexdigest()
            r = self.client.post('/api/newsletter/sync/', body,
                                 content_type='application/json',
                                 HTTP_X_WEBHOOK_SECRET=sig)

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['result']['conf'], 'inchangé')
        sorti.refresh_from_db()
        self.assertFalse(sorti.is_active)
        mock_add.assert_not_called()

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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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
import json as json_module

from django.test import override_settings


def _hmac_sig(secret, body_bytes):
    return hmac_module.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Webhook cnt-adhesion : synchronisation des abonnés newsletter
# ---------------------------------------------------------------------------

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
        self.site.newsletter_active = True   # ce test exerce l'envoi
        self.site.save(update_fields=['newsletter_active'])
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
        # Ces tests exercent l'envoi : le syndicat doit donc proposer une
        # newsletter, coupée par défaut depuis le 17/08/2026.
        self.site.newsletter_active = True
        self.site.save(update_fields=['ovh_mailing_list', 'newsletter_active'])
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

    def test_renvoie_vers_la_page_de_contact(self):
        # Le formulaire a quitté la page le 17/08/2026 : il doublonnait celui
        # de /<slug>/contact/, au champ et au captcha près.
        r = self.client.get(self.url)
        self.assertContains(r, '/rejoindre-site/contact/')

    def test_post_refuse_et_ne_cree_rien(self):
        from content.models import ContactMessage
        data = {
            'name': 'Alice', 'email': 'alice@test.fr',
            'subject': 'Test', 'message': 'Bonjour',
            'h-captcha-response': 'test-token',
        }
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 405)
        self.assertFalse(ContactMessage.objects.filter(email='alice@test.fr').exists())


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
                featured_on_conf=True
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
            with self.assertLogs('content.views', level='ERROR') as journal:
                result = _send_contact_email(site, msg)
        self.assertFalse(result)
        self.assertIn('SANS DESTINATAIRE', '\n'.join(journal.output))

    @patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception('SMTP error'))
    def test_send_contact_email_signale_lechec_sans_le_propager(self, mock_send):
        """Ce test s'appelait « exception silencieuse » et vérifiait que
        `_send_contact_email` ne renvoyait rien — écrit pour la couverture,
        docstring « exception ignorée » à l'appui. Il épinglait donc le défaut
        comme spécification : quiconque réparait le silence le voyait rougir.

        Ce qui compte vraiment tient en deux points, et les voici : l'échec ne
        remonte pas au visiteur — sa demande est enregistrée, lui répondre une
        500 serait faux — et il ne disparaît pas pour autant.
        """
        from content.views import _send_contact_email
        from content.models import ContactMessage
        site = _ensure_section_page(slug='exc-email-site', name='Exc Email Site')
        site.contact_email = 'contact@exc.fr'
        site.save(update_fields=['contact_email'])
        msg = ContactMessage.objects.create(
            site=site, name='Test', email='t@t.fr', message='m'
        )
        with self.assertLogs('content.views', level='ERROR') as journal:
            remis = _send_contact_email(site, msg)
        self.assertFalse(remis)
        self.assertIn('contact@exc.fr', '\n'.join(journal.output))


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
        for s_ in (self.site_a, self.site_b):   # ces tests exercent l'envoi
            s_.newsletter_active = True
            s_.save(update_fields=['newsletter_active'])
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

    def test_comment_viewset_get_queryset(self):
        from content.wagtail_hooks import CommentViewSet
        qs = self._vs_qs(CommentViewSet)
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


class CategorieDuVoisinSousLaConfTest(TestCase):
    """L'adresse `/categorie/<slug>/` de la conf ne sert que la conf.

    Relevé le 01/09/2026 dans les journaux nginx de production : sur
    **2618 requêtes** de catégorie, **1562 — 60 %** — rendaient la catégorie
    d'un autre syndicat sous l'identité de la confédération, `context['site']`
    prenant même la fiche du voisin. La plus demandée,
    `/categorie/service-a-la-personne/` (252 requêtes), servait l'Auvergne.

    Et sept slugs sont portés par deux syndicats : sur ceux-là,
    `get_object_or_404(CmsCategory, slug=slug)` levait
    `MultipleObjectsReturned`, donc un **500** sur le flux — vérifié en ligne
    sur cinq d'entre eux.
    """

    def setUp(self):
        self.conf = make_site(slug='principal')
        self.voisin = make_site('voisin', wp_blog_id=2, site_type='regional',
                                name='Voisin')

    def test_une_categorie_de_la_conf_est_servie_normalement(self):
        make_cms_category(name='Droit', slug='droit', section_slug='principal')
        r = self.client.get('/categorie/droit/')
        self.assertEqual(r.status_code, 200)

    def test_le_flux_dune_categorie_du_voisin_redirige_vers_son_site(self):
        cat = make_cms_category(name='Locales', slug='locales',
                                section_slug='voisin')
        r = self.client.get('/categorie/locales/feed/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'{cat.get_absolute_url()}feed/')

    def test_un_slug_porte_par_deux_syndicats_ne_leve_plus_500(self):
        """C'était une erreur serveur en production, pas une hypothèse."""
        autre = make_site('autre', wp_blog_id=3, site_type='regional',
                          name='Autre')
        make_cms_category(name='Luttes', slug='luttes', section_slug='voisin')
        make_cms_category(name='Luttes', slug='luttes', section_slug='autre')
        for url in ('/categorie/luttes/', '/categorie/luttes/feed/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_le_syndicat_le_mieux_fourni_est_choisi(self):
        """Sans tri, `.first()` rendait un résultat au hasard de la base : la
        même adresse pouvait mener à deux syndicats différents."""
        make_site('autre', wp_blog_id=3, site_type='regional', name='Autre')
        maigre = make_cms_category(name='Luttes', slug='luttes',
                                   section_slug='autre')
        fournie = make_cms_category(name='Luttes', slug='luttes',
                                    section_slug='voisin')
        for i in range(3):
            # `categories=` et non `.add()` : sur un ParentalManyToManyField,
            # `.add()` ne touche la base qu'au `save()` de l'article.
            make_article_page(section_slug='voisin', title=f'L{i}',
                              slug=f'l-{i}', categories=[fournie])
        r = self.client.get('/categorie/luttes/')
        self.assertEqual(r['Location'], fournie.get_absolute_url())
        self.assertNotEqual(r['Location'], maigre.get_absolute_url())

    def test_un_syndicat_depublie_ne_sert_pas_de_destination(self):
        """Rediriger vers un site fermé mènerait à un 404 : autant le rendre
        tout de suite, et sur la bonne adresse."""
        ferme = _ensure_section_page(slug='ferme', name='Fermé', live=False)
        make_cms_category(name='Cachée', slug='cachee', section_slug='ferme')
        self.assertEqual(self.client.get('/categorie/cachee/').status_code, 404)
        self.assertEqual(
            self.client.get('/categorie/cachee/feed/').status_code, 404)

    def test_un_slug_inconnu_reste_un_404(self):
        self.assertEqual(self.client.get('/categorie/nexiste-pas/').status_code, 404)

    def test_le_flux_par_categorie_dun_syndicat_existe(self):
        """La redirection a besoin d'une destination : ce flux n'existait pas."""
        cat = make_cms_category(name='Locales', slug='locales',
                                section_slug='voisin')
        make_article_page(section_slug='voisin', title='Une locale',
                          slug='une-locale', categories=[cat])
        r = self.client.get('/voisin/categorie/locales/feed/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Une locale', r.content.decode())

    def test_ce_flux_se_ferme_avec_son_syndicat(self):
        ferme = _ensure_section_page(slug='ferme2', name='Fermé', live=False)
        make_cms_category(name='Cachée', slug='cachee2', section_slug='ferme2')
        self.assertEqual(
            self.client.get('/ferme2/categorie/cachee2/feed/').status_code, 404)


class LegacySiteSlugRoutingTest(TestCase):
    """Régression : un sous-site dont le legacy_site_slug diffère du slug.

    Sur un domaine autonome, SectionDomainMiddleware préfixe le chemin avec
    `legacy_site_slug`. Les vues qui résolvaient la section par `slug=` seul
    renvoyaient un 404 sur tout le sous-site sauf la home et le contact
    (cas constaté en prod le 31/07/2026 : Numérique, slug « numerique »,
    legacy « stnum » — 5 pages en 404 ; Éducation a le même écart).
    """

    def setUp(self):
        self.site = make_site(slug='numerique', name='CNT-SO Numérique',
                              site_type='sectoral')
        self.site.legacy_site_slug = 'stnum'
        self.site.save()

    def test_pages_du_sous_site_accessibles_par_le_slug_legacy(self):
        for chemin in ['agenda', 'rejoindre', 'ressources', 'plan-du-site',
                       'espace-presse', 'contact']:
            with self.subTest(chemin=chemin):
                r = self.client.get(f'/stnum/{chemin}/')
                self.assertEqual(
                    r.status_code, 200,
                    f"/stnum/{chemin}/ doit répondre malgré le slug hérité",
                )

    def test_pages_du_sous_site_accessibles_par_le_slug_wagtail(self):
        for chemin in ['agenda', 'rejoindre', 'ressources', 'plan-du-site',
                       'espace-presse', 'contact']:
            with self.subTest(chemin=chemin):
                r = self.client.get(f'/numerique/{chemin}/')
                self.assertEqual(r.status_code, 200)

    def test_slug_inconnu_reste_en_404(self):
        r = self.client.get('/syndicat-inexistant-xyz/agenda/')
        self.assertEqual(r.status_code, 404)

    def test_helper_resout_les_deux_slugs(self):
        from content.views import get_section_or_404
        self.assertEqual(get_section_or_404('stnum').pk, self.site.pk)
        self.assertEqual(get_section_or_404('numerique').pk, self.site.pk)
        with self.assertRaises(Http404):
            get_section_or_404('nawak-xyz')

    def test_le_contenu_du_syndicat_est_bien_affiche_via_le_slug_legacy(self):
        """Second volet du bug : les vues filtraient les contenus sur le slug
        brut de l'URL (« stnum »), alors que les contenus portent le slug
        Wagtail (« numerique ») — les pages répondaient mais restaient vides."""
        cat = make_cms_category(name='Outils', section_slug='numerique')
        make_article_page(section_slug='numerique', title='Guide autodefense',
                          slug='guide-autodefense', categories=[cat])

        r = self.client.get('/stnum/ressources/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Guide autodefense')
        self.assertContains(r, 'Outils')

        # « Nous rejoindre » n'affiche pas les catégories, mais les charge en
        # contexte (sidebar) : on vérifie la donnée, pas le rendu.
        r = self.client.get('/stnum/rejoindre/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(cat, r.context['categories'])

    def test_le_flux_rss_du_syndicat_n_est_pas_vide(self):
        """Le flux filtrait sur `legacy_site_slug or slug`, donc sur « stnum » :
        il ressortait vide alors que les articles portent « numerique ».
        Constaté en prod sur Numérique et Éducation (flux vides, homes pleines)."""
        make_article_page(section_slug='numerique', title='Depeche du syndicat',
                          slug='depeche-du-syndicat')
        for url in ('/stnum/feed/', '/numerique/feed/'):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'Depeche du syndicat')

    def test_le_nom_du_syndicat_remplace_stucs_dans_les_ressources(self):
        """Le template « générique » des ressources affichait STUCS en dur
        sur tous les sous-sites (constaté en prod sur les 7 domaines)."""
        r = self.client.get('/numerique/ressources/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'CNT-SO Numérique')
        self.assertNotContains(r, 'STUCS')


class MenuRequetesTest(TestCase):
    """Le menu est reconstruit à chaque page : il ne doit pas repartir en N+1.

    base.html descend à trois niveaux (item → enfant → petit-enfant). Le tag
    ne préchargeait qu'un niveau : chaque enfant déclenchait une requête, plus
    une par catégorie liée pour bâtir son URL — 62 requêtes sur la home d'un
    sous-site, ramenées à 18 (audit du 31/07/2026).
    """

    PLAFOND = 30

    def setUp(self):
        self.site = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        cat = make_cms_category(name='Luttes', slug='luttes', section_slug='13')
        # un menu à trois niveaux, comme en production
        for i in range(3):
            parent = MenuItem.objects.create(
                site=self.site, menu='main', title=f'Rubrique {i}',
                link_type='url', url='#', order=i, is_active=True)
            for j in range(3):
                enfant = MenuItem.objects.create(
                    site=self.site, menu='main', title=f'Sous {i}.{j}',
                    link_type='category', category=cat, parent=parent,
                    order=j, is_active=True)
                MenuItem.objects.create(
                    site=self.site, menu='main', title=f'Petit {i}.{j}',
                    link_type='category', category=cat, parent=enfant,
                    order=0, is_active=True)

    def test_la_home_de_sous_site_ne_part_pas_en_n_plus_un(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get('/13/')
        self.assertEqual(r.status_code, 200)
        self.assertLess(
            len(ctx.captured_queries), self.PLAFOND,
            f"{len(ctx.captured_queries)} requêtes : le préchargement du menu "
            f"a probablement régressé")

    def test_les_trois_niveaux_de_menu_sont_precharges(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from content.templatetags.menu_tags import get_menu

        items = get_menu(self.site, 'main')       # requêtes de préchargement ici
        with CaptureQueriesContext(connection) as ctx:
            for item in items:
                for enfant in item.children.all():
                    list(enfant.children.all())   # ne doit rien requêter de plus
        self.assertEqual(
            len(ctx.captured_queries), 0,
            "parcourir les trois niveaux ne doit déclencher aucune requête")


class AccessibiliteTest(TestCase):
    """Bases d'accessibilité vérifiées sur le HTML réellement servi
    (audit du 31/07/2026 : ni lien d'évitement, ni étiquette sur la recherche
    et la newsletter, et pas de repère <main> sur l'accueil)."""

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')

    def test_lien_d_evitement_present_et_cible_existante(self):
        r = self.client.get('/')
        self.assertContains(r, 'class="skip-link"')
        self.assertContains(r, 'href="#contenu"')
        self.assertContains(r, 'id="contenu"')

    def test_repere_main_sur_l_accueil(self):
        r = self.client.get('/')
        self.assertContains(r, '<main')

    def test_champ_de_recherche_etiquete(self):
        r = self.client.get('/')
        self.assertContains(r, 'aria-label="Rechercher sur le site"')

    def test_champ_newsletter_etiquete(self):
        html = self.client.get('/').content.decode()
        import re
        for champ in re.findall(r'<input[^>]*type="email"[^>]*>', html):
            self.assertIn('aria-label', champ,
                          "le champ e-mail de la newsletter doit être étiqueté")


class NavigationClavierTest(TestCase):
    """Audit du 01/08/2026, passe « navigation clavier et rendu ».

    Trois défauts constatés au navigateur : des liens focusables mais
    invisibles (cartouches de la manchette en opacité 0, diapositives inactives
    du carrousel), et des champs qui supprimaient le contour de focus sans rien
    mettre à la place."""

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')

    def test_un_filet_de_securite_garantit_un_focus_visible(self):
        html = self.client.get('/').content.decode()
        self.assertIn(':focus-visible', html,
                      "base.html doit poser un contour de focus par défaut")

    def test_aucun_champ_ne_supprime_le_contour_sans_remplacement(self):
        """`outline: none` n'est acceptable qu'accompagné d'un autre repère visuel."""
        import re
        html = self.client.get('/').content.decode()
        for bloc in re.finditer(r'([^{}]*):focus[^{}]*\{([^}]*)\}', html):
            selecteur, corps = bloc.group(1).strip()[-70:], bloc.group(2)
            if not re.search(r'outline:\s*(none|0)\b', corps):
                continue
            remplacement = re.search(r'border-color|box-shadow|background|outline:\s*\d', corps)
            self.assertTrue(
                remplacement,
                f"« {selecteur} » retire le contour de focus sans le remplacer")

    def test_le_titre_des_cartes_de_la_manchette_est_toujours_visible(self):
        """Le titre était masqué jusqu'au survol, posé sur l'affiche. Au doigt
        personne ne survole, et au clavier on tabulait sur un lien invisible :
        il fallait un `:focus-within` pour rattraper le coup. Le titre est
        maintenant sous l'affiche, affiché en permanence — plus de cartouche à
        révéler, donc plus de lien invisible possible."""
        import re
        html = self.client.get('/').content.decode()
        bloc = re.search(r'\.hp-mcard-body\s*\{([^}]*)\}', html)
        self.assertIsNotNone(bloc, "règle .hp-mcard-body introuvable")
        self.assertNotIn('opacity: 0', bloc.group(1),
                         "le titre des cartes ne doit pas dépendre du survol")

    def _accueil_avec_carrousel(self):
        """Deux articles à la une : le carrousel ne s'anime qu'au-delà d'un."""
        from cms.models import CarouselArticle
        for titre, slug in (('Une A', 'une-a'), ('Une B', 'une-b')):
            CarouselArticle.objects.create(
                page=self.site,
                article=make_article_page(section_slug='principal',
                                          title=titre, slug=slug))
        html = self.client.get('/').content.decode()
        self.assertIn('id="hp-carousel-track"', html,
                      "le carrousel devrait être rendu")
        return html

    def test_le_carrousel_ne_defile_pas_tout_seul(self):
        """WCAG 2.2.2 (niveau A) : tout contenu qui défile seul au-delà de
        5 secondes doit pouvoir être arrêté. Le carrousel se passe de bouton
        pause parce qu'il ne bouge que sur clic — supprimer la minuterie sans
        remettre la pause rouvrirait le manquement."""
        html = self._accueil_avec_carrousel()
        self.assertNotIn('setInterval', html,
                         "le carrousel ne doit pas défiler de lui-même : sans "
                         "minuterie, aucun bouton pause n'est exigible")

    def test_le_carrousel_respecte_le_reglage_animations_reduites(self):
        html = self._accueil_avec_carrousel()
        self.assertIn('prefers-reduced-motion', html,
                      "le défilement automatique ne doit pas démarrer si "
                      "l'utilisateur a réduit les animations")

    def test_les_diapositives_inactives_sont_hors_de_l_ordre_de_tabulation(self):
        """Masquer par `opacity` ou `pointer-events` laisse les liens dans le
        parcours clavier : on tabule sur une diapositive invisible. `display:
        none` les en retire, et les retire aussi de l'arbre d'accessibilité."""
        import re
        html = self.client.get('/').content.decode()
        bloc = re.search(r'\.hp-carousel-slide\s*\{([^}]*)\}', html)
        self.assertIsNotNone(bloc, "règle .hp-carousel-slide introuvable")
        self.assertIn('display: none', bloc.group(1))


class HierarchieDesTitresTest(TestCase):
    """Aucun saut de niveau de titre dans les gabarits (WCAG 1.3.1).

    L'audit avait relevé h1 → h3 sur toutes les pages d'article
    (« Partager cet article » et « Articles similaires » en h3)."""

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')

    def _niveaux(self, html):
        import re
        return [int(m.group(1)) for m in re.finditer(r'<h([1-6])\b', html)]

    def _assert_sans_saut(self, html, ou):
        niveaux = self._niveaux(html)
        sauts = [(a, b) for a, b in zip(niveaux, niveaux[1:]) if b > a + 1]
        self.assertEqual(sauts, [], f"saut(s) de niveau de titre sur {ou} : {sauts}")

    def test_page_d_article_sans_saut_de_niveau(self):
        make_article_page(section_slug='principal', title='Grève au dépôt',
                          slug='greve-au-depot')
        r = self.client.get(reverse('content:article_detail',
                                    kwargs={'slug': 'greve-au-depot'}))
        self.assertEqual(r.status_code, 200)
        self._assert_sans_saut(r.content.decode(), "une page d'article")

    def test_accueil_sans_saut_de_niveau(self):
        r = self.client.get('/')
        self._assert_sans_saut(r.content.decode(), "l'accueil")


class AccueilHeriteDeWordPressTest(TestCase):
    """Un syndicat ayant gardé sa page « home » WordPress était servi par un
    gabarit HTML autonome : ni menu, ni pied de page CNT-SO, ni lien
    d'évitement, aucun h1, Tailwind chargé depuis un CDN externe — et un titre
    codé en dur au nom du syndicat du numérique, donc faux pour tout autre."""

    def setUp(self):
        self.site = make_site(slug='metallurgie', name='CNT-SO Métallurgie',
                              site_type='sectoral')
        Page.objects.create(
            site=self.site, title='Accueil', slug='home', status='publish',
            content='<h3>Le syndicat de la métallurgie</h3><p>Rejoignez-nous.</p>',
        )

    def test_la_page_garde_la_navigation_du_site(self):
        r = self.client.get('/metallurgie/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="skip-link"')
        self.assertContains(r, '<main')

    def test_la_page_a_un_titre_de_niveau_1(self):
        r = self.client.get('/metallurgie/')
        self.assertContains(r, '<h1')
        self.assertContains(r, 'CNT-SO Métallurgie')

    def test_le_contenu_herite_est_conserve(self):
        r = self.client.get('/metallurgie/')
        self.assertContains(r, 'Rejoignez-nous.')

    def test_aucun_nom_de_syndicat_code_en_dur(self):
        r = self.client.get('/metallurgie/')
        self.assertNotContains(r, 'métiers du numérique')

    def test_aucune_dependance_a_un_cdn_externe(self):
        r = self.client.get('/metallurgie/')
        self.assertNotContains(r, 'cdn.tailwindcss.com')


class SectionUrlTagTest(TestCase):
    """`section_url` doit rendre l'URL déjà canonique.

    `{% url %}` produisait toujours `/<slug>/…`, que le middleware redirige en
    301 quand la section a son propre domaine : 301 redirections rien que sur la
    page Ressources de Poitiers (audit du 01/08)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.site = _ensure_section_page(slug='tag-url', name='CNT-SO Tag',
                                         site_type='regional')

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def _url(self, route, **kwargs):
        from content.templatetags.content_tags import section_url
        return section_url(route, self.site, **kwargs)

    def _avec_domaine(self, domaine='tag.cnt-so.org'):
        from django.core.cache import cache
        self.site.custom_domain = domaine
        self.site.save(update_fields=['custom_domain'])
        cache.clear()

    def test_sans_domaine_l_url_reste_relative_et_prefixee(self):
        self.assertEqual(self._url('content:site_ressources'),
                         '/tag-url/ressources/')

    def test_avec_domaine_le_prefixe_de_section_disparait(self):
        self._avec_domaine()
        self.assertEqual(self._url('content:site_ressources'),
                         'https://tag.cnt-so.org/ressources/')

    def test_la_racine_du_sous_site_devient_la_racine_du_domaine(self):
        self._avec_domaine()
        self.assertEqual(self._url('content:site_home'), 'https://tag.cnt-so.org/')

    def test_les_arguments_nommes_sont_transmis(self):
        self._avec_domaine()
        self.assertEqual(self._url('content:site_category_detail', slug='banque-dimage'),
                         'https://tag.cnt-so.org/categorie/banque-dimage/')

    def test_une_route_inconnue_ne_casse_pas_la_page(self):
        self.assertEqual(self._url('content:route-qui-nexiste-pas'), '')

    def test_un_site_absent_ne_casse_pas_la_page(self):
        from content.templatetags.content_tags import section_url
        self.assertEqual(section_url('content:site_ressources', None), '')

    @override_settings(ALLOWED_HOSTS=['tag.cnt-so.org', 'testserver'])
    def test_la_page_ressources_ne_produit_plus_de_lien_a_rediriger(self):
        """Le vrai symptôme : plus aucun lien préfixé sur un domaine autonome.

        La page est demandée sur le domaine lui-même — sur l'hôte principal, le
        chemin préfixé est légitimement redirigé vers ce domaine."""
        import re
        make_article_page(section_slug='tag-url', title='Tract', slug='tract')
        self._avec_domaine()
        r = self.client.get('/ressources/', HTTP_HOST='tag.cnt-so.org')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        prefixes = [h for h in re.findall(r'href="([^"]+)"', html)
                    if h.startswith('/tag-url/')]
        self.assertEqual(prefixes, [],
                         f"liens encore préfixés, donc redirigés : {prefixes[:5]}")

    def test_une_url_de_menu_saisie_a_la_main_est_normalisee(self):
        """Un rédacteur tape `/tag-url/ressources/` : sur un domaine autonome
        c'est exactement la forme que le middleware redirige."""
        from content.models import MenuItem
        self._avec_domaine()
        item = MenuItem.objects.create(
            site=self.site, title='Ressources', link_type='url',
            url='/tag-url/ressources/?cat=greve', is_active=True)
        self.assertEqual(item.get_url(),
                         'https://tag.cnt-so.org/ressources/?cat=greve')

    def test_une_url_de_menu_externe_n_est_pas_touchee(self):
        from content.models import MenuItem
        self._avec_domaine()
        for saisie in ('https://cnt-so.org/international/', '/13/ressources/'):
            item = MenuItem.objects.create(
                site=self.site, title='Ailleurs', link_type='url',
                url=saisie, is_active=True)
            self.assertEqual(item.get_url(), saisie)

    def test_une_url_de_menu_reste_intacte_sans_domaine_autonome(self):
        from content.models import MenuItem
        item = MenuItem.objects.create(
            site=self.site, title='Ressources', link_type='url',
            url='/tag-url/ressources/', is_active=True)
        self.assertEqual(item.get_url(), '/tag-url/ressources/')

    @override_settings(ALLOWED_HOSTS=['tag.cnt-so.org', 'testserver'])
    def test_aucune_page_du_sous_site_ne_produit_de_lien_a_rediriger(self):
        """Balayage complet : le menu et les barres latérales sont sur toutes
        les pages, un seul lien préfixé y coûterait une redirection partout."""
        import re
        from content.models import MenuItem
        make_article_page(section_slug='tag-url', title='Tract', slug='tract')
        MenuItem.objects.create(site=self.site, title='Contact',
                                link_type='contact', is_active=True, order=1)
        MenuItem.objects.create(site=self.site, title='Agenda',
                                link_type='agenda', is_active=True, order=2)
        # URL tapée à la main par un rédacteur, comme sur STUCS en production
        MenuItem.objects.create(site=self.site, title='Ressources',
                                link_type='url', url='/tag-url/ressources/',
                                is_active=True, order=3)
        self._avec_domaine()

        fautifs, examinees = {}, []
        for chemin in ('/', '/ressources/', '/contact/', '/agenda/',
                       '/rejoindre/', '/plan-du-site/', '/espace-presse/',
                       '/article/tract/'):
            r = self.client.get(chemin, HTTP_HOST='tag.cnt-so.org')
            if r.status_code != 200:
                continue
            examinees.append(chemin)
            liens = [h for h in re.findall(r'href="([^"]+)"', r.content.decode())
                     if h.startswith('/tag-url/')]
            if liens:
                fautifs[chemin] = sorted(set(liens))[:4]
        # sans cette garde, un balayage qui ne verrait que des 404 passerait
        self.assertGreaterEqual(len(examinees), 6,
                                f"balayage trop maigre pour conclure : {examinees}")
        self.assertEqual(fautifs, {},
                         f"liens préfixés restants (une 301 par clic) : {fautifs}")


@override_settings(NEWSLETTER_SEND_DELAY=0)  # 18 s en production : bridage OVH
class ParcoursNewsletterCompletTest(TestCase):
    """Le parcours d'un abonné de bout en bout, jamais exercé jusqu'ici.

    Chaque étape était testée isolément, mais rien ne vérifiait que la chaîne
    tient : que le lien de confirmation reçu par e-mail fonctionne vraiment, et
    que le lien de désabonnement glissé dans la newsletter envoyée aussi."""

    def setUp(self):
        from django.core import mail
        from django.core.cache import caches
        caches['limites'].clear()  # la limite par IP est partagée entre tests
        self.site = _ensure_section_page(slug='parcours-nl', name='CNT-SO Parcours',
                                         site_type='sectoral')
        self.site.newsletter_active = True   # parcours complet : inscription → envoi
        self.site.save(update_fields=['newsletter_active'])
        self.article = make_article_page(section_slug='parcours-nl',
                                         title='Grève reconductible',
                                         slug='greve-reconductible')
        mail.outbox = []

    def _lien(self, corps, motif):
        import re
        m = re.search(r'https?://[^\s"\'<>]*(?:' + motif + r')[^\s"\'<>]*', corps)
        self.assertIsNotNone(m, f"lien « {motif} » absent de l'e-mail")
        return m.group(0)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_de_l_inscription_au_desabonnement(self, _captcha):
        from django.core import mail
        from content.models import Newsletter, NewsletterArticle

        # 1. inscription depuis le site public : le formulaire mène à la page
        #    de vérification, seule habilitée à inscrire (cf. NewsletterAntiAbusTest)
        r = self.client.post(
            reverse('content:site_newsletter_subscribe', args=['parcours-nl']),
            {'email': 'militante@example.org', 'name': 'Militante'})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            reverse('content:site_newsletter_subscribe_verify', args=['parcours-nl']),
            {'email': 'militante@example.org', 'name': 'Militante',
             'h-captcha-response': 'ok'})
        self.assertEqual(r.status_code, 200)
        abonnee = Subscriber.objects.get(email='militante@example.org')
        self.assertFalse(abonnee.is_active, "l'inscription doit rester à confirmer")

        # 2. l'e-mail de confirmation part, et son lien active bien le compte
        self.assertEqual(len(mail.outbox), 1)
        url_confirmation = self._lien(mail.outbox[0].body, 'confirm')
        self.client.get(url_confirmation.replace('http://testserver', ''))
        abonnee.refresh_from_db()
        self.assertTrue(abonnee.is_active)
        self.assertIsNotNone(abonnee.confirmed_at)

        # 3. la rédaction compose et envoie la newsletter
        mail.outbox = []
        newsletter = Newsletter.objects.create(
            site=self.site, title='Nouvelles du mois', intro='Au sommaire.',
            status='draft')
        ajoute_a_la_newsletter(newsletter, self.article)
        chef = _chef_client(self.site)
        chef.post(f'/cms/newsletter/{newsletter.pk}/envoyer/', {'mode': 'send'})

        # 4. l'abonnée reçoit un courrier complet
        self.assertEqual(len(mail.outbox), 1)
        envoi = mail.outbox[0]
        self.assertEqual(envoi.to, ['militante@example.org'])
        self.assertEqual(envoi.subject, 'Nouvelles du mois')
        self.assertIn('Grève reconductible', envoi.body)
        html = envoi.alternatives[0][0]
        self.assertIn('Grève reconductible', html)

        # 5. le lien de désabonnement du courrier reçu fonctionne
        url_desabo = self._lien(envoi.body, 'desabonnement|unsubscribe|desinscription')
        chemin = url_desabo.replace('http://testserver', '')
        self.assertEqual(self.client.get(chemin).status_code, 200)
        self.client.post(chemin)
        abonnee.refresh_from_db()
        self.assertFalse(abonnee.is_active, "le lien de l'e-mail doit désabonner")

        # 6. la newsletter est marquée envoyée et ne peut pas repartir
        newsletter.refresh_from_db()
        self.assertEqual(newsletter.status, 'sent')
        self.assertEqual(newsletter.sent_count, 1)
        mail.outbox = []
        chef.post(f'/cms/newsletter/{newsletter.pk}/envoyer/', {'mode': 'send'})
        self.assertEqual(len(mail.outbox), 0,
                         "une newsletter déjà envoyée ne doit pas repartir")

    def test_un_desabonne_ne_recoit_plus_rien(self):
        from django.core import mail
        from content.models import Newsletter
        Subscriber.objects.create(site=self.site, email='parti@example.org',
                                  is_active=False)
        Subscriber.objects.create(site=self.site, email='reste@example.org',
                                  is_active=True)
        newsletter = Newsletter.objects.create(site=self.site, title='Suite',
                                               intro='.', status='draft')
        mail.outbox = []
        _chef_client(self.site).post(f'/cms/newsletter/{newsletter.pk}/envoyer/',
                                     {'mode': 'send'})
        self.assertEqual([m.to[0] for m in mail.outbox], ['reste@example.org'])


class ContrasteCouleursTest(TestCase):
    """Les couleurs de texte de la charte doivent tenir le seuil WCAG AA (4,5:1
    sur blanc). Le rouge historique #EC1C24 était à 4,41 — juste en dessous —
    et servait aux liens dans le texte (audit du 01/08/2026)."""

    SEUIL_TEXTE = 4.5

    @staticmethod
    def _ratio_sur_blanc(hexa):
        def lin(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        h = hexa.lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
        return 1.05 / (luminance + 0.05)

    def test_le_rouge_de_charte_tient_le_seuil_aa(self):
        import re
        from pathlib import Path
        from django.conf import settings

        base = Path(settings.BASE_DIR) / 'templates' / 'base.html'
        m = re.search(r'--primary-color:\s*(#[0-9A-Fa-f]{6})', base.read_text(encoding='utf-8'))
        self.assertIsNotNone(m, "--primary-color introuvable dans base.html")
        ratio = self._ratio_sur_blanc(m.group(1))
        self.assertGreaterEqual(
            ratio, self.SEUIL_TEXTE,
            f"{m.group(1)} donne {ratio:.2f}:1 sur blanc — sous le seuil AA "
            f"pour le texte courant")

    def test_aucune_ancienne_teinte_rouge_ne_subsiste(self):
        from pathlib import Path
        from django.conf import settings

        anciennes = ('EC1C24', 'EC1A2E', 'E63946')
        fautifs = []
        for f in (Path(settings.BASE_DIR) / 'templates').rglob('*.html'):
            texte = f.read_text(encoding='utf-8', errors='ignore').upper()
            for teinte in anciennes:
                if f'#{teinte}' in texte:
                    fautifs.append(f"{f.name} → #{teinte}")
        self.assertEqual(fautifs, [],
                         "teintes rouges sous le seuil de contraste encore présentes")

    def test_la_reference_de_calcul_est_juste(self):
        # Repères connus : noir sur blanc = 21, blanc sur blanc = 1
        self.assertAlmostEqual(self._ratio_sur_blanc('#000000'), 21.0, places=1)
        self.assertAlmostEqual(self._ratio_sur_blanc('#FFFFFF'), 1.0, places=1)


class LienDeMenuSansCibleTest(TestCase):
    """Un lien dont la cible manque s'enregistrait sans broncher et menait vers
    '#'. La production comptait 8 entrées dans cet état, dont « CNT-SO national »
    au PREMIER NIVEAU du menu de quatre sous-sites — donc sur toutes leurs pages
    (audit du 05/08/2026).

    Deux causes distinctes, donc deux garde-fous : la création sans cible
    (`clean`) et le pourrissement ultérieur, les cibles étant en
    `on_delete=SET_NULL` — un lien valide se vide tout seul quand sa cible est
    supprimée, sans qu'aucun enregistrement ne repasse par `clean`.
    """

    def setUp(self):
        self.site = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        self.autre = make_site(slug='principal', name='CNT-SO confédération')

    # ── Garde-fou 1 : la création ────────────────────────────────────────────

    def test_lien_vers_un_site_sans_cible_refuse(self):
        from django.core.exceptions import ValidationError
        item = MenuItem(site=self.site, menu='main', title='CNT-SO national',
                        link_type='site')
        with self.assertRaises(ValidationError) as ctx:
            item.full_clean()
        self.assertIn('target_site', ctx.exception.message_dict)

    def test_lien_vers_un_site_avec_cible_accepte(self):
        item = MenuItem(site=self.site, menu='main', title='CNT-SO national',
                        link_type='site', target_site=self.autre)
        item.full_clean()   # ne doit pas lever

    def test_les_quatre_types_a_cible_sont_couverts(self):
        """Catégorie, site, article et page mènent tous à '#' sans cible."""
        from django.core.exceptions import ValidationError
        for type_lien, champ in MenuItem._CIBLE_REQUISE.items():
            with self.subTest(type_lien=type_lien):
                item = MenuItem(site=self.site, menu='main', title='X',
                                link_type=type_lien)
                with self.assertRaises(ValidationError) as ctx:
                    item.full_clean()
                self.assertIn(champ, ctx.exception.message_dict)

    def test_un_parent_de_sous_menu_sans_url_reste_permis(self):
        """Le '#' d'un parent est une convention, pas un défaut : il ouvre le
        sous-menu au lieu de naviguer."""
        item = MenuItem(site=self.site, menu='main', title='Ressources',
                        link_type='url', url='#')
        item.full_clean()   # ne doit pas lever

    # ── Garde-fou 2 : l'affichage, après pourrissement ───────────────────────

    def test_une_cible_supprimee_vide_le_lien_sans_validation(self):
        """Reproduit le pourrissement : SET_NULL agit hors de tout `clean`."""
        cat = make_cms_category(name='TPE', slug='tpe', section_slug='13')
        item = MenuItem.objects.create(site=self.site, menu='main', title='TPE',
                                       link_type='category', category=cat)
        cat.delete()
        item.refresh_from_db()
        self.assertIsNone(item.category)
        self.assertEqual(item.get_url(), '#')
        self.assertTrue(item.est_impasse)

    def test_un_parent_a_diese_n_est_pas_une_impasse(self):
        parent = MenuItem.objects.create(site=self.site, menu='main',
                                         title='Ressources', link_type='url',
                                         url='#')
        MenuItem.objects.create(site=self.site, menu='main', title='Guide',
                                link_type='url', url='/guide/', parent=parent)
        self.assertFalse(parent.est_impasse)

    def test_le_menu_n_affiche_pas_une_impasse(self):
        MenuItem.objects.create(site=self.site, menu='main',
                                title='Lien mort à ne pas afficher',
                                link_type='site', target_site=None)
        MenuItem.objects.create(site=self.site, menu='main',
                                title='Lien valide', link_type='url',
                                url='/valide/')
        html = self.client.get('/13/').content.decode()
        self.assertNotIn('Lien mort à ne pas afficher', html)
        self.assertIn('Lien valide', html)


class SitemapSectionExterneTest(TestCase):
    """Une section à `external_url` (syndicat hébergé ailleurs, comme le STAA
    sur staa-cnt-so.org) a un `get_absolute_url()` pointant vers un AUTRE
    domaine : la lister publierait l'URL d'autrui dans notre sitemap."""

    def test_le_sitemap_exclut_les_sections_externes(self):
        interne = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        externe = make_site(slug='staa', name='STAA', site_type='sectoral')
        externe.external_url = 'https://staa-cnt-so.org/'
        externe.save()

        from content.sitemaps import SiteSitemap
        items = list(SiteSitemap().items())
        self.assertIn(interne, items)
        self.assertNotIn(externe, items)

    def test_aucune_url_hors_domaine_dans_le_sitemap_rendu(self):
        externe = make_site(slug='staa', name='STAA', site_type='sectoral')
        externe.external_url = 'https://staa-cnt-so.org/'
        externe.save()
        corps = self.client.get('/sitemap.xml').content.decode()
        self.assertNotIn('staa-cnt-so.org', corps)


class CommentaireDeGabaritTest(TestCase):
    """`{# … #}` en Django ne vaut que sur UNE ligne.

    Étalé sur plusieurs lignes il n'est pas reconnu comme commentaire : le
    texte s'affiche en clair aux visiteurs. C'est arrivé le 05/08/2026 — un
    commentaire de trois lignes ajouté au menu de `base.html` s'est imprimé
    avant chaque entrée, sur toutes les pages du site, en production. La suite
    de tests était verte : rien ne regardait le HTML rendu de si près.
    """

    def test_aucun_commentaire_multiligne_dans_les_gabarits(self):
        from pathlib import Path
        racine = Path(__file__).resolve().parent.parent / 'templates'
        fautifs = []
        for chemin in racine.rglob('*.html'):
            for num, ligne in enumerate(chemin.read_text().splitlines(), start=1):
                if '{#' in ligne and '#}' not in ligne.split('{#', 1)[1]:
                    fautifs.append(f'{chemin.relative_to(racine)}:{num}')
        self.assertEqual(
            fautifs, [],
            "Commentaire {# #} sur plusieurs lignes : Django ne le reconnaît "
            f"pas et l'affiche aux visiteurs. Utiliser {{% comment %}} : {fautifs}")

    def test_le_menu_rendu_ne_contient_aucun_reste_de_gabarit(self):
        """Filet côté rendu : aucune page ne doit laisser fuir de syntaxe."""
        site = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        MenuItem.objects.create(site=site, menu='main', title='Actualités',
                                link_type='url', url='/actus/')
        html = self.client.get('/13/').content.decode()
        for reste in ('{#', '#}', '{%', '%}', '{{', '}}'):
            self.assertNotIn(reste, html,
                             f'{reste!r} laissé tel quel dans le HTML servi')


class PiedDePageRacinesSansEnfantTest(TestCase):
    """Le gabarit rendait toute racine du menu `footer` en titre de colonne.
    Quatre sous-sites affichaient donc « CNT-SO national », « Flux RSS »,
    « Plan du site » et « Contact » en en-têtes surmontant des listes vides —
    un pied de page entièrement creux (constaté en production le 05/08/2026).
    Ces entrées ont pourtant chacune une destination : ce sont des liens.
    """

    def setUp(self):
        self.site = make_site(slug='auvergne', name='CNT-SO Auvergne',
                              site_type='regional')

    def test_une_racine_sans_enfant_devient_un_lien(self):
        MenuItem.objects.create(site=self.site, menu='footer',
                                title='Plan du site', link_type='url',
                                url='/auvergne/plan-du-site/')
        html = self.client.get('/auvergne/').content.decode()
        self.assertIn('Plan du site', html)
        self.assertNotIn('<h3 class="footer-nav-title">Plan du site</h3>', html,
                         "rendu en titre de colonne au lieu d'un lien")

    def test_une_racine_avec_enfants_reste_une_colonne(self):
        col = MenuItem.objects.create(site=self.site, menu='footer',
                                      title='Ressources', link_type='url',
                                      url='#')
        MenuItem.objects.create(site=self.site, menu='footer', title='Guides',
                                link_type='url', url='/guides/', parent=col)
        html = self.client.get('/auvergne/').content.decode()
        self.assertIn('<h3 class="footer-nav-title">Ressources</h3>', html)

    def test_aucune_colonne_vide_n_est_rendue(self):
        """Une colonne dont tous les enfants sont désactivés reste creuse."""
        col = MenuItem.objects.create(site=self.site, menu='footer',
                                      title='Vide', link_type='url', url='#')
        MenuItem.objects.create(site=self.site, menu='footer', title='Caché',
                                link_type='url', url='/x/', parent=col,
                                is_active=False)
        html = self.client.get('/auvergne/').content.decode()
        self.assertNotIn('<h3 class="footer-nav-title">Vide</h3>', html)


class LienVersUnSiteDepuisUnDomaineTest(TestCase):
    """Une URL de section est relative au site principal. Servie depuis un
    domaine autonome, elle y boucle : « CNT-SO national » valait '/' et
    renvoyait à l'accueil de la fédération, pas à la confédération."""

    def setUp(self):
        self.principal = make_site(slug='principal', name='CNT-SO confédération')
        self.federation = make_site(slug='auvergne', name='CNT-SO Auvergne',
                                    site_type='regional')

    def test_depuis_un_domaine_autonome_le_lien_est_absolu(self):
        self.federation.custom_domain = 'auvergne.cnt-so.org'
        self.federation.save()
        item = MenuItem.objects.create(
            site=self.federation, menu='footer', title='CNT-SO national',
            link_type='site', target_site=self.principal)
        url = item.get_url()
        self.assertTrue(url.startswith('http'),
                        f'{url!r} : relative, elle boucle sur la fédération')
        self.assertNotIn('auvergne', url)

    def test_sans_domaine_autonome_le_lien_reste_relatif(self):
        item = MenuItem.objects.create(
            site=self.federation, menu='footer', title='CNT-SO national',
            link_type='site', target_site=self.principal)
        self.assertEqual(item.get_url(), '/')

    def test_une_cible_a_domaine_propre_reste_inchangee(self):
        self.federation.custom_domain = 'auvergne.cnt-so.org'
        self.federation.save()
        autre = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        autre.custom_domain = '13.cnt-so.org'
        autre.save()
        item = MenuItem.objects.create(
            site=self.federation, menu='footer', title='CNT-SO 13',
            link_type='site', target_site=autre)
        self.assertIn('13.cnt-so.org', item.get_url())


class LienPageParUrlTest(TestCase):
    """« /page/<slug>/ » est une route réelle qui redirige (301) vers l'URL
    canonique : le lien marche, mais coûte un aller-retour à chaque clic.
    Trois entrées du pied de page confédéral étaient dans ce cas (constat H de
    la passe 1, traité le 05/08/2026).

    Le remède n'est pas de réécrire l'URL mais de rattacher l'entrée à la page :
    le lien suivra alors un futur changement de slug.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO confédération')
        self.page = make_content_page(slug='syndicats', title='Nos syndicats',
                                      section_slug='principal')

    def _lancer(self, **kw):
        from django.core.management import call_command
        from io import StringIO
        call_command('fix_menus_morts', stdout=StringIO(), **kw)

    def test_le_lien_est_rattache_a_la_page(self):
        item = MenuItem.objects.create(
            site=self.site, menu='footer', title='Syndicats',
            link_type='url', url='/page/syndicats/')
        self._lancer()
        item.refresh_from_db()
        self.assertEqual(item.link_type, 'page')
        self.assertEqual(item.page_id, self.page.pk)
        self.assertEqual(item.get_url(), self.page.get_absolute_url())
        self.assertNotIn('/page/', item.get_url())

    def test_une_page_introuvable_est_laissee_intacte(self):
        item = MenuItem.objects.create(
            site=self.site, menu='footer', title='Fantôme',
            link_type='url', url='/page/nexiste-pas/')
        self._lancer()
        item.refresh_from_db()
        self.assertEqual(item.link_type, 'url')
        self.assertEqual(item.url, '/page/nexiste-pas/')

    def test_une_url_qui_n_est_pas_une_page_est_ignoree(self):
        item = MenuItem.objects.create(
            site=self.site, menu='footer', title='Article',
            link_type='url', url='/article/greve-2026/')
        self._lancer()
        item.refresh_from_db()
        self.assertEqual(item.url, '/article/greve-2026/')

    def test_la_commande_est_idempotente(self):
        item = MenuItem.objects.create(
            site=self.site, menu='footer', title='Syndicats',
            link_type='url', url='/page/syndicats/')
        self._lancer()
        self._lancer()
        item.refresh_from_db()
        self.assertEqual(item.page_id, self.page.pk)


class LienDeSectionSuitLaBasculeTest(TestCase):
    """Une entrée rattachée à sa section suit automatiquement l'activation
    d'un domaine autonome ; une URL manuscrite reste figée.

    C'est l'exigence posée par Arnaud le 05/08/2026 pour « Éducation &
    Recherche » : le lien devra mener à educ.cnt-so.org le jour où l'ancien
    WordPress sera retiré, sans qu'on ait à rouvrir le menu.
    """

    def setUp(self):
        self.principal = make_site(slug='principal', name='CNT-SO confédération')
        self.education = make_site(slug='education', name='CNT-SO Éducation',
                                   site_type='sectoral')

    def test_le_lien_rattache_suit_l_activation_du_domaine(self):
        item = MenuItem.objects.create(
            site=self.principal, menu='main', title='Éducation & Recherche',
            link_type='site', target_site=self.education)
        self.assertEqual(item.get_url(), '/education/')

        # Le jour de la bascule : on ne touche qu'à la fiche du syndicat.
        self.education.custom_domain = 'educ.cnt-so.org'
        self.education.save()
        item.refresh_from_db()
        self.assertEqual(item.get_url(), 'https://educ.cnt-so.org/')

    def test_une_url_manuscrite_reste_figee(self):
        """Contrôle : c'est bien le rattachement qui apporte la propriété."""
        item = MenuItem.objects.create(
            site=self.principal, menu='main', title='Éducation & Recherche',
            link_type='url', url='/education/')
        self.education.custom_domain = 'educ.cnt-so.org'
        self.education.save()
        item.refresh_from_db()
        self.assertEqual(item.get_url(), '/education/',
                         "une URL écrite à la main ne peut pas suivre")

    def test_la_commande_rattache_l_entree(self):
        from django.core.management import call_command
        from io import StringIO
        item = MenuItem.objects.create(
            site=self.principal, menu='main', title='Éducation & Recherche',
            link_type='site', target_site=None, url='/education/')
        call_command('fix_menus_morts', stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.target_site_id, self.education.pk)
        self.assertEqual(item.url, '', "l'URL manuscrite doit être effacée")
        self.assertEqual(item.get_url(), '/education/')


class BanqueImagesSidebarTest(TestCase):
    """Le bloc « Notre banque d'images » fabriquait son lien pour le site
    courant, en supposant que chaque syndicat a sa catégorie « banque-dimage ».
    Six sur neuf ne l'ont pas : le bloc menait à un 404 sur TOUTES leurs pages,
    barre latérale oblige (constaté en production le 05/08/2026)."""

    def setUp(self):
        self.principal = make_site(slug='principal', name='CNT-SO confédération')
        self.sous_site = make_site(slug='13', name='CNT-SO 13', site_type='regional')

    def _url(self, site):
        from content.templatetags.content_tags import banque_images_url
        return banque_images_url(site)

    @staticmethod
    def _conf_url():
        """Adresse attendue de la banque confédérale : absolue depuis
        `url_site_principal` — elle doit porter son hôte partout."""
        from django.conf import settings
        return f'{settings.MAIN_SITE_BASE_URL}/categorie/banque-dimage/'

    @staticmethod
    def _chemin(url):
        from urllib.parse import urlparse
        return urlparse(url).path or url

    def test_case_cochee_avec_categorie_pointe_vers_la_sienne(self):
        make_cms_category(name="Banque d'images", slug='banque-dimage',
                          section_slug='13')
        self.sous_site.banque_images_propre = True
        self.sous_site.save()
        self.assertIn('/13/', self._url(self.sous_site))

    def test_case_decochee_renvoie_a_la_confederation(self):
        """Même si le syndicat a sa propre catégorie : c'est la case qui
        décide, pas la présence de la donnée."""
        make_cms_category(name="Banque d'images", slug='banque-dimage',
                          section_slug='13')
        make_cms_category(name="Banque d'image", slug='banque-dimage',
                          section_slug='principal')
        self.sous_site.banque_images_propre = False
        self.sous_site.save()
        self.assertEqual(self._url(self.sous_site), self._conf_url())

    def test_case_cochee_sans_categorie_ne_fabrique_pas_un_404(self):
        """Le filet : une case qui ment ne doit pas recréer le bug d'origine."""
        make_cms_category(name="Banque d'image", slug='banque-dimage',
                          section_slug='principal')
        self.sous_site.banque_images_propre = True
        self.sous_site.save()
        url = self._url(self.sous_site)
        self.assertEqual(url, self._conf_url())
        self.assertNotEqual(self.client.get(self._chemin(url)).status_code, 404)

    def test_sans_categorie_propre_on_sert_celle_de_la_confederation(self):
        make_cms_category(name="Banque d'image", slug='banque-dimage',
                          section_slug='principal')
        url = self._url(self.sous_site)
        self.assertEqual(url, self._conf_url())

    def test_sur_un_domaine_autonome_le_repli_est_absolu(self):
        """Une URL relative retomberait sur le domaine du syndicat : 404."""
        make_cms_category(name="Banque d'image", slug='banque-dimage',
                          section_slug='principal')
        self.sous_site.custom_domain = '13.cnt-so.org'
        self.sous_site.save()
        url = self._url(self.sous_site)
        self.assertTrue(url.startswith('http'), f'{url!r} : relative')
        self.assertNotIn('13.cnt-so.org', url)

    def test_sans_categorie_nulle_part_le_bloc_disparait(self):
        self.assertEqual(self._url(self.sous_site), '')
        html = self.client.get('/13/').content.decode()
        self.assertNotIn('archives photographiques', html)
        self.assertNotIn('Voir la galerie', html)

    def test_le_bloc_rendu_ne_pointe_jamais_vers_un_404(self):
        """Balayage : pour chaque site, l'URL produite doit répondre."""
        from cms.models import SectionPage
        make_cms_category(name="Banque d'image", slug='banque-dimage',
                          section_slug='principal')
        for site in SectionPage.objects.filter(live=True):
            with self.subTest(site=site.slug):
                url = self._url(site)
                if not url:
                    continue
                self.assertNotEqual(
                    self.client.get(self._chemin(url)).status_code, 404,
                    f'{site.title} : {url} est une adresse morte')


class SouscriptionViewTest(TestCase):
    """La page de souscription remplace un article dont l'appel au don tenait
    dans un « cliquez ici » de la taille du texte courant, répété deux fois au
    fil de 3 000 signes — sur une page qui n'existe que pour recueillir des
    dons (relevé par Arnaud, 16/08/2026)."""

    def setUp(self):
        self.site = make_site()

    def test_la_page_repond(self):
        self.assertEqual(self.client.get(reverse('content:souscription')).status_code, 200)

    def test_le_lien_de_don_est_present(self):
        html = self.client.get(reverse('content:souscription')).content.decode()
        self.assertIn('we-solidaire.com', html)

    def test_l_url_nommee_ne_redirige_plus_vers_l_article(self):
        """`content:souscription` était une redirection vers l'article. Sept
        gabarits pointent sur ce nom : il doit servir la page, pas rebondir."""
        reponse = self.client.get(reverse('content:souscription'))
        self.assertEqual(reponse.status_code, 200,
                         "l'URL nommée doit servir la page directement")

    def test_aucun_lien_vers_l_ancien_wordpress(self):
        """Deux liens de l'article partaient sur cnt-so.org, qui sert encore
        l'ancien WordPress : le lecteur quittait le nouveau site sans le
        savoir. On vise ces deux cibles, pas la chaîne « cnt-so.org » — le
        gabarit de base l'emploie légitimement pour l'URL canonique."""
        html = self.client.get(reverse('content:souscription')).content.decode()
        for cible in ('cnt-so.org/orientations-du-6eme-congres',
                      'cnt-so.org/on-a-toujours-raison'):
            with self.subTest(cible=cible):
                self.assertNotIn(cible, html)

    def test_un_nom_de_fichier_devient_lisible(self):
        from content.views import _libelle_document
        self.assertEqual(_libelle_document('cntso_souscription_flyers.pdf'),
                         'Souscription flyers')

    def test_un_titre_deja_redige_est_respecte(self):
        """On habille les noms de fichiers, on ne réécrit pas le travail d'un
        rédacteur qui a saisi un vrai titre dans /cms/."""
        from content.views import _libelle_document
        self.assertEqual(_libelle_document('Tract à diffuser'), 'Tract à diffuser')


class SyndicatDepublieTest(TestCase):
    """Dépublier un syndicat doit fermer son site, pas seulement le masquer.

    Avant le 16/08/2026, `live=False` le retirait des menus et des listes, mais
    ses URL continuaient de servir : page d'accueil, contact, agenda, flux RSS
    et articles. Un site « désactivé » restait ouvert à quiconque avait
    l'adresse, un signet ou un résultat de moteur de recherche.
    """

    def setUp(self):
        make_site()  # la conf, dont dépendent les gabarits
        self.site = make_site('ferme', wp_blog_id=91, site_type='regional',
                              name='Syndicat Fermé')
        self.article = make_article_page(section_slug='ferme',
                                         title='Tract', slug='tract-ferme')

    URLS = ('/ferme/', '/ferme/contact/', '/ferme/agenda/', '/ferme/feed/',
            '/ferme/article/tract-ferme/')

    def _codes(self):
        return {u: self.client.get(u).status_code for u in self.URLS}

    def test_publie_tout_repond(self):
        """Contrôle positif : sans lui, un garde-fou qui fermerait tout,
        publié ou non, passerait le test suivant sans qu'on le voie."""
        for url, code in self._codes().items():
            with self.subTest(url=url):
                self.assertEqual(code, 200)

    def test_depublie_tout_est_ferme(self):
        self.site.live = False
        self.site.save(update_fields=['live'])
        for url, code in self._codes().items():
            with self.subTest(url=url):
                self.assertEqual(code, 404,
                                 f"{url} sert encore un syndicat dépublié")

    def test_les_articles_ne_survivent_pas_a_leur_syndicat(self):
        """Wagtail sert une page publiée sans regarder si son parent l'est :
        c'est par là que les articles restaient accessibles. On appelle donc
        `serve()` directement, le chemin que Wagtail emprunte."""
        from django.http import Http404
        from django.test import RequestFactory
        self.site.live = False
        self.site.save(update_fields=['live'])
        self.article.refresh_from_db()
        self.assertTrue(self.article.live, "l'article reste publié en base")
        with self.assertRaises(Http404):
            self.article.serve(RequestFactory().get('/ferme/tract-ferme/'))

    def test_un_article_de_la_conf_reste_servi(self):
        """Le garde-fou ne doit pas se déclencher sur le site confédéral,
        qui n'est pas un sous-site."""
        from django.test import RequestFactory
        art = make_article_page(section_slug='principal', title='Conf',
                                slug='art-conf-garde-fou')
        reponse = art.serve(RequestFactory().get('/article/art-conf-garde-fou/'))
        self.assertEqual(reponse.status_code, 200)

    def test_un_syndicat_voisin_reste_servi(self):
        """Le garde-fou ne doit fermer que le syndicat visé."""
        voisin = make_site('ouvert', wp_blog_id=92, site_type='regional',
                           name='Syndicat Ouvert')
        self.site.live = False
        self.site.save(update_fields=['live'])
        self.assertEqual(self.client.get('/ouvert/').status_code, 200)
        self.assertTrue(voisin.live)


# ── Flux des syndicats hébergés ailleurs ──────────────────────────────────────

FLUX_RSS_EXEMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>STAA</title>
  <item>
    <title>La surcotisation forfaitaire</title>
    <link>https://staa-cnt-so.org/2026/05/25/surcotisation/</link>
    <guid isPermaLink="false">https://staa-cnt-so.org/?p=1234</guid>
    <pubDate>Mon, 25 May 2026 08:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Communiqu&#233; de soutien</title>
    <link>https://staa-cnt-so.org/2026/06/03/soutien/</link>
    <guid isPermaLink="false">https://staa-cnt-so.org/?p=1250</guid>
    <pubDate>Wed, 03 Jun 2026 08:00:00 +0000</pubDate>
  </item>
</channel></rss>"""


class _FausseReponse:
    """Réponse HTTP minimale, pour ne pas sortir sur le réseau pendant les tests."""

    def __init__(self, contenu=FLUX_RSS_EXEMPLE, status_code=200, etag='"abc"'):
        self.content = contenu
        self.status_code = status_code
        self.headers = {'ETag': etag} if etag else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f'{self.status_code}')


class FluxUrlTest(TestCase):
    """Un syndicat hébergé ailleurs publie presque toujours un WordPress :
    imposer la saisie du `/feed/` à la main serait un champ de plus à remplir
    et une occasion d'oubli."""

    def test_flux_deduit_du_site_externe(self):
        site = make_site(slug='staa', name='STAA', site_type='sectoral',
                         external_url='https://staa-cnt-so.org/')
        self.assertEqual(site.get_feed_url(), 'https://staa-cnt-so.org/feed/')

    def test_feed_url_explicite_prioritaire(self):
        site = make_site(slug='staa', name='STAA', site_type='sectoral',
                         external_url='https://staa-cnt-so.org/')
        site.feed_url = 'https://staa-cnt-so.org/atom.xml'
        site.save()
        self.assertEqual(site.get_feed_url(), 'https://staa-cnt-so.org/atom.xml')

    def test_syndicat_heberge_chez_nous_na_pas_de_flux(self):
        """Ses articles sont déjà en base : aller les chercher en RSS les
        dupliquerait dans le cartouche du réseau."""
        site = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        self.assertEqual(site.get_feed_url(), '')


class SyncFluxReseauTest(TestCase):

    def setUp(self):
        self.site = make_site(slug='staa', name='STAA', site_type='sectoral',
                              external_url='https://staa-cnt-so.org/')

    def _sync(self, reponse=None, **kwargs):
        from django.core.management import call_command
        with patch('content.management.commands.sync_flux_reseau.requests.get',
                   return_value=reponse or _FausseReponse()) as faux:
            call_command('sync_flux_reseau', stdout=StringIO(), stderr=StringIO(), **kwargs)
        return faux

    def test_moissonne_les_entrees(self):
        self._sync()
        articles = ExternalArticle.objects.filter(section=self.site)
        self.assertEqual(articles.count(), 2)
        recent = articles.first()
        self.assertEqual(recent.title, 'Communiqué de soutien')
        self.assertEqual(recent.get_absolute_url(),
                         'https://staa-cnt-so.org/2026/06/03/soutien/')
        self.assertEqual(recent.published_at.date().isoformat(), '2026-06-03')

    def test_deux_passages_ne_dupliquent_pas(self):
        self._sync()
        self._sync()
        self.assertEqual(ExternalArticle.objects.count(), 2)

    def test_flux_inchange_ne_retelecharge_pas(self):
        """Le 304 économise la bande passante du syndicat qui nous l'offre."""
        self._sync()
        self.site.refresh_from_db()
        self.assertEqual(self.site.feed_etag, '"abc"')
        faux = self._sync(reponse=_FausseReponse(status_code=304))
        self.assertEqual(faux.call_args.kwargs['headers']['If-None-Match'], '"abc"')
        self.assertEqual(ExternalArticle.objects.count(), 2)

    def test_flux_injoignable_ne_fait_pas_echouer_la_commande(self):
        """Un serveur voisin en panne ne doit ni casser le cron ni effacer
        les articles déjà connus : on réessaiera à l'heure suivante."""
        from django.core.management import call_command
        import requests
        self._sync()
        with patch('content.management.commands.sync_flux_reseau.requests.get',
                   side_effect=requests.ConnectionError('injoignable')):
            call_command('sync_flux_reseau', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(ExternalArticle.objects.count(), 2)

    def test_dry_run_necrit_rien(self):
        self._sync(**{'dry_run': True})
        self.assertEqual(ExternalArticle.objects.count(), 0)

    def test_purge_au_dela_du_plafond(self):
        from content.management.commands.sync_flux_reseau import MAX_PAR_SITE
        for i in range(MAX_PAR_SITE + 5):
            ExternalArticle.objects.create(
                section=self.site, guid=f'vieux-{i}', title=f'Vieux {i}',
                url=f'https://staa-cnt-so.org/vieux-{i}/',
                published_at=timezone.now() - timedelta(days=100 + i))
        self._sync()
        self.assertEqual(ExternalArticle.objects.filter(section=self.site).count(),
                         MAX_PAR_SITE)
        # Les deux entrées du flux sont récentes : elles survivent à la purge.
        self.assertTrue(ExternalArticle.objects.filter(
            title='Communiqué de soutien').exists())


class ReseauAccueilFluxExterneTest(TestCase):
    """Un syndicat parti vivre sur son propre site disparaissait du cartouche
    « réseau », c'est-à-dire du seul endroit de l'accueil où les sous-sites
    s'expriment."""

    def setUp(self):
        make_site(slug='principal')
        self.externe = make_site(slug='staa', name='STAA', site_type='sectoral',
                                 external_url='https://staa-cnt-so.org/')
        self.interne = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        make_article_page(section_slug='13', title='Grève au nettoyage')
        self.article_externe = ExternalArticle.objects.create(
            section=self.externe, guid='p1', title='La surcotisation forfaitaire',
            url='https://staa-cnt-so.org/2026/05/25/surcotisation/',
            published_at=timezone.now())

    def test_larticle_externe_apparait_dans_le_reseau(self):
        html = self.client.get('/').content.decode()
        self.assertIn('La surcotisation forfaitaire', html)
        self.assertIn('https://staa-cnt-so.org/2026/05/25/surcotisation/', html)
        self.assertIn('STAA', html)

    def test_le_lien_externe_souvre_dans_un_nouvel_onglet(self):
        html = self.client.get('/').content.decode()
        lien = [l for l in html.split('<a ') if 'surcotisation' in l][0]
        self.assertIn('target="_blank"', lien)
        self.assertIn('rel="noopener"', lien)

    def test_les_articles_internes_restent(self):
        html = self.client.get('/').content.decode()
        self.assertIn('Grève au nettoyage', html)

    def test_depublier_le_syndicat_retire_ses_articles_du_reseau(self):
        """Dépublier ferme le site du syndicat : ses articles ne doivent pas
        continuer à s'afficher sur l'accueil de la confédération."""
        self.externe.live = False
        self.externe.save(update_fields=['live'])
        html = self.client.get('/').content.decode()
        self.assertNotIn('La surcotisation forfaitaire', html)

    def test_le_tour_de_table_melange_les_deux_sources(self):
        """Un site externe bavard ne doit pas rafler toutes les places."""
        for i in range(9):
            ExternalArticle.objects.create(
                section=self.externe, guid=f'p{i + 10}', title=f'Externe {i}',
                url=f'https://staa-cnt-so.org/{i}/',
                published_at=timezone.now())
        html = self.client.get('/').content.decode()
        self.assertIn('Grève au nettoyage', html)


# ── Page « Nos syndicats et structures » ──────────────────────────────────────

PAGE_SYNDICATS_HTML = """<div class="article-content">
<p>La CNT-SO organise les travailleur·euses de tous les secteurs.</p>
</div>

<style>
.syndicats-grid { display: grid; }
</style>

<div class="syndicats-grid">
  <a href="/categorie/nettoyage/" class="syndicat-card">
    <img class="syndicat-card-img" src="/media/uploads/2025/12/nettoyage.png" alt="Nettoyage">
    <div class="syndicat-card-body">
      <div class="syndicat-card-title">Nettoyage</div>
      <div class="syndicat-card-desc">Propreté, multiservices&hellip;</div>
    </div>
  </a>
  <a href="/numerique/" class="syndicat-card">
    <div class="syndicat-card-img" style="background:#3e3e3e;"><span>&lt;/&gt;</span></div>
    <div class="syndicat-card-body">
      <div class="syndicat-card-title">Numérique</div>
      <div class="syndicat-card-desc">Tech, informatique&hellip;</div>
    </div>
  </a>
</div>"""


class FicheSyndicatModeleTest(TestCase):

    def setUp(self):
        self.principal = make_site(slug='principal')

    def test_lien_vers_une_categorie(self):
        """La cible est une clé étrangère : renommer le slug de la catégorie
        ne laisse pas un lien mort derrière lui."""
        cat = make_cms_category(name='Nettoyage', slug='nettoyage')
        fiche = FicheSyndicat.objects.create(
            site=self.principal, titre='Nettoyage', categorie=cat)
        self.assertEqual(fiche.get_lien(), '/categorie/nettoyage/')

    def test_lien_vers_un_syndicat_heberge_ailleurs(self):
        """Le STAA vit sur son propre site : la carte doit y mener."""
        staa = make_site(slug='staa', name='STAA', site_type='sectoral',
                         external_url='https://staa-cnt-so.org/')
        fiche = FicheSyndicat.objects.create(
            site=self.principal, titre='STAA', site_cible=staa)
        self.assertEqual(fiche.get_lien(), 'https://staa-cnt-so.org/')

    def test_lien_libre_en_dernier_recours(self):
        fiche = FicheSyndicat.objects.create(
            site=self.principal, titre='Ailleurs', url='/une/page/')
        self.assertEqual(fiche.get_lien(), '/une/page/')

    def test_une_carte_sans_destination_est_refusee(self):
        """Une carte qui ne mène nulle part est un piège pour le visiteur."""
        from django.core.exceptions import ValidationError
        fiche = FicheSyndicat(site=self.principal, titre='Orpheline')
        with self.assertRaises(ValidationError):
            fiche.full_clean()

    def test_visuel_replie_sur_limage_heritee(self):
        fiche = FicheSyndicat.objects.create(
            site=self.principal, titre='Nettoyage', url='/x/',
            image_url='/media/uploads/2025/12/nettoyage.png')
        self.assertEqual(fiche.visuel_url, '/media/uploads/2025/12/nettoyage.png')


class PageSyndicatsTest(TestCase):

    def setUp(self):
        self.principal = make_site(slug='principal')
        self.cat = make_cms_category(name='Nettoyage', slug='nettoyage')

    def _fiche(self, titre='Nettoyage', **kwargs):
        kwargs.setdefault('categorie', self.cat)
        return FicheSyndicat.objects.create(
            site=self.principal, titre=titre, **kwargs)

    def test_la_page_affiche_les_fiches(self):
        self._fiche(description='Propreté, multiservices…')
        html = self.client.get('/syndicats/').content.decode()
        self.assertIn('Nettoyage', html)
        self.assertIn('Propreté, multiservices', html)
        self.assertIn('/categorie/nettoyage/', html)

    def test_une_fiche_masquee_ne_sort_pas(self):
        self._fiche(titre='Brouillon', is_active=False)
        html = self.client.get('/syndicats/').content.decode()
        self.assertNotIn('Brouillon', html)

    def test_lordre_est_respecte(self):
        self._fiche(titre='Dernière', order=10)
        self._fiche(titre='Première', order=1)
        html = self.client.get('/syndicats/').content.decode()
        self.assertLess(html.index('Première'), html.index('Dernière'))

    def test_le_chapo_vient_de_la_page_editable(self):
        """Le texte d'introduction reste modifiable dans /cms/, comme pour les
        permanences : seule la grille est passée au gabarit."""
        make_content_page(section_slug='principal', title='Nos syndicats',
                          slug='syndicats',
                          body='[{"type": "html", "value": "<p>Notre chapô à nous</p>"}]')
        html = self.client.get('/syndicats/').content.decode()
        self.assertIn('Notre chapô à nous', html)

    def test_la_page_repond_sans_aucune_fiche(self):
        r = self.client.get('/syndicats/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Aucun syndicat renseigné', r.content.decode())

    def test_les_fiches_dun_autre_site_ne_sortent_pas(self):
        autre = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        FicheSyndicat.objects.create(site=autre, titre='Fiche du 13',
                                     categorie=self.cat)
        html = self.client.get('/syndicats/').content.decode()
        self.assertNotIn('Fiche du 13', html)


class ImporteFichesSyndicatsTest(TestCase):
    """La conversion du vieux bloc HTML en fiches éditables."""

    def setUp(self):
        self.principal = make_site(slug='principal')
        self.cat = make_cms_category(name='Nettoyage', slug='nettoyage')
        self.numerique = make_site(slug='numerique', name='CNT-SO Numérique',
                                   site_type='sectoral')
        self.page = make_content_page(
            section_slug='principal', title='Nos syndicats', slug='syndicats',
            body=json_module.dumps([{'type': 'html', 'value': PAGE_SYNDICATS_HTML}]))

    def _importer(self, *args):
        from django.core.management import call_command
        sortie = StringIO()
        call_command('importe_fiches_syndicats', *args,
                     stdout=sortie, stderr=StringIO())
        return sortie.getvalue()

    def test_les_cartes_deviennent_des_fiches(self):
        self._importer()
        self.assertEqual(FicheSyndicat.objects.count(), 2)
        nettoyage = FicheSyndicat.objects.get(titre='Nettoyage')
        self.assertEqual(nettoyage.categorie, self.cat)
        self.assertEqual(nettoyage.description, 'Propreté, multiservices…')
        self.assertEqual(nettoyage.image_url,
                         '/media/uploads/2025/12/nettoyage.png')

    def test_une_carte_sans_image_est_importee_quand_meme(self):
        """Numérique et le STAA n'ont pas d'image mais un aplat de couleur :
        une regex qui attendait un `<img>` les sautait en silence."""
        self._importer()
        numerique = FicheSyndicat.objects.get(titre='Numérique')
        self.assertEqual(numerique.site_cible, self.numerique)
        self.assertEqual(numerique.image_url, '')

    def test_relancer_ne_duplique_pas(self):
        self._importer()
        self._importer()
        self.assertEqual(FicheSyndicat.objects.count(), 2)

    def test_dry_run_necrit_rien(self):
        self._importer('--dry-run')
        self.assertEqual(FicheSyndicat.objects.count(), 0)

    def test_completer_ajoute_les_syndicats_absents(self):
        """La page oubliait le STAA, le TAS et le Numérique — non par choix,
        mais parce qu'ajouter une carte demandait de recopier des balises."""
        tas = make_site(slug='tas', name='TAS', site_type='sectoral',
                        external_url='https://www.cnt-tas.org/')
        self._importer('--completer')
        fiche = FicheSyndicat.objects.get(site_cible=tas)
        self.assertEqual(fiche.get_lien(), 'https://www.cnt-tas.org/')
        # Le Numérique était déjà une carte : il ne doit pas être ajouté deux fois.
        self.assertEqual(
            FicheSyndicat.objects.filter(site_cible=self.numerique).count(), 1)

    def test_completer_ajoute_les_secteurs_du_menu_sans_carte(self):
        """La page et le menu « Secteurs » énumèrent la même chose : ce que le
        menu annonce, la page doit le montrer. Trois secteurs du menu n'avaient
        pas de carte (T.P.E., Animation & Éducation populaire, Intérim)."""
        interim = make_cms_category(name='Intérim', slug='interim')
        MenuItem.objects.create(site=self.principal, menu='main',
                                link_type='category', title='Intérim',
                                category=interim, order=5,
                                parent=self._menu_secteurs())
        self._importer('--completer')
        fiche = FicheSyndicat.objects.get(titre='Intérim')
        self.assertEqual(fiche.categorie, interim)
        self.assertEqual(fiche.get_lien(), '/categorie/interim/')

    def test_completer_ne_double_pas_un_secteur_deja_en_carte(self):
        """« Nettoyage » est déjà une carte de la page : le menu ne doit pas
        en ajouter une seconde."""
        MenuItem.objects.create(site=self.principal, menu='main',
                                link_type='category', title='Nettoyage',
                                category=self.cat, order=1,
                                parent=self._menu_secteurs())
        self._importer('--completer')
        self.assertEqual(
            FicheSyndicat.objects.filter(categorie=self.cat).count(), 1)

    def test_les_cartes_ajoutees_se_rangent_a_la_fin(self):
        """Une fois la page vidée de son HTML, le compteur de cartes lues vaut
        zéro : les cartes ajoutées venaient s'entrelacer en tête de grille."""
        self._importer('--vider-la-page')
        interim = make_cms_category(name='Intérim', slug='interim')
        MenuItem.objects.create(site=self.principal, menu='main',
                                link_type='category', title='Intérim',
                                category=interim, order=5,
                                parent=self._menu_secteurs())
        self._importer('--completer')
        ajoutee = FicheSyndicat.objects.get(titre='Intérim')
        autres = FicheSyndicat.objects.exclude(pk=ajoutee.pk)
        self.assertTrue(all(f.order < ajoutee.order for f in autres))

    def _menu_secteurs(self):
        return MenuItem.objects.create(
            site=self.principal, menu='main', title='Secteurs', url='#')

    def test_completer_ignore_les_rubriques_hors_secteurs(self):
        """« Solidarités » est une rubrique racine du menu, pas un champ de
        syndicalisation : lui fabriquer une carte n'aurait aucun sens."""
        solidarites = make_cms_category(name='Solidarités', slug='solidarites')
        MenuItem.objects.create(site=self.principal, menu='main',
                                link_type='category', title='Solidarités',
                                category=solidarites, order=6)
        self._importer('--completer')
        self.assertFalse(FicheSyndicat.objects.filter(titre='Solidarités').exists())

    def test_completer_ignore_une_categorie_homonyme(self):
        """Le même champ existe parfois en deux catégories, héritage de
        l'import WordPress : « Activités postales » est en base deux fois, la
        fiche pointant sur l'une et le menu sur l'autre. Deux cartes pour la
        même chose ne seraient qu'un doublon aux yeux du lecteur."""
        postale_a = make_cms_category(name='Activités postales', slug='postales-a')
        postale_b = make_cms_category(name='Activités Postales', slug='postales-b')
        FicheSyndicat.objects.create(site=self.principal, titre='Activités postales',
                                     categorie=postale_a)
        MenuItem.objects.create(site=self.principal, menu='main',
                                link_type='category', title='Activités postales',
                                category=postale_b, order=7,
                                parent=self._menu_secteurs())
        self._importer('--completer')
        self.assertEqual(
            FicheSyndicat.objects.filter(titre__icontains='postales').count(), 1)

    def test_vider_la_page_garde_le_chapo(self):
        self._importer('--vider-la-page')
        self.page.refresh_from_db()
        corps = ''.join(str(b.value) for b in self.page.body)
        self.assertIn('La CNT-SO organise', corps)
        self.assertNotIn('syndicats-grid', corps)
        self.assertNotIn('<style>', corps)

    def test_la_page_rendue_ne_double_pas_les_cartes(self):
        """Tant que le corps garde l'ancienne grille, chaque carte s'affiche
        deux fois : celle du gabarit et celle du bloc HTML."""
        self._importer('--vider-la-page')
        html = self.client.get('/syndicats/').content.decode()
        self.assertEqual(html.count('class="syndicat-card"'), 2)


class MenuChoixTest(TestCase):
    """Un menu proposé aux rédacteurs doit être un menu affiché.

    « Menu secondaire » a figuré des mois dans la liste déroulante de /cms/
    sans qu'aucun gabarit ne l'appelle : la production portait dix entrées
    éditables et sans effet, dont personne ne pouvait deviner l'inutilité.
    """

    def test_seuls_les_menus_rendus_sont_proposes(self):
        proposes = {code for code, _ in MenuItem.MENU_CHOICES}
        self.assertEqual(proposes, {'main', 'footer'})

    def test_chaque_menu_propose_a_un_gabarit_qui_lappelle(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR) / 'templates'
        rendus = set()
        for gabarit in base.rglob('*.html'):
            texte = gabarit.read_text(encoding='utf-8', errors='ignore')
            for code, _ in MenuItem.MENU_CHOICES:
                if f"get_menu site '{code}'" in texte:
                    rendus.add(code)
        self.assertEqual(rendus, {code for code, _ in MenuItem.MENU_CHOICES})


class NewsletterAntiAbusTest(TestCase):
    """L'inscription ne doit plus servir de relais à courriels.

    Du 24/07 au 17/08/2026, un botnet a posté une centaine de fois par jour sur
    `/newsletter/inscription/` depuis 25 adresses IP : la vue lisait
    `request.POST` sans formulaire ni captcha, créait l'abonné et faisait
    partir un courriel de confirmation vers l'adresse postée. Près de 2 000
    boîtes tierces ont été bombardées depuis nos serveurs.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        from django.core.cache import cache
        cache.clear()

    def test_un_post_direct_ninscrit_personne(self):
        """Le geste exact du botnet : poster une adresse et rien d'autre."""
        r = self.client.post('/newsletter/inscription/',
                             {'email': 'victime@example.com'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Subscriber.objects.count(), 0)

    def test_un_post_direct_nenvoie_aucun_courriel(self):
        from django.core import mail
        self.client.post('/newsletter/inscription/',
                         {'email': 'victime@example.com'})
        self.assertEqual(len(mail.outbox), 0)

    def test_la_premiere_etape_mene_au_captcha(self):
        r = self.client.post('/newsletter/inscription/',
                             {'email': 'camarade@example.org'})
        self.assertContains(r, 'robot')
        self.assertContains(r, 'camarade@example.org')

    def test_le_champ_piege_arrete_le_robot(self):
        r = self.client.post('/newsletter/inscription/',
                             {'email': 'robot@example.com',
                              'site_web': 'http://spam.example'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Subscriber.objects.count(), 0)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_le_captcha_franchi_inscrit_et_envoie(self, _):
        from django.core import mail
        r = self.client.post('/newsletter/inscription/valider/', {
            'email': 'camarade@example.org', 'name': '',
            'h-captcha-response': 'ok'})
        self.assertEqual(r.status_code, 200)
        abonne = Subscriber.objects.get(email='camarade@example.org')
        self.assertFalse(abonne.is_active)  # double opt-in : le lien reste à cliquer
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('camarade@example.org', mail.outbox[0].to)

    def test_sans_captcha_la_validation_est_refusee(self):
        from django.core import mail
        r = self.client.post('/newsletter/inscription/valider/',
                             {'email': 'victime@example.com'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Subscriber.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_une_meme_ip_est_bornee(self, _):
        """Même avec un captcha résolu, une IP ne peut pas enchaîner."""
        from content.views import NEWSLETTER_MAX_PAR_IP
        for i in range(NEWSLETTER_MAX_PAR_IP):
            r = self.client.post('/newsletter/inscription/valider/', {
                'email': f'camarade{i}@example.org', 'h-captcha-response': 'ok'})
            self.assertEqual(r.status_code, 200)
        r = self.client.post('/newsletter/inscription/valider/', {
            'email': 'un-de-trop@example.org', 'h-captcha-response': 'ok'})
        self.assertEqual(r.status_code, 429)
        self.assertFalse(
            Subscriber.objects.filter(email='un-de-trop@example.org').exists())

    def test_le_champ_piege_est_dans_le_formulaire_public(self):
        """Sans le champ dans la page, le piège ne se déclencherait jamais."""
        html = self.client.get('/').content.decode()
        self.assertIn('name="site_web"', html)


class OvhListeInscriptionTest(TestCase):
    """Où atterrissent les inscrits venus du site.

    Le 17/08/2026, la liste « news » était pleine (plafond dur OVH : 5 000)
    mais son compteur `nbSubscribers` annonçait 1 260. Le site la croyait donc
    disponible, continuait d'y inscrire, et chaque ajout échouait en silence :
    la newsletter ne pouvait plus gagner un seul abonné.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        self.site.ovh_mailing_list = 'news,news2,news3'
        self.site.save()

    @override_settings(OVH_APPLICATION_KEY='cle-de-test', OVH_LIST_CAP=4900)
    @patch('cms.ovh_client.get_subscribers')
    def test_le_comptage_enumere_au_lieu_de_croire_le_compteur(self, faux_abonnes):
        from django.core.cache import cache
        from content.ovh_sync import list_count
        cache.clear()
        faux_abonnes.return_value = ['a@x.fr'] * 5000
        self.assertEqual(list_count('news'), 5000)

    @override_settings(OVH_APPLICATION_KEY='cle-de-test', OVH_LIST_CAP=4900)
    @patch('cms.ovh_client.get_subscribers')
    def test_une_liste_pleine_est_evitee(self, faux_abonnes):
        from django.core.cache import cache
        from content.ovh_sync import pick_list
        cache.clear()
        faux_abonnes.side_effect = lambda nom: (['a@x.fr'] * 5000 if nom == 'news'
                                                else ['b@x.fr'] * 10)
        self.assertEqual(pick_list(self.site), 'news2')

    @override_settings(OVH_APPLICATION_KEY='cle-de-test', OVH_LIST_CAP=4900)
    @patch('cms.ovh_client.get_subscribers')
    def test_la_liste_dediee_lemporte(self, faux_abonnes):
        """Les inscrits du site doivent rester distincts des adresses héritées,
        dont on ne connaît ni l'origine ni le consentement."""
        from django.core.cache import cache
        from content.ovh_sync import pick_list
        cache.clear()
        faux_abonnes.return_value = ['b@x.fr'] * 10
        self.site.ovh_liste_inscription = 'news3'
        self.site.save()
        self.assertEqual(pick_list(self.site), 'news3')

    @override_settings(OVH_APPLICATION_KEY='cle-de-test', OVH_LIST_CAP=4900)
    @patch('cms.ovh_client.get_subscribers')
    def test_une_liste_dediee_pleine_ne_bloque_pas_linscription(self, faux_abonnes):
        from django.core.cache import cache
        from content.ovh_sync import pick_list
        cache.clear()
        faux_abonnes.side_effect = lambda nom: (['a@x.fr'] * 5000 if nom == 'news3'
                                                else ['b@x.fr'] * 10)
        self.site.ovh_liste_inscription = 'news3'
        self.site.save()
        self.assertEqual(pick_list(self.site), 'news')


class NewsletterRubriquesTest(TestCase):
    """Le sommaire de la newsletter confédérale.

    Le rédacteur choisit des articles et leur donne une rubrique ; les sections
    se composent seules. Il n'y a rien à cocher : une rubrique sans article
    n'existe pas dans l'e-mail.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        self.nl = Newsletter.objects.create(
            site=self.site, title='La lettre de la conf', intro='Bonjour à toutes et tous.')
        self.rang = 0

    def _article(self, titre, rubrique=''):
        from content.models import NewsletterArticle
        self.rang += 1
        art = make_article_page(section_slug='principal', title=titre,
                                slug=titre.lower().replace(' ', '-').replace("'", ''))
        return ajoute_a_la_newsletter(self.nl, art, rubrique=rubrique)

    def test_les_rubriques_sortent_dans_lordre_du_redacteur(self):
        """Cet ordre était figé dans le code jusqu'au 18/08/2026 : c'est
        désormais celui des blocs, que le rédacteur déplace."""
        self._article('Solidarité internationale', 'international')
        self._article('Grève au nettoyage', 'actu-syndicale')
        self._article('Campagne sans-papiers', 'campagne')
        libelles = [libelle for libelle, _ in self.nl.par_rubrique()]
        self.assertEqual(libelles, ['International', 'Actu syndicale', 'Campagnes'])

    def test_une_rubrique_sans_article_nexiste_pas(self):
        self._article('Campagne sans-papiers', 'campagne')
        libelles = [libelle for libelle, _ in self.nl.par_rubrique()]
        self.assertEqual(libelles, ['Campagnes'])
        self.assertNotIn('Nos droits', libelles)

    def test_une_rubrique_sans_titre_sert_de_liste_a_plat(self):
        """Ce que produisent les newsletters des syndicats, qui n'ont pas de
        rubriques : une liste sans titre de section."""
        self._article('Un mot du syndicat')
        self._article('Campagne sans-papiers', 'campagne')
        groupes = self.nl.par_rubrique()
        self.assertEqual(groupes[0][0], '')
        self.assertEqual(groupes[0][1][0].article.title, 'Un mot du syndicat')
        self.assertEqual(groupes[1][0], 'Campagnes')

    def test_lordre_est_respecte_dans_une_rubrique(self):
        self._article('Première grève', 'actu-syndicale')
        self._article('Seconde grève', 'actu-syndicale')
        _, articles = self.nl.par_rubrique()[0]
        self.assertEqual([na.article.title for na in articles],
                         ['Première grève', 'Seconde grève'])

    def test_une_newsletter_sans_article_ne_produit_aucune_section(self):
        self.assertEqual(self.nl.par_rubrique(), [])

    def test_le_gabarit_affiche_les_titres_de_section(self):
        from django.template.loader import render_to_string
        self._article('Campagne sans-papiers', 'campagne')
        self._article('Grève au nettoyage', 'actu-syndicale')
        html = render_to_string('newsletter/email.html', {
            'newsletter': self.nl,
            'newsletter_articles': list(self.nl.articles_a_plat()),
            'groupes': self.nl.par_rubrique(),
            'site_url': 'https://cnt-so.org/',
            'unsubscribe_url': 'https://cnt-so.org/desabo/',
            'is_preview': True,
        })
        self.assertIn('Campagnes', html)
        self.assertIn('Actu syndicale', html)
        self.assertNotIn('International', html)
        self.assertLess(html.index('Campagnes'), html.index('Actu syndicale'))

    def test_la_version_texte_reprend_les_rubriques(self):
        """Un lecteur en texte brut doit recevoir le même sommaire, pas une
        liste à plat qui perdrait le sens des sections."""
        from content.newsletter_views import _corps_texte
        self._article('Campagne sans-papiers', 'campagne')
        articles = self.nl.articles_a_plat()
        for na in articles:
            na.link_url = 'https://cnt-so.org/article/x/'
        texte = _corps_texte(self.nl, articles, 'https://cnt-so.org/desabo/')
        self.assertIn('CAMPAGNES', texte)
        self.assertIn('Campagne sans-papiers', texte)
        self.assertIn('Gérer votre abonnement', texte)

    def test_letiquette_de_categorie_disparait_sous_une_rubrique(self):
        """Sous un titre de section, la catégorie du site fait doublon — et
        « Non classé » y était disgracieux (signalé par Arnaud, 17/08/2026)."""
        from django.template.loader import render_to_string
        cat = make_cms_category(name='Orientations', slug='orientations')
        na = self._article('Campagne sans-papiers', 'campagne')
        through = ArticlePage.cms_categories.through
        through.objects.create(articlepage=na.article, cmscategory=cat)

        def rendu():
            return render_to_string('newsletter/email.html', {
                'newsletter': self.nl,
                'newsletter_articles': list(self.nl.articles_a_plat()),
                'groupes': self.nl.par_rubrique(),
                'site_url': 'https://cnt-so.org/',
                'unsubscribe_url': 'https://cnt-so.org/desabo/',
                'is_preview': True,
            })

        self.assertNotIn('Orientations', rendu())

        # Sans titre de section, l'étiquette reste : c'est le rendu des
        # syndicats, qui n'ont pas de rubriques.
        na.bloc.rubrique = ''
        na.bloc.save()
        self.assertIn('Orientations', rendu())


class BoutonRedactionTest(TestCase):
    """Une porte d'entrée vers /cms/ depuis chaque sous-site.

    Le lien était conditionné à `user.is_authenticated`. Or la session est
    propre à chaque domaine : un gestionnaire du 86 arrive déconnecté sur
    86.cnt-so.org, ne voyait donc aucun bouton, et devait passer par le site
    de la confédération pour modifier ses propres pages (signalé par Arnaud,
    17/08/2026).
    """

    def setUp(self):
        make_site(slug='principal')
        self.sous_site = make_site(slug='poitiers', name='CNT-SO Poitiers',
                                   site_type='regional')

    def test_le_bouton_est_visible_sur_un_sous_site_sans_etre_connecte(self):
        html = self.client.get('/poitiers/').content.decode()
        self.assertIn('Rédaction', html)

    def test_le_bouton_reste_absent_de_laccueil_conf_pour_un_visiteur(self):
        """Rien ne change pour le public de la confédération."""
        html = self.client.get('/').content.decode()
        self.assertNotIn('>\n                Rédaction', html)

    def test_le_bouton_apparait_pour_un_utilisateur_connecte(self):
        User.objects.create_user('camarade', password='secret-12345')
        self.client.login(username='camarade', password='secret-12345')
        html = self.client.get('/').content.decode()
        self.assertIn('Rédaction', html)

    @override_settings(ALLOWED_HOSTS=['testserver', '86.cnt-so.org'],
                       MAIN_SITE_BASE_URL='https://newsite.cnt-so.org')
    def test_depuis_un_domaine_de_federation_le_lien_est_absolu(self):
        """Un /cms/ relatif y provoque une redirection, et surtout la session
        n'existe pas sur ce domaine : le lien doit mener droit à la conf."""
        from django.core.cache import cache
        cache.clear()  # le lookup hôte→section est mis en cache 60 s
        self.sous_site.custom_domain = '86.cnt-so.org'
        self.sous_site.save()
        html = self.client.get('/', HTTP_HOST='86.cnt-so.org').content.decode()
        self.assertIn('https://newsite.cnt-so.org/cms/', html)


class CartouchesDeBarreLateraleTest(TestCase):
    """Deux cartouches annonçaient du contenu et n'en montraient aucun.

    Tous deux filtraient sur une catégorie « incontournables » qui n'existe
    dans aucune section : « Ce que vous avez loupé » sur l'accueil confédéral
    et « Nouvelles de la confédération » sur les sous-sites étaient vides
    depuis toujours (constaté en production le 17/08/2026, signalé par Arnaud).
    """

    def setUp(self):
        make_site(slug='principal')
        self.sous_site = make_site(slug='poitiers', name='CNT-SO Poitiers',
                                   site_type='regional')
        self.cat = make_cms_category(name='Luttes', slug='luttes')
        make_article_page(section_slug='principal', title='Communiqué confédéral',
                          slug='communique-confederal', categories=[self.cat])
        make_article_page(section_slug='poitiers', title='Grève locale au 86',
                          slug='greve-locale-86', categories=[self.cat])

    def test_laccueil_conf_montre_les_articles_recents(self):
        html = self.client.get('/').content.decode()
        bloc = html.split('Ce que vous avez loupé')[-1][:2000]
        self.assertIn('Communiqué confédéral', bloc)

    def test_le_sous_site_montre_bien_les_nouvelles_de_la_conf(self):
        html = self.client.get('/poitiers/').content.decode()
        bloc = html.split('Nouvelles de la confédération')[-1][:2000]
        self.assertIn('Communiqué confédéral', bloc)

    def test_le_sous_site_ny_montre_pas_ses_propres_articles(self):
        """C'est l'erreur d'origine : le cartouche annonçait la conf et
        recevait les articles du sous-site."""
        html = self.client.get('/poitiers/').content.decode()
        bloc = html.split('Nouvelles de la confédération')[-1][:2000]
        self.assertNotIn('Grève locale au 86', bloc)


class InscriptionDepuisUnSousSiteTest(TestCase):
    """Seule la confédération diffuse une newsletter.

    Les autres listes OVH sont des listes de travail internes, réservées aux
    adhérent·es (arbitrage d'Arnaud, 17/08/2026). Un visiteur qui s'abonne
    depuis le site du 86 doit donc rejoindre la lettre confédérale — et non
    une base que personne n'utilise, l'impasse silencieuse qu'on a passé la
    journée à supprimer.
    """

    def setUp(self):
        from django.core.cache import caches
        caches['limites'].clear()
        self.conf = make_site(slug='principal')
        self.conf.ovh_mailing_list = 'news3'
        self.conf.save()
        self.sous_site = make_site(slug='poitiers', name='CNT-SO Poitiers',
                                   site_type='regional')

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_un_abonne_du_86_rejoint_la_lettre_confederale(self, _captcha):
        self.client.post('/poitiers/newsletter/inscription/valider/',
                         {'email': 'camarade@example.org', 'h-captcha-response': 'ok'})
        abonne = Subscriber.objects.get(email='camarade@example.org')
        self.assertEqual(abonne.site, self.conf)

    @patch('hcaptcha.fields.hCaptchaField.validate')
    def test_un_syndicat_qui_a_sa_liste_garde_ses_inscrits(self, _captcha):
        """La règle suit les données : rendre sa liste à un syndicat lui rend
        sa newsletter, sans toucher au code."""
        self.sous_site.ovh_mailing_list = 'sante-social-86'
        self.sous_site.save()
        self.client.post('/poitiers/newsletter/inscription/valider/',
                         {'email': 'locale@example.org', 'h-captcha-response': 'ok'})
        abonne = Subscriber.objects.get(email='locale@example.org')
        self.assertEqual(abonne.site, self.sous_site)

    def test_la_page_de_validation_annonce_la_bonne_newsletter(self):
        """Le visiteur doit savoir à quelle lettre il s'abonne avant de valider."""
        r = self.client.post('/poitiers/newsletter/inscription/',
                             {'email': 'camarade@example.org'})
        self.assertContains(r, self.conf.title)


class NewsletterReserveeALaConfTest(TestCase):
    """La newsletter n'est plus proposée que par la confédération.

    Les autres listes OVH sont des listes de travail internes, réservées aux
    adhérent·es (arbitrage d'Arnaud, 17/08/2026). Un interrupteur par syndicat
    permet de la lui rendre : « Proposer la newsletter sur ce site », dans sa
    fiche.
    """

    def setUp(self):
        self.conf = make_site(slug='principal')
        self.conf.newsletter_active = True
        self.conf.save()
        self.sous_site = make_site(slug='poitiers', name='CNT-SO Poitiers',
                                   site_type='regional')

    def test_lencart_a_disparu_du_sous_site(self):
        html = self.client.get('/poitiers/').content.decode()
        self.assertNotIn('Restez informé', html)
        self.assertNotIn("Restez aux aguets", html)

    def test_lencart_reste_sur_la_conf(self):
        html = self.client.get('/').content.decode()
        self.assertIn('newsletter', html.lower())
        self.assertIn("Restez aux aguets", html)

    def test_linterrupteur_le_rend_au_syndicat(self):
        """Cocher la case suffit : c'est le bouton de réactivation."""
        self.sous_site.newsletter_active = True
        self.sous_site.save()
        html = self.client.get('/poitiers/').content.decode()
        self.assertIn('Restez informé', html)

    def test_par_defaut_un_nouveau_syndicat_na_pas_de_newsletter(self):
        neuf = make_site(slug='34', name='CNT-SO 34', site_type='regional')
        self.assertFalse(neuf.newsletter_active)

    def test_envoyer_depuis_un_syndicat_coupe_est_refuse(self):
        """Sans ce garde-fou, la lettre « partait » sans destinataire et sans
        que rien ne le dise.

        Le chef doit s'être placé SUR Poitiers : depuis le 31/08/2026 un compte
        de haut niveau atterrit sur la confédération, et le cloisonnement de
        `_get_newsletter` refuse alors la lettre d'un autre syndicat avant même
        d'arriver ici. C'est le test suivant qui couvre ce refus-là.
        """
        from django.contrib.auth.models import User
        chef = User.objects.create_superuser('chef-nl', 'c@x.fr', 'x')
        self.client.force_login(chef)
        session = self.client.session
        session['cms_current_site_id'] = self.sous_site.pk
        session.save()
        nl = Newsletter.objects.create(site=self.sous_site, title='Lettre du 86',
                                       intro='Bonjour')
        r = self.client.get(f'/cms/newsletter/{nl.pk}/envoyer/', follow=True)
        self.assertIn("n&#x27;est pas activée", r.content.decode())
        nl.refresh_from_db()
        self.assertEqual(nl.status, 'draft')

    def test_la_lettre_dun_autre_syndicat_est_refusee(self):
        """Placé sur la confédération, un chef n'ouvre pas la lettre de Poitiers.

        Effet de l'atterrissage par défaut sur la conf : le cloisonnement de
        `NewsletterSendView._get_newsletter` s'applique désormais dès la
        connexion, là où un chef sans syndicat choisi passait au travers.
        """
        from django.contrib.auth.models import User
        chef = User.objects.create_superuser('chef-nl-conf', 'cc@x.fr', 'x')
        self.client.force_login(chef)
        nl = Newsletter.objects.create(site=self.sous_site, title='Lettre du 86',
                                       intro='Bonjour')
        r = self.client.get(f'/cms/newsletter/{nl.pk}/envoyer/')
        # 302 et non 403 : Wagtail convertit PermissionDenied en redirection
        # dans les vues enregistrées par `register_admin_urls` (cf. la fiche
        # « Pièges Wagtail »).
        #
        # La destination distingue les deux refus, et c'est tout l'intérêt du
        # test : le cloisonnement renvoie sur /cms/ AVANT d'examiner la lettre,
        # tandis que le garde-fou « newsletter coupée » renvoie sur la liste
        # des newsletters avec son message. Un test qui se contenterait du 302
        # passerait dans les deux cas — donc ne prouverait rien.
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/cms/')
        corps = self.client.get(f'/cms/newsletter/{nl.pk}/envoyer/',
                                follow=True).content.decode()
        self.assertNotIn("n&#x27;est pas activée", corps)
        nl.refresh_from_db()
        self.assertEqual(nl.status, 'draft')


class NewsletterDelivrabiliteTest(TestCase):
    """Ce qui envoyait la newsletter dans les indésirables.

    Le 18/08/2026, un courriel de confirmation est arrivé en indésirable chez
    Gmail alors que SPF, DKIM et DMARC passaient tous les trois. Restaient
    trois défauts dans le message lui-même, plus une réputation d'envoi abîmée
    par trois semaines de bombardement.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        self.site.newsletter_active = True
        self.site.save()
        from django.core.cache import caches
        caches['limites'].clear()

    def test_le_message_id_porte_un_vrai_domaine(self):
        """`@cnt-so` n'est pas un domaine : Django prenait le nom de la machine."""
        from django.core import mail
        with patch('hcaptcha.fields.hCaptchaField.validate', return_value=None):
            self.client.post('/newsletter/inscription/valider/', {
                'email': 'camarade@example.org', 'name': '',
                'h-captcha-response': 'test',
            })
        self.assertEqual(len(mail.outbox), 1)
        message_id = mail.outbox[0].message()['Message-ID']
        self.assertTrue(message_id.endswith('@cnt-so.org>'), message_id)

    def test_le_courriel_de_confirmation_a_une_adresse_de_reponse(self):
        from django.core import mail
        with patch('hcaptcha.fields.hCaptchaField.validate', return_value=None):
            self.client.post('/newsletter/inscription/valider/', {
                'email': 'camarade@example.org', 'name': '',
                'h-captcha-response': 'test',
            })
        self.assertEqual(mail.outbox[0].reply_to, ['contact@cnt-so.org'])


class BlocDocumentTelechargeableTest(TestCase):
    """« Il n'est pas évident de comprendre qu'on peut télécharger le document »
    (audit d'ergonomie du 01/06/2026, § 6.2).

    Le bloc n'était qu'un lien en ligne : picto « fichier » — une page cornée,
    pas un téléchargement — suivi du nom brut du document, souvent illisible
    (« com cntso sudcommerce 09 01 2026 »). Et `.btn-download` n'avait aucun
    style : rien ne le distinguait du texte courant.
    """

    def setUp(self):
        from wagtail.documents.models import Document
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wagtail.blocks.stream_block import StreamValue
        self.site = make_site(slug='principal', name='CNT-SO')
        self.doc = Document.objects.create(
            title='Appel à la lutte du 9 janvier',
            file=SimpleUploadedFile('appel.pdf', b'%PDF-1.4 essai', 'application/pdf'))
        self.article = make_article_page(section_slug='principal',
                                         title='Avec document', slug='avec-document')
        self.article.body = StreamValue(
            self.article.body.stream_block,
            [('file', {'document': self.doc, 'title': ''})], is_lazy=False)
        self.article.save_revision().publish()

    def _bloc(self):
        """Le bloc RENDU, isolé du reste de la page.

        Les premières versions de ces tests cherchaient « Télécharger » et
        « bloc-document-lien » dans la page entière — or ces deux chaînes
        figurent aussi dans la feuille de style de `base.html`. Ils passaient
        donc même en supprimant le bloc, ce qu'une mutation a montré. On
        n'inspecte plus que le fragment produit par le gabarit.
        """
        html = self.client.get('/article/avec-document/').content.decode()
        debut = html.find('<div class="bloc-document">')
        self.assertNotEqual(debut, -1, "le bloc document n'est pas rendu du tout")
        return html[debut:html.find('</div>', html.find('</a>', debut))]

    def test_laction_est_dite(self):
        """Le verbe manquait : rien n'annonçait qu'un clic téléchargeait."""
        self.assertIn('Télécharger', self._bloc())

    def test_le_titre_du_document_est_affiche(self):
        self.assertIn('Appel à la lutte du 9 janvier', self._bloc())

    def test_le_format_et_le_poids_sont_annonces(self):
        """On doit savoir ce qu'on prend avant de le prendre."""
        bloc = self._bloc()
        self.assertIn('PDF', bloc)
        self.assertRegex(bloc, r'\d+([.,]\d+)?\s*(o|octet|Ko|Mo)')

    def test_le_lien_declenche_bien_un_telechargement(self):
        """`download` distingue « enregistrer » de « ouvrir dans l'onglet »."""
        self.assertRegex(self._bloc(), r'<a[^>]+href="[^"]+\.pdf"[^>]*\sdownload')


class TelechargementVisuelBanqueTest(TestCase):
    """La banque d'image existe pour être utilisée, encore faut-il le dire.

    Audit d'ergonomie du 01/06/2026 : « en l'état le téléchargement d'une image
    n'est pas évident […] rien dans la page ne nous dit que cette action est
    possible ». La page annonce pourtant des visuels « à disposition des
    militant·es et structures de la CNT-SO ».

    `is_gallery` était calculé dans `ArticleDetailView` depuis le début et lu
    par aucun gabarit : la plomberie attendait qu'on la branche.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        self.banque = make_cms_category(name="Banque d'image", slug='banque-dimage',
                                        section_slug='principal')
        self.autre = make_cms_category(name='Luttes banque', slug='luttes-banque-test',
                                       section_slug='principal')

    def _article(self, slug, categories):
        from wagtail.images.models import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00'
               b'\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00'
               b'\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00'
               b'\x00\x00\x00IEND\xaeB`\x82')
        image = Image.objects.create(
            title=f'Visuel {slug}',
            file=SimpleUploadedFile(f'{slug}.png', png, 'image/png'))
        return make_article_page(section_slug='principal', title=slug, slug=slug,
                                 categories=categories, featured_image=image)

    def test_un_visuel_de_la_banque_se_telecharge(self):
        self._article('visuel-covid', [self.banque])
        r = self.client.get('/article/visuel-covid/')
        self.assertContains(r, 'Télécharger ce visuel')
        self.assertContains(r, 'download')

    def test_un_article_ordinaire_na_pas_ce_lien(self):
        """Le lien n'a de sens que sur la banque : ailleurs, l'image illustre."""
        self._article('article-ordinaire', [self.autre])
        r = self.client.get('/article/article-ordinaire/')
        self.assertNotContains(r, 'Télécharger ce visuel')

    def test_sans_image_aucun_lien(self):
        make_article_page(section_slug='principal', title='Sans image',
                          slug='sans-image', categories=[self.banque])
        r = self.client.get('/article/sans-image/')
        self.assertNotContains(r, 'Télécharger ce visuel')


class RechercheMultiMotsTest(TestCase):
    """Audit d'ergonomie du 31/08/2026 : « la recherche ne permet pas plusieurs
    mots ». Mesuré en production, c'est faux — elle les accepte, en exigeant
    que TOUS figurent dans l'article :

        « nettoyage »        272 résultats
        « grève »            607
        « grève nettoyage »  127   ← moins que chacun : c'est bien un ET
        « grève, nettoyage » 127   ← la virgule ne gêne pas

    Ce qui était vrai en revanche : **« ou » ne donne pas un OU** — il compte
    comme un mot de plus et restreint encore (60 résultats). Et l'écran vide ne
    disait rien : ni comment la recherche fonctionne, ni où s'adresser ensuite.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')

    def test_la_virgule_separe_les_mots(self):
        from content.views import SearchView
        self.assertEqual(SearchView._termes('grève, nettoyage'),
                         ['grève', 'nettoyage'])

    def test_les_liaisons_ne_sont_pas_cherchees(self):
        """« ou » restreignait au lieu d'élargir : autant l'effacer."""
        from content.views import SearchView
        self.assertEqual(SearchView._termes('grève ou nettoyage'),
                         ['grève', 'nettoyage'])
        self.assertEqual(SearchView._termes('grève et nettoyage'),
                         ['grève', 'nettoyage'])

    def test_une_recherche_faite_que_de_liaisons_reste_intacte(self):
        """Sinon on chercherait le vide."""
        from content.views import SearchView
        self.assertEqual(SearchView._termes('et ou'), ['et', 'ou'])

    def test_lecran_vide_explique_et_oriente(self):
        r = self.client.get('/recherche/', {'q': 'zzzqqqxxx'})
        self.assertContains(r, 'Aucun résultat')
        self.assertContains(r, 'Écrivez-nous')
        self.assertContains(r, '/contact/')

    def test_avec_plusieurs_mots_il_dit_pourquoi_cest_etroit(self):
        r = self.client.get('/recherche/', {'q': 'zzzqqq xxxwww'})
        self.assertContains(r, 'tous les')
        self.assertTrue(r.context['plusieurs_mots'])

    def test_avec_un_seul_mot_il_ne_parle_pas_de_plusieurs(self):
        r = self.client.get('/recherche/', {'q': 'zzzqqqxxx'})
        self.assertFalse(r.context['plusieurs_mots'])
        self.assertNotContains(r, 'tous les mots')


class SitemapAdressesValidesTest(TestCase):
    """83 % du sitemap servi en production était malformé.

    `Sitemap.location()` doit rendre un CHEMIN — Django y colle
    `protocole://hôte`. Or `get_absolute_url()` rend une URL absolue dès qu'une
    section a son propre domaine, et pour le principal depuis qu'il passe par
    `url_site_principal()`. D'où, relevé le 27/08/2026 sur
    https://newsite.cnt-so.org/sitemap.xml :

        https://newsite.cnt-so.orghttps://newsite.cnt-so.org/article/…

    725 adresses sur 866. Aucun test ne regardait le contenu du sitemap : on
    vérifiait qu'il répondait 200, pas ce qu'il annonçait. Or c'est le fichier
    par lequel les moteurs découvriront le site à la bascule DNS.
    """

    def setUp(self):
        self.principal = make_site(slug='principal', name='CNT-SO')
        self.article = make_article_page(section_slug='principal',
                                         title='Un article', slug='un-article')
        make_content_page(section_slug='principal', title='Une page',
                          slug='une-page')
        make_cms_category(name='Luttes', slug='luttes', section_slug='principal')

    def _adresses(self):
        reponse = self.client.get('/sitemap.xml')
        self.assertEqual(reponse.status_code, 200)
        return re.findall(r'<loc>([^<]+)</loc>',
                          reponse.content.decode('utf-8', 'replace'))

    def test_aucune_adresse_ne_porte_deux_fois_un_protocole(self):
        doublees = [u for u in self._adresses() if u.count('http') > 1]
        self.assertEqual(
            doublees, [],
            f"le domaine est collé à une URL déjà absolue : {doublees[:3]}")

    def test_chaque_adresse_annoncee_est_servie(self):
        """Le sitemap ne doit pas promettre ce que les vues refusent — c'est le
        défaut qu'on avait déjà entre `slugs_contenu` et les vues publiques.

        Restreint aux routes que `content.urls` sert lui-même. Les
        `ContentPage` en sont exclues à dessein : leur adresse dépend de
        l'arbre Wagtail et de l'enregistrement `Site`, que les fabriques de
        test ne fixent pas — l'assertion réussissait ou échouait selon les
        classes ayant tourné avant, dans le même processus. Un test qui dépend
        de son ordre d'exécution ne dit plus rien de vrai sur le code.

        En production, la vérification a été faite sur les vraies adresses :
        25 tirées au hasard du sitemap servi, toutes en 200 (27/08/2026).
        """
        from urllib.parse import urlparse
        chemins = [urlparse(a).path for a in self._adresses()]
        verifiables = [c for c in chemins
                       if c.startswith(('/article/', '/categorie/'))]
        self.assertTrue(verifiables, "aucune adresse vérifiable dans le sitemap")
        for chemin in verifiables:
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    self.client.get(chemin).status_code, 200,
                    f"annoncée au sitemap mais non servie : {chemin}")

    def test_le_contenu_dun_syndicat_depublie_nest_pas_annonce(self):
        """Dépublier ferme le site du syndicat ; le sitemap principal
        continuait pourtant d'annoncer ses articles (Rhône-Alpes, 32 articles
        le 27/08/2026)."""
        ferme = make_site(slug='ferme', name='CNT-SO Fermé', site_type='regional')
        make_article_page(section_slug='ferme', title='Article fermé',
                          slug='article-ferme')
        ferme.live = False
        ferme.save()
        self.assertNotIn('article-ferme', ' '.join(self._adresses()))


class ChampsDeSaisieNommesTest(TestCase):
    """Tout champ de saisie doit avoir un nom lisible par un lecteur d'écran.

    Le cartouche d'inscription à la newsletter existe en cinq exemplaires —
    `_sidebar`, `_sidebar_cta`, `_sectoral_sidebar`, `_newsletter`,
    `qui_sommes_nous`. Trois portaient `aria-label`, deux l'avaient perdu à la
    recopie (relevé le 27/08/2026) : sur la page d'un article, le champ
    n'annonçait que « votre@email.fr ». Un `placeholder` n'est pas une
    étiquette — il disparaît à la saisie, et les lecteurs d'écran ne le
    traitent pas uniformément.

    Le test balaie le HTML rendu plutôt que les gabarits : c'est ce que le
    visiteur reçoit qui compte, et un sixième cartouche ajouté demain sans
    étiquette échouera ici.
    """

    #: Champs légitimement sans étiquette : le piège à robots est masqué aux
    #: technologies d'assistance (`aria-hidden`, `tabindex="-1"`), lui en
    #: donner une le rendrait visible à ceux-là mêmes qu'il protège.
    EXEMPTS = ('site_web',)

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        make_article_page(section_slug='principal', title='Un article',
                          slug='un-article')

    def _sans_nom(self, url):
        html = self.client.get(url).content.decode('utf-8', 'replace')
        muets = []
        for m in re.finditer(r'<(input|select|textarea)\b([^>]*)>', html, re.I):
            attrs = m.group(2)
            if re.search(r'type\s*=\s*["\'](hidden|submit|button|image)', attrs, re.I):
                continue
            if re.search(r'\baria-hidden\s*=\s*["\']true', attrs, re.I):
                continue
            nom = re.search(r'\bname\s*=\s*["\']([^"\']+)', attrs)
            if nom and nom.group(1) in self.EXEMPTS:
                continue
            if re.search(r'\b(aria-label|aria-labelledby|title)\s*=', attrs, re.I):
                continue
            ident = re.search(r'\bid\s*=\s*["\']([^"\']+)', attrs)
            if ident and f'for="{ident.group(1)}"' in html:
                continue
            muets.append(re.sub(r'\s+', ' ', m.group(0))[:80])
        return muets

    def test_les_pages_publiques_nont_aucun_champ_muet(self):
        for url in ('/', '/article/un-article/', '/contact/',
                    '/newsletter/desabonnement/'):
            with self.subTest(url=url):
                muets = self._sans_nom(url)
                self.assertEqual(
                    muets, [],
                    f"champ(s) sans nom accessible sur {url} — un placeholder "
                    f"n'est pas une étiquette : {muets}")


class ReglagesSansDecorTest(TestCase):
    """Une application réglée mais jamais branchée fait croire à un dispositif.

    `wagtail-cache` a vécu ainsi : présent dans `INSTALLED_APPS`, réglé
    (`WAGTAILCACHE_CACHE`, `WAGTAILCACHE_TIMEOUT = 3600`), cité dans CLAUDE.md
    comme intégration clé — et ses middlewares absents de `MIDDLEWARE`. Aucune
    page n'a jamais été mise en cache, et la production le confirmait : pas un
    en-tête `X-Wagtail-Cache` (audit du 27/08/2026).

    Ce test ne réclame pas de cache. Il exige seulement que les réglages et le
    branchement disent la même chose, dans un sens comme dans l'autre.
    """

    def test_le_cache_de_pages_est_soit_branche_soit_absent(self):
        from django.conf import settings
        declare = 'wagtailcache' in settings.INSTALLED_APPS
        branche = any('wagtailcache' in m for m in settings.MIDDLEWARE)
        self.assertEqual(
            declare, branche,
            "wagtail-cache est déclaré sans être branché (ou l'inverse) : "
            "soit ajouter ses middlewares Update/FetchFromCache, soit le "
            "retirer d'INSTALLED_APPS. Attention, la production tourne à trois "
            "workers : un cache mémoire ne serait purgé que sur l'un d'eux.")

    def test_aucun_reglage_ne_survit_a_lapplication_retiree(self):
        from django.conf import settings
        if 'wagtailcache' in settings.INSTALLED_APPS:
            self.skipTest("wagtail-cache est de retour : ce test ne s'applique plus.")
        orphelins = [c for c in dir(settings) if c.startswith('WAGTAILCACHE')]
        self.assertEqual(
            orphelins, [],
            f"réglages sans application pour les porter : {orphelins}")


class SlugHeriteServiParLesVuesTest(TestCase):
    """Le sitemap listait des adresses que les vues renvoyaient en 404.

    `SectionPage.slugs_contenu` existe parce que quelques syndicats ont un slug
    WordPress hérité différent du slug Wagtail (Numérique « stnum »,
    Éducation « fter ») et que leurs contenus anciens portent celui-là. Sa
    docstring affirme « tout filtre `section_slug` passe désormais par ici ».

    C'était faux : les flux et les trois sitemaps l'utilisaient, les vues
    publiques filtraient sur le seul slug Wagtail. Un article hérité était donc
    annoncé aux moteurs de recherche et introuvable quand on suivait le lien —
    les deux ne pouvaient pas avoir raison en même temps (audit du 26/08/2026).
    """

    def setUp(self):
        self.site = make_site(slug='numerique', name='CNT-SO Numérique',
                              site_type='sectoral')
        self.site.legacy_site_slug = 'stnum'
        self.site.save()
        self.ancien = make_article_page(section_slug='stnum', title='Article hérité',
                                        slug='article-herite')

    def test_le_sitemap_et_la_vue_sont_daccord(self):
        from content.sitemaps import SectionArticleSitemap
        annonces = {a.slug for a in SectionArticleSitemap(self.site).items()}
        self.assertIn('article-herite', annonces)
        r = self.client.get('/numerique/article/article-herite/')
        self.assertEqual(r.status_code, 200,
                         "le sitemap l'annonce, la vue doit le servir")

    def test_larticle_herite_apparait_dans_la_liste_du_syndicat(self):
        r = self.client.get('/numerique/')
        self.assertContains(r, 'Article hérité')

    def test_une_categorie_heritee_est_servie(self):
        make_cms_category(name='Droits', slug='droits-h', section_slug='stnum')
        r = self.client.get('/numerique/categorie/droits-h/')
        self.assertEqual(r.status_code, 200)

    def test_le_contenu_du_voisin_reste_hors_de_portee(self):
        """Élargir le périmètre ne doit pas ouvrir celui d'à côté."""
        make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        make_article_page(section_slug='marseille', title='Chez le voisin',
                          slug='chez-le-voisin')
        self.assertEqual(
            self.client.get('/numerique/article/chez-le-voisin/').status_code, 404)


class SlugHeriteSansCollisionTest(TestCase):
    """Un slug hérité ne peut pas être le slug Wagtail d'un autre syndicat.

    `slugs_contenu` sert de périmètre à tous les filtres publics depuis
    l'harmonisation : si le slug hérité de A était le slug de B, A servirait le
    contenu de B sous sa propre adresse. Le cas n'existe pas — seul
    « numerique » a un slug hérité — et il ne doit pas pouvoir être créé.
    """

    def test_la_collision_est_refusee(self):
        from django.core.exceptions import ValidationError
        make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        autre = make_site(slug='paris', name='CNT-SO Paris', site_type='regional')
        autre.legacy_site_slug = 'marseille'
        with self.assertRaises(ValidationError) as leve:
            autre.clean()
        self.assertIn('legacy_site_slug', leve.exception.message_dict)

    def test_un_slug_herite_libre_passe(self):
        site = make_site(slug='numerique', name='CNT-SO Numérique',
                         site_type='sectoral')
        site.legacy_site_slug = 'stnum'
        site.clean()   # ne doit rien lever

    def test_le_slug_herite_egal_au_sien_passe(self):
        site = make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        site.legacy_site_slug = 'marseille'
        site.clean()


class SuppressionAbonneRetireDeOvhTest(TestCase):
    """Supprimer un abonné doit aussi le retirer des listes OVH.

    Arnaud, 27/08/2026 : « y a pas moyen de mettre un garde-fou pour ça ? ».
    L'asymétrie était réelle : *désactiver* quelqu'un le retirait bien — le
    signal `post_save` s'en charge — mais le *supprimer* ne retirait rien.
    L'objet disparaissait, aucun signal de mise à jour ne partait, et l'adresse
    restait chez OVH : elle continuait de recevoir la lettre, sans plus aucune
    trace de consentement en base pour l'expliquer.

    Le geste est à portée de clic : un rédacteur a le droit de supprimer un
    abonné depuis /cms/.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        self.site.ovh_mailing_list = 'news3'
        self.site.save()

    def test_la_suppression_retire_des_listes(self):
        abo = Subscriber.objects.create(site=self.site, email='partante@example.org',
                                        is_active=True, ovh_list='news3')
        with patch('content.ovh_sync.ovh_unsubscribe') as retirer:
            abo.delete()
        retirer.assert_called_once()
        self.assertEqual(retirer.call_args[0][1], 'partante@example.org')

    def test_elle_ne_touche_pas_a_qui_est_arrive_par_un_autre_chemin(self):
        """Une adresse peut être sur une liste sans que le site l'y ait mise :
        les 5 895 adresses héritées du WordPress n'ont aucune ligne ici.

        Cas réel du 27/08/2026 : `julien.huard@cnt-so.org` avait une ligne
        d'essai datée de mars ET une inscription légitime sur `news2` depuis
        l'import. Supprimer la ligne d'essai devait le laisser sur news2.
        """
        abo = Subscriber.objects.create(site=self.site, is_active=True,
                                        email='historique@example.org',
                                        ovh_list='')   # le site ne l'a jamais posé
        with patch('content.ovh_sync.ovh_unsubscribe') as retirer:
            abo.delete()
        retirer.assert_not_called()

    def test_la_suppression_en_masse_aussi(self):
        """Enregistrer un récepteur `pre_delete` désactive le « fast delete »
        de Django : une suppression par queryset passe donc aussi par là."""
        for i in range(3):
            Subscriber.objects.create(site=self.site, email=f'lot{i}@example.org',
                                      is_active=True, ovh_list='news3')
        with patch('content.ovh_sync.ovh_unsubscribe') as retirer:
            Subscriber.objects.filter(email__startswith='lot').delete()
        self.assertEqual(retirer.call_count, 3)

    def test_labonne_confederal_du_webhook_est_retire_lui_aussi(self):
        """Il porte `site=None` : sans redirection vers le principal, la
        suppression ne balaierait aucune liste."""
        abo = Subscriber.objects.create(site=None, email='adherente@example.org',
                                        is_active=True, ovh_list='news3')
        with patch('content.ovh_sync.ovh_unsubscribe') as retirer:
            abo.delete()
        retirer.assert_called_once()


class DesactivationSuitLeRoutageTest(TestCase):
    """Désactiver un abonné doit balayer la liste qui le porte VRAIMENT.

    Le signal visait les listes du syndicat d'inscription. Or un syndicat sans
    liste envoie ses inscrits sur celles de la confédération : désactiver un
    abonné de Marseille balayait une liste vide et le laissait sur `news3`.
    Même angle mort que celui trouvé dans `verifie_abonnes_ovh`.
    """

    def setUp(self):
        principal = make_site(slug='principal', name='CNT-SO')
        principal.ovh_mailing_list = 'news3'
        principal.save()
        self.marseille = make_site(slug='13', name='CNT-SO 13',
                                   site_type='regional')

    def test_la_desactivation_balaie_les_listes_de_la_confederation(self):
        abo = Subscriber.objects.create(site=self.marseille, is_active=True,
                                        email='marseillaise@example.org')
        with patch('content.ovh_sync.ovh_unsubscribe') as retirer:
            abo.is_active = False
            abo.save(update_fields=['is_active'])
        retirer.assert_called_once()
        vise = retirer.call_args[0][0]
        self.assertEqual(
            vise.slug, 'principal',
            "le retrait doit viser les listes qui portent réellement l'adresse")


class VerifieAbonnesOvhTest(TestCase):
    """Détecter les abonnés que le site croit inscrits et qu'OVH ne connaît pas.

    La newsletter part vers les listes OVH : une personne absente des listes
    ne reçoit rien, même si le site lui a affiché « inscription confirmée ».
    Rien ne permettait de repérer ce cas — `ovh_subscribe` échoue en rendant
    `None`, la ligne locale reste active, et personne ne le sait.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        self.site.ovh_mailing_list = 'news3'
        self.site.save()

    def _lancer(self, chez_ovh, **options):
        from django.core.management import call_command
        sortie = StringIO()
        with patch('cms.ovh_client.get_subscribers', return_value=chez_ovh):
            call_command('verifie_abonnes_ovh', stdout=sortie,
                         stderr=StringIO(), **options)
        return sortie.getvalue()

    def test_un_abonne_absent_des_listes_est_denonce(self):
        Subscriber.objects.create(site=self.site, email='oubliee@example.org',
                                  is_active=True)
        rapport = self._lancer(chez_ovh=[])
        self.assertIn('oubliee@example.org', rapport)
        self.assertIn('jamais posé', rapport)
        self.assertIn('ne reçoivent RIEN', rapport)

    def test_un_abonne_present_ne_lest_pas(self):
        Subscriber.objects.create(site=self.site, email='presente@example.org',
                                  is_active=True)
        rapport = self._lancer(chez_ovh=['Presente@Example.org'])
        self.assertNotIn('presente@example.org', rapport)
        self.assertIn('Aucun abonné manquant', rapport)

    def test_labonne_confederal_du_webhook_est_compte(self):
        """Il porte `site=None` : l'oublier laisserait la moitié des abonnés
        de la confédération hors de la vérification."""
        Subscriber.objects.create(site=None, email='adherente@example.org',
                                  is_active=True)
        rapport = self._lancer(chez_ovh=[])
        self.assertIn('adherente@example.org', rapport)

    def test_un_abonne_inactif_nest_pas_attendu_chez_ovh(self):
        Subscriber.objects.create(site=self.site, email='sortie@example.org',
                                  is_active=False)
        rapport = self._lancer(chez_ovh=[])
        self.assertNotIn('sortie@example.org', rapport)

    def test_une_liste_illisible_ne_denonce_personne(self):
        """Sans la liste, tout paraîtrait manquant : dénoncer des absents qui
        n'en sont pas ferait réinscrire tout le monde en double."""
        Subscriber.objects.create(site=self.site, email='inconnue@example.org',
                                  is_active=True)
        from django.core.management import call_command
        sortie, erreurs = StringIO(), StringIO()
        with patch('cms.ovh_client.get_subscribers', side_effect=OSError('API HS')):
            call_command('verifie_abonnes_ovh', stdout=sortie, stderr=erreurs)
        self.assertNotIn('inconnue@example.org', sortie.getvalue())
        self.assertIn('listes illisibles', erreurs.getvalue())

    def test_labonne_dun_syndicat_sans_liste_est_verifie_aussi(self):
        """C'est là que les orphelins s'accumulent, pas ailleurs.

        Un syndicat sans liste OVH n'envoie pas dans le vide : ses inscrits
        vont sur les listes de la confédération (`site_de_diffusion`).
        La première version de cette commande sautait ces syndicats — et
        annonçait donc « aucun abonné manquant » alors que deux inscrits de
        Marseille, de mars 2026, n'étaient sur AUCUNE liste (constaté en
        production le 27/08/2026).
        """
        marseille = make_site(slug='13', name='CNT-SO 13', site_type='regional')
        self.assertEqual(marseille.ovh_mailing_list, '',
                         "ce test n'a de sens que sur un syndicat sans liste")
        Subscriber.objects.create(site=marseille, email='oubliee-13@example.org',
                                  is_active=True)
        rapport = self._lancer(chez_ovh=[])
        self.assertIn('oubliee-13@example.org', rapport)
        self.assertIn('CNT-SO 13', rapport)

    def test_reparer_reinscrit_et_note_la_liste(self):
        abo = Subscriber.objects.create(site=self.site, email='a@example.org',
                                        is_active=True)
        with patch('content.ovh_sync.ovh_subscribe', return_value='news3') as poser:
            self._lancer(chez_ovh=[], reparer=True)
        poser.assert_called_once()
        abo.refresh_from_db()
        self.assertEqual(abo.ovh_list, 'news3')

    def test_sans_reparer_rien_nest_touche(self):
        abo = Subscriber.objects.create(site=self.site, email='b@example.org',
                                        is_active=True)
        with patch('content.ovh_sync.ovh_subscribe') as poser:
            self._lancer(chez_ovh=[])
        poser.assert_not_called()
        abo.refresh_from_db()
        self.assertEqual(abo.ovh_list, '')


class ContactNonRemisTest(TestCase):
    """Un message de contact qui ne part pas doit laisser une trace.

    `_send_contact_email` appelait `send(fail_silently=True)` dans un
    `try/except Exception: pass`. Les deux ensemble : l'échec ne levait rien,
    ne journalisait rien, ne comptait rien. Un serveur SMTP qui refuse les
    envois affichait donc « message envoyé » à tous les visiteurs pendant des
    mois, sans que le syndicat reçoive quoi que ce soit ni sache pourquoi.

    Le `fail_silently` reste voulu : le message est enregistré en base et
    lisible dans /cms/, il ne faut pas répondre une 500 à quelqu'un dont la
    demande est bien arrivée. C'est le silence côté journal qui était fautif.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        self.site.contact_email = 'syndicat@example.org'
        self.site.save()
        self.message = ContactMessage.objects.create(
            site=self.site, name='Dupont', first_name='Camille',
            email='camille@example.org', message='Question sur mon contrat.')

    def _envoyer(self):
        from content.views import _send_contact_email
        return _send_contact_email(self.site, self.message)

    def test_un_envoi_reussi_est_annonce_comme_tel(self):
        from django.core import mail
        self.assertTrue(self._envoyer())
        self.assertEqual(len(mail.outbox), 1)

    def test_un_echec_est_journalise_avec_le_destinataire(self):
        with patch('content.views.EmailMultiAlternatives.send', return_value=0):
            with self.assertLogs('content.views', level='ERROR') as journal:
                remis = self._envoyer()
        self.assertFalse(remis)
        trace = '\n'.join(journal.output)
        self.assertIn('syndicat@example.org', trace)
        self.assertIn(str(self.message.pk), trace,
                      "le numéro du message manque : impossible de le retrouver "
                      "dans /cms/ à partir du journal")

    def test_une_exception_ne_remonte_pas_au_visiteur(self):
        """Sa demande est enregistrée : lui répondre une 500 serait faux."""
        with patch('content.views.EmailMultiAlternatives.send',
                   side_effect=OSError('SMTP injoignable')):
            with self.assertLogs('content.views', level='ERROR'):
                self.assertFalse(self._envoyer())


class ConfirmationNonRemiseTest(TestCase):
    """Une inscription dont le courriel de confirmation échoue.

    La page suivante annonce « regardez votre boîte » ; sans le lien, la
    personne ne confirme jamais et reste inactive. L'échec était avalé par un
    `except Exception: pass`, donc invisible des deux côtés.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO')
        from django.core.cache import caches
        caches['limites'].clear()

    @patch('hcaptcha.fields.hCaptchaField.validate', return_value=True)
    def test_lechec_est_journalise_avec_ladresse(self, _captcha):
        with patch('content.views.EmailMultiAlternatives.send',
                   side_effect=OSError('SMTP injoignable')):
            with self.assertLogs('content.views', level='ERROR') as journal:
                r = self.client.post('/newsletter/inscription/valider/', {
                    'email': 'perdue@example.org', 'name': '',
                    'h-captcha-response': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('perdue@example.org', '\n'.join(journal.output))


class AbonneConfederalTest(TestCase):
    """`site` est nul pour les abonnés venus de cnt-adhesion.

    C'est la convention du webhook (`_sync_sub(email, site=None, …)`), que
    `cms/apps.py` traduit en « listes du site principal ». Le `__str__` du
    modèle lisait pourtant `self.site.name` sans garde : afficher un tel
    abonné — liste des snippets, journal, page de suppression — levait une
    AttributeError et rendait une 500.
    """

    def test_son_nom_saffiche_sans_planter(self):
        abo = Subscriber(email='adherente@example.org', site=None)
        self.assertIn('adherente@example.org', str(abo))

    def test_il_est_annonce_comme_confederal(self):
        self.assertIn('Confédération', str(Subscriber(email='x@y.fr', site=None)))

    def test_labonne_dun_syndicat_porte_toujours_son_nom(self):
        site = make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        self.assertIn('CNT-SO 13', str(Subscriber(email='x@y.fr', site=site)))


class NewsletterDesabonnementTest(TestCase):
    """La sortie doit exister, et fonctionner.

    Le lien « Se désabonner » du pied de chaque newsletter pointait vers
    `/newsletter/inscription/`, une vue en POST seul : il répondait 405.
    Sans porte de sortie, le seul geste restant est « signaler comme
    indésirable » — le pire signal pour la délivrabilité.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        from django.core.cache import caches
        caches['limites'].clear()

    def test_la_page_repond_en_get(self):
        r = self.client.get('/newsletter/desabonnement/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Se désabonner')

    def test_elle_renvoie_au_formulaire_et_pas_a_une_adresse(self):
        """Décision d'Arnaud du 26/08/2026, dans la ligne du pied de page :
        l'adresse en clair exposait la boîte aux moissonneurs, et elle était
        écrite en dur — un adhérent du STUCS y lisait celle de la conf."""
        r = self.client.get('/newsletter/desabonnement/')
        self.assertNotContains(r, 'mailto:')
        self.assertContains(r, 'formulaire de contact')
        self.assertContains(r, 'href="/contact/"')

    def test_sur_un_syndicat_le_lien_mene_a_son_formulaire(self):
        make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        r = self.client.get('/marseille/newsletter/desabonnement/')
        self.assertContains(r, '/marseille/contact/')
        self.assertNotContains(r, 'mailto:')

    def test_sur_un_domaine_autonome_le_slug_ne_se_repete_pas(self):
        """Même piège que le bouton du tract et l'écran « Pages du syndicat » :
        bâti par un simple `reverse`, le lien porte le slug en préfixe et un
        syndicat à domaine autonome renvoie son lecteur chez la conf."""
        # Fonction de module depuis le 02/09/2026 : la page d'adhésion en
        # attente en avait besoin à son tour, et son commentaire disait déjà
        # « on ne l'ajoute pas une troisième fois ».
        from content.views import url_contact_du_syndicat
        site = make_site(slug='stucs', name='CNT-SO STUCS', site_type='sectoral')
        site.custom_domain = 'stucs.cnt-so.org'
        site.save()
        url = url_contact_du_syndicat(site)
        self.assertEqual(url, 'https://stucs.cnt-so.org/contact/')
        self.assertNotIn('/stucs/contact', url)

    def test_le_message_de_quota_ne_donne_plus_dadresse(self):
        from content.views import NEWSLETTER_MAX_DESABO_PAR_IP
        with patch('content.ovh_sync.ovh_unsubscribe'):
            for i in range(NEWSLETTER_MAX_DESABO_PAR_IP):
                self.client.post('/newsletter/desabonnement/', {'email': f'a{i}@example.org'})
            r = self.client.post('/newsletter/desabonnement/', {'email': 'tardive@example.org'})
        self.assertContains(r, 'Trop de demandes')
        self.assertNotContains(r, 'contact@cnt-so.org')

    def test_elle_nest_pas_indexee(self):
        """Elle est liée depuis chaque newsletter, et n'a rien à faire dans un
        moteur de recherche — comme le tract, qui portait déjà son noindex."""
        r = self.client.get('/newsletter/desabonnement/')
        self.assertContains(r, 'name="robots" content="noindex')

    def test_le_get_ne_desabonne_personne(self):
        """Les filtres antispam préchargent les liens du header
        `List-Unsubscribe` : un GET qui agirait viderait la liste tout seul."""
        abo = Subscriber.objects.create(site=self.site, email='intacte@example.org',
                                        is_active=True)
        self.client.get('/newsletter/desabonnement/?email=intacte@example.org')
        abo.refresh_from_db()
        self.assertTrue(abo.is_active)

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_le_desabonnement_retire_des_listes_ovh(self, retirer):
        r = self.client.post('/newsletter/desabonnement/',
                             {'email': 'Sortante@Example.org'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'sortante@example.org')
        retirer.assert_called_once()
        self.assertEqual(retirer.call_args[0][1], 'sortante@example.org')

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_le_desabonnement_desactive_la_ligne_locale(self, retirer):
        abo = Subscriber.objects.create(site=self.site, email='sortante@example.org',
                                        is_active=True)
        self.client.post('/newsletter/desabonnement/', {'email': 'sortante@example.org'})
        abo.refresh_from_db()
        self.assertFalse(abo.is_active)

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_il_eteint_aussi_labonne_venu_de_ladhesion(self, retirer):
        """Un abonné confédéral existe sous deux formes, et la sortie doit
        éteindre les deux.

        Le formulaire du site enregistre `site=<principal>` ; le webhook
        cnt-adhesion, lui, `site=None` — convention que `cms/apps.py` traduit
        en « listes du principal ». Ne filtrer que sur la première laissait la
        seconde active : cnt-adhesion repousse les préférences à chaque
        encaissement et réinscrivait la personne au prélèvement suivant. Sa
        sortie ne tenait qu'un mois.
        """
        adhesion = Subscriber.objects.create(site=None, email='adherente@example.org',
                                             is_active=True)
        self.client.post('/newsletter/desabonnement/', {'email': 'adherente@example.org'})
        adhesion.refresh_from_db()
        self.assertFalse(adhesion.is_active)

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_la_casse_de_ladresse_nempeche_pas_la_sortie(self, retirer):
        """Le webhook n'abaisse pas la casse, cette vue si : une ligne
        « Jean.Dupont@… » n'était jamais retrouvée."""
        abo = Subscriber.objects.create(site=self.site, email='Jean.Dupont@Example.org',
                                        is_active=True)
        self.client.post('/newsletter/desabonnement/', {'email': 'jean.dupont@example.org'})
        abo.refresh_from_db()
        self.assertFalse(abo.is_active)

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_il_ne_touche_pas_a_labonne_dun_autre_syndicat(self, retirer):
        """Le repêchage de `site=None` ne doit pas devenir un « tout éteindre »."""
        autre = make_site(slug='marseille', name='CNT-SO 13', site_type='regional')
        ailleurs = Subscriber.objects.create(site=autre, email='partagee@example.org',
                                             is_active=True)
        self.client.post('/newsletter/desabonnement/', {'email': 'partagee@example.org'})
        ailleurs.refresh_from_db()
        self.assertTrue(ailleurs.is_active)

    def test_adresse_invalide_reaffiche_le_formulaire(self):
        r = self.client.post('/newsletter/desabonnement/', {'email': 'pas-une-adresse'})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "C&#x27;est fait")

    @patch('content.ovh_sync.ovh_unsubscribe')
    def test_la_limite_le_dit_au_lieu_de_faire_semblant(self, retirer):
        """Annoncer un retrait qui n'a pas eu lieu renverrait vers « indésirable »."""
        from content.views import NEWSLETTER_MAX_DESABO_PAR_IP
        for i in range(NEWSLETTER_MAX_DESABO_PAR_IP):
            self.client.post('/newsletter/desabonnement/', {'email': f'a{i}@example.org'})
        r = self.client.post('/newsletter/desabonnement/', {'email': 'tardive@example.org'})
        self.assertContains(r, 'Trop de demandes')
        self.assertNotIn('tardive@example.org',
                         [c[0][1] for c in retirer.call_args_list])


def _navigateur():
    """Le binaire Chrome/Chromium de cette machine, ou None.

    Le tract est mis en pages par du JavaScript : sa seule vérification
    honnête passe par un navigateur. Là où il n'y en a pas — un serveur
    d'intégration nu —, les tests concernés sont sautés plutôt que rendus
    faux : mieux vaut un test annoncé absent qu'un test vert qui ne mesure
    rien. C'était le défaut des assertions précédentes, qui cherchaient des
    littéraux dans le gabarit.
    """
    import glob
    import shutil
    for nom in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable'):
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    trouves = sorted(glob.glob(
        os.path.expanduser('~/.cache/puppeteer/chrome/*/chrome-linux64/chrome')))
    return trouves[-1] if trouves else None


def _pages_du_tract(test, url):
    """Le nombre de pages A4 que le tract produit réellement.

    On rend la page, on la confie à Chrome sans interface, et on lit
    l'attribut `data-pages` que le script pose une fois la répartition faite.
    """
    import subprocess
    import tempfile

    chrome = _navigateur()
    if not chrome:
        test.skipTest("Aucun Chrome/Chromium : la mise en pages du tract ne "
                      "peut pas être mesurée sur cette machine.")
    html = test.client.get(url).content
    with tempfile.TemporaryDirectory() as dossier:
        fichier = os.path.join(dossier, 'tract.html')
        with open(fichier, 'wb') as f:
            f.write(html)
        # Pas de `--user-data-dir` : ce Chrome (150) reste pendu indéfiniment
        # quand on lui en impose un, profil pré-créé ou non — mesuré le
        # 26/08/2026. Le profil par défaut convient, `--dump-dom` n'écrit rien.
        try:
            sortie = subprocess.run(
                [chrome, '--headless', '--disable-gpu', '--no-sandbox',
                 '--virtual-time-budget=5000', '--dump-dom', f'file://{fichier}'],
                capture_output=True, text=True, timeout=60,
            ).stdout
        except subprocess.TimeoutExpired:
            # Ne pas transformer ça en test sauté : une mise en pages qui ne
            # rend jamais la main est précisément le défaut à attraper.
            test.fail("Le navigateur n'a pas rendu la main en 60 s : la mise "
                      "en pages du tract ne termine pas.")
    trouve = re.search(r'data-pages="(\d+)"', sortie)
    test.assertIsNotNone(
        trouve, "Le script du tract n'a pas fini sa mise en pages : aucun "
                "`data-pages` sur le <body>.")
    return int(trouve.group(1))


class FichePratiqueTractTest(TestCase):
    """« Un format de fiche pratique que les gens peuvent aussi télécharger en
    format tract pour afficher dans leur boîte » (Arnaud, 18/08/2026).

    Le tract est la même fiche en A4 noir et blanc : c'est le navigateur qui en
    fait un PDF, aucune bibliothèque n'ayant à être installée sur le serveur.
    """

    def setUp(self):
        self.site = _ensure_section_page(slug='tract-site', name='Tract Site',
                                         site_type='sectoral')
        self.cat = make_cms_category(name='Nos droits', slug='droit-tract',
                                     section_slug='tract-site')
        self.fiche = make_article_page(
            section_slug='tract-site', title='Forfait jours', slug='forfait-jours',
            categories=[self.cat], excerpt='Un chapeau.', fiche_pratique=True)
        self.breve = make_article_page(
            section_slug='tract-site', title='Une brève', slug='une-breve',
            categories=[self.cat])

    def test_le_tract_repond_pour_une_fiche_pratique(self):
        r = self.client.get('/tract-site/article/forfait-jours/tract/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Forfait jours')

    def test_un_article_ordinaire_na_pas_de_tract(self):
        """Sans cette garde, chaque brève aurait une adresse fantôme."""
        r = self.client.get('/tract-site/article/une-breve/tract/')
        self.assertEqual(r.status_code, 404)

    def test_le_bouton_napparait_que_sur_une_fiche_pratique(self):
        r = self.client.get('/tract-site/article/forfait-jours/')
        self.assertContains(r, 'Télécharger le tract')
        r2 = self.client.get('/tract-site/article/une-breve/')
        self.assertNotContains(r2, 'Télécharger le tract')

    def test_le_tract_est_calibre_a4_et_ne_simprime_pas_avec_sa_barre(self):
        r = self.client.get('/tract-site/article/forfait-jours/tract/')
        html = r.content.decode()
        self.assertIn('size: A4', html)
        self.assertIn('.barre { display: none', html)

    def test_le_tract_porte_le_syndicat_et_son_contact(self):
        self.site.contact_email = 'tract@cnt-so.org'
        self.site.save()
        r = self.client.get('/tract-site/article/forfait-jours/tract/')
        self.assertContains(r, 'Tract Site')
        self.assertContains(r, 'tract@cnt-so.org')

    def test_le_tract_nest_pas_indexe(self):
        """C'est la même fiche que l'article : deux adresses indexées se
        feraient concurrence dans les moteurs."""
        r = self.client.get('/tract-site/article/forfait-jours/tract/')
        self.assertContains(r, 'name="robots" content="noindex"')

    def test_un_article_dun_autre_syndicat_nest_pas_servi_ici(self):
        autre = _ensure_section_page(slug='tract-autre', name='Autre',
                                     site_type='sectoral')
        r = self.client.get('/tract-autre/article/forfait-jours/tract/')
        self.assertEqual(r.status_code, 404)


class TractCouleurEtDeuxPagesTest(TestCase):
    """Le tract sort en couleur, et tient en deux pages.

    « Fais des tracts en couleur, si les gens veulent les imprimer en n&b ils
    choisiront » puis « le tract ne peut pas faire 2,5 pages, ça n'a pas de
    sens, 1 ou 2 pages max » (Arnaud, 18/08/2026).
    """

    def setUp(self):
        self.site = _ensure_section_page(slug='tract-couleur', name='Tract Couleur',
                                         site_type='sectoral')
        self.cat = make_cms_category(name='Nos droits', slug='droit-couleur',
                                     section_slug='tract-couleur')
        self.fiche = make_article_page(
            section_slug='tract-couleur', title='Fiche', slug='fiche-couleur',
            categories=[self.cat], fiche_pratique=True)
        self.url = '/tract-couleur/article/fiche-couleur/tract/'

    def test_le_tract_sort_en_couleur(self):
        html = self.client.get(self.url).content.decode()
        # Le rouge de la charte, et l'instruction sans laquelle les navigateurs
        # suppriment les aplats à l'impression.
        self.assertIn('#E81C24', html)
        self.assertIn('print-color-adjust: exact', html)

    def test_le_noir_et_blanc_reste_au_choix_de_qui_imprime(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('noir et blanc', html)
        self.assertNotIn('filter: grayscale', html)

    def test_le_tract_fait_une_page_ou_deux_jamais_un_entre_deux(self):
        """« Il ne peut pas faire 1,7 page, ça n'existe pas » (Arnaud).

        Mesuré dans un vrai navigateur, pas cherché dans la source. Ce test
        vérifiait auparavant que la chaîne « PAGES_VISEES = [1, 2] » figurait
        dans le gabarit : il serait resté vert avec une pagination cassée, et
        rouge sur un simple changement d'espacement.
        """
        pages = _pages_du_tract(self, self.url)
        self.assertIn(pages, (1, 2),
                      f'Le tract sort en {pages} pages : ni une, ni deux.')

    def test_une_fiche_longue_est_comprimee_a_deux_pages(self):
        """L'exigence, c'est le cas long : une fiche courte tient de toute
        façon sur une page, et un test qui n'utilise qu'elle resterait vert
        avec la pagination cassée. Ici le texte déborde largement une A4 : le
        script doit réduire le corps jusqu'à le faire tenir en deux, pas
        ouvrir une troisième feuille.
        """
        from wagtail.blocks.stream_block import StreamValue
        paragraphe = (
            "<h2>Ce que dit la loi</h2><p>" + ("Le forfait jours n'est licite "
            "qu'encadré par un accord collectif qui fixe le suivi de la charge "
            "de travail. ") * 12 + "</p>"
        )
        self.fiche.body = StreamValue(
            self.fiche.body.stream_block,
            [('rich_text', paragraphe) for _ in range(9)], is_lazy=False)
        self.fiche.save_revision().publish()

        pages = _pages_du_tract(self, self.url)
        self.assertLessEqual(
            pages, 2,
            f"Une fiche longue sort en {pages} pages : le corps devait être "
            "réduit pour tenir en deux.")

    def test_le_tract_ferme_ses_pages(self):
        """Des feuilles closes, et un saut de page entre elles — sans quoi le
        PDF sort en bande continue (« j'ai encore une bande continue »)."""
        html = self.client.get(self.url).content.decode()
        self.assertIn('break-after: page', html)
        self.assertRegex(html, r'\.zone\s*\{[^}]*overflow:\s*hidden')

    def test_la_feuille_reste_A4_meme_sur_un_petit_ecran(self):
        """Une mise en page « mobile » changerait les hauteurs, et la
        pagination se calculerait sur une géométrie qui n'est pas celle de la
        feuille imprimée : c'est ce qui sortait un PDF de trois pages."""
        html = self.client.get(self.url).content.decode()
        self.assertIn('width: 210mm; height: 297mm;', html)
        # C'est l'affichage qu'on réduit, pas la feuille.
        self.assertIn("tract.style.transform = 'scale(", html)
        # …et cette réduction ne doit pas survivre à l'impression.
        self.assertIn('transform: none !important; height: auto !important;', html)


class TractAllegeTest(TestCase):
    """« Fais une version allégée du tract, enlève les sources juridiques mais
    rajoute le nom du syndicat et le contact » (Arnaud, 18/08/2026).

    Quinze références de jurisprudence font la crédibilité de l'article en
    ligne, pas celle d'une affiche : sur un panneau, elles ne servent qu'à
    manger la place.
    """

    def setUp(self):
        from wagtail.rich_text import RichText
        self.site = _ensure_section_page(slug='tract-allege', name='Tract Allégé',
                                         site_type='sectoral')
        self.cat = make_cms_category(name='Nos droits', slug='droit-allege',
                                     section_slug='tract-allege')
        self.fiche = make_article_page(
            section_slug='tract-allege', title='Fiche', slug='fiche-allegee',
            categories=[self.cat], fiche_pratique=True,
            body=[
                ('rich_text', RichText('<h2>Quoi faire</h2><p>Garde tes preuves.</p>')),
                ('rich_text', RichText('<h2>Sources</h2><p>Cass. soc. 11 mars 2025.</p>')),
            ])
        self.url_tract = '/tract-allege/article/fiche-allegee/tract/'
        self.url_web = '/tract-allege/article/fiche-allegee/'

    def test_le_tract_laisse_les_sources_de_cote(self):
        html = self.client.get(self.url_tract).content.decode()
        self.assertIn('Garde tes preuves', html)
        self.assertNotIn('Cass. soc. 11 mars 2025', html)

    def test_larticle_en_ligne_les_conserve(self):
        html = self.client.get(self.url_web).content.decode()
        self.assertIn('Cass. soc. 11 mars 2025', html)

    def test_le_pied_porte_le_nom_du_syndicat(self):
        html = self.client.get(self.url_tract).content.decode()
        self.assertIn('Tract Allégé', html)

    def test_le_pied_porte_le_contact_du_syndicat(self):
        self.site.contact_email = 'numerique@cnt-so.org'
        self.site.save()
        html = self.client.get(self.url_tract).content.decode()
        self.assertIn('numerique@cnt-so.org', html)

    def test_sans_contact_propre_le_tract_donne_celui_de_la_conf(self):
        """Un tract sans contact ne sert à rien : c'est par là qu'on rejoint."""
        self.site.contact_email = ''
        self.site.save()
        html = self.client.get(self.url_tract).content.decode()
        self.assertIn('contact@cnt-so.org', html)

    def test_seuls_les_titres_de_references_sont_ecartes(self):
        """« Six cas » et « Sourcing » ne doivent pas disparaître au passage."""
        from content.views import ArticleTractView
        from wagtail.rich_text import RichText
        from cms.models import ArticlePage as AP
        garde = make_article_page(
            section_slug='tract-allege', title='Garde', slug='fiche-garde',
            categories=[self.cat], fiche_pratique=True,
            body=[
                ('rich_text', RichText('<h2>Sourcing et recrutement</h2><p>A.</p>')),
                ('rich_text', RichText('<h2>Références</h2><p>B.</p>')),
                ('rich_text', RichText('<p>Sources : un paragraphe, pas un titre.</p>')),
            ])
        blocs = ArticleTractView._blocs_du_tract(AP.objects.get(pk=garde.pk))
        rendu = ' '.join(str(b.value) for b in blocs)
        self.assertIn('Sourcing et recrutement', rendu)
        self.assertIn('pas un titre', rendu)
        self.assertNotIn('<h2>Références</h2>', rendu)


class TractUrlSurLeBonDomaineTest(TestCase):
    """Le bouton du tract ne doit pas quitter le domaine du syndicat.

    Bâti par un simple `reverse`, il portait le slug en préfixe : sur
    numerique.cnt-so.org, « /numerique/article/…/tract/ » redirigeait vers
    newsite.cnt-so.org. Constaté en production le 18/08/2026, juste après la
    mise en ligne.
    """

    def setUp(self):
        self.site = _ensure_section_page(slug='tract-domaine', name='Tract Domaine',
                                         site_type='sectoral')
        self.cat = make_cms_category(name='Nos droits', slug='droit-domaine',
                                     section_slug='tract-domaine')
        self.article = make_article_page(
            section_slug='tract-domaine', title='Fiche', slug='fiche-domaine',
            categories=[self.cat], fiche_pratique=True)

    def test_sans_domaine_autonome_ladresse_est_relative(self):
        self.assertEqual(self.article.get_tract_url(),
                         '/tract-domaine/article/fiche-domaine/tract/')

    def test_avec_domaine_autonome_le_slug_ne_se_repete_pas(self):
        self.site.custom_domain = 'tract-domaine.cnt-so.org'
        self.site.save()
        url = self.article.get_tract_url()
        self.assertEqual(url, 'https://tract-domaine.cnt-so.org/article/fiche-domaine/tract/')
        self.assertNotIn('/tract-domaine/article/', url)

    def test_le_bouton_de_larticle_reprend_cette_adresse(self):
        """Le gabarit doit lire `get_tract_url`, pas refaire un `reverse`."""
        html = self.client.get('/tract-domaine/article/fiche-domaine/').content.decode()
        self.assertIn(self.article.get_tract_url(), html)
        self.assertIn('Télécharger le tract', html)


class TractSansAdresseEnDoubleTest(TestCase):
    """« Ne pas mettre l'adresse du syndicat plusieurs fois à côté » (Arnaud).

    Le pied affichait « numerique@cnt-so.org numerique.cnt-so.org » côte à
    côte — deux chaînes presque identiques — et le nom du syndicat figurait
    déjà dans l'en-tête.
    """

    def setUp(self):
        self.site = _ensure_section_page(slug='tract-double', name='Tract Double',
                                         site_type='sectoral')
        self.site.contact_email = 'double@cnt-so.org'
        self.site.custom_domain = 'double.cnt-so.org'
        self.site.save()
        self.cat = make_cms_category(name='Nos droits', slug='droit-double',
                                     section_slug='tract-double')
        make_article_page(section_slug='tract-double', title='Fiche',
                          slug='fiche-double', categories=[self.cat],
                          fiche_pratique=True)

    def _html(self):
        # Sur un domaine autonome, le chemin ne porte pas le slug : le demander
        # depuis testserver ne renverrait qu'une redirection.
        with override_settings(ALLOWED_HOSTS=['*']):
            r = self.client.get('/article/fiche-double/tract/',
                                SERVER_NAME='double.cnt-so.org')
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_le_nom_du_syndicat_napparait_quune_fois(self):
        self.assertEqual(self._html().count('Tract Double'), 1)

    def test_ladresse_e_mail_napparait_quune_fois(self):
        self.assertEqual(self._html().count('double@cnt-so.org'), 1)

    def test_le_domaine_nest_pas_colle_a_l_e_mail(self):
        """Ils sont séparés : le domaine en tête, le courriel en pied."""
        html = self._html()
        self.assertEqual(html.count('>double.cnt-so.org<'), 1)
        self.assertLess(html.index('>double.cnt-so.org<'), html.index('double@cnt-so.org'))


class SommaireNewsletterLisibleTest(TestCase):
    """« Comment je fais pour choisir les articles que je mets dedans ? »

    Arnaud a fini par trouver, ce qui est le symptôme : les trois champs d'un
    bloc avaient le même poids, et le geste central — choisir l'article — se
    lisait comme un réglage secondaire coincé entre deux autres.
    """

    def setUp(self):
        self.site = make_site(slug='principal')
        self.user = make_superuser()
        self.client.force_login(self.user)
        self.nl = Newsletter.objects.create(site=self.site, title='Lettre',
                                            intro='Bonjour')
        self.url = f'/cms/snippets/content/newsletter/edit/{self.nl.pk}/'

    def test_la_rubrique_vient_avant_larticle(self):
        html = self.client.get(self.url).content.decode()
        self.assertLess(html.index('nl-rubrique'), html.index('nl-article'))

    def test_le_choix_sans_rubrique_est_nomme(self):
        """Django affichait « --------- » : personne ne devinait qu'un article
        pouvait n'appartenir à aucune rubrique."""
        html = self.client.get(self.url).content.decode()
        self.assertIn('Sans titre de section', html)

    def test_on_lit_quune_rubrique_porte_plusieurs_articles(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("autant d&#x27;articles que voulu", html)

    def test_plusieurs_articles_tiennent_dans_une_meme_rubrique(self):
        """La question de fond : c'était déjà possible, ça ne se voyait pas."""
        from content.models import NewsletterArticle
        cat = make_cms_category(name='C', slug='c-nl', section_slug='principal')
        a1 = make_article_page(section_slug='principal', title='Un', slug='nl-un',
                               categories=[cat])
        a2 = make_article_page(section_slug='principal', title='Deux', slug='nl-deux',
                               categories=[cat])
        ajoute_a_la_newsletter(self.nl, a1, rubrique='campagne')
        ajoute_a_la_newsletter(self.nl, a2, rubrique='campagne')
        groupes = self.nl.par_rubrique()
        self.assertEqual(len(groupes), 1)
        libelle, articles = groupes[0]
        self.assertEqual(libelle, 'Campagnes')
        self.assertEqual([na.article.title for na in articles], ['Un', 'Deux'])

    def test_un_article_sans_rubrique_passe_en_tete(self):
        """Réponse à « peut-on choisir un article sans le mettre dans une
        rubrique ? » — oui, et il ouvre la lettre."""
        from content.models import NewsletterArticle
        cat = make_cms_category(name='C', slug='c-nl2', section_slug='principal')
        seul = make_article_page(section_slug='principal', title='Seul',
                                 slug='nl-seul', categories=[cat])
        range_ = make_article_page(section_slug='principal', title='Rangé',
                                   slug='nl-range', categories=[cat])
        ajoute_a_la_newsletter(self.nl, seul, rubrique='')
        ajoute_a_la_newsletter(self.nl, range_, rubrique='droits')
        groupes = self.nl.par_rubrique()
        self.assertEqual(groupes[0][0], '')
        self.assertEqual(groupes[0][1][0].article.title, 'Seul')
        self.assertEqual(groupes[1][0], 'Nos droits')


class MiseEnAvantDepuisLarticleTest(TestCase):
    """Remplir le carrousel et la une depuis l'article, pas depuis une fiche.

    Arnaud, 31/08/2026 : « il faut bien pouvoir remplir le carrousel et la une
    depuis la création d'article ». Deux cases existaient pour ça et **aucune
    des deux ne marchait sur la confédération** :

      - `in_carousel` ne synchronisait que pour `section_type` sectoral ou
        régional ; la conf est `main` ;
      - `featured_on_conf` alimentait `HomePage.get_context`, dont le contexte
        ne sort nulle part — `/` est servi par `HomeView`.

    0 article sur 1710 portait l'une ou l'autre.
    """

    def setUp(self):
        self.conf = _ensure_section_page(slug='principal', name='CNT-SO',
                                         site_type='main')
        self.syndicat = _ensure_section_page(slug='stucs', name='CNT-SO STUCS',
                                             site_type='sectoral')

    def _image(self):
        from wagtail.images.models import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io
        try:
            from PIL import Image as PILImage
        except ImportError:  # pragma: no cover
            self.skipTest('Pillow absent')
        tampon = io.BytesIO()
        PILImage.new('RGB', (60, 60), 'red').save(tampon, format='PNG')
        return Image.objects.create(
            title='Visuel', file=SimpleUploadedFile('v.png', tampon.getvalue(),
                                                    content_type='image/png'))

    # ── Le carrousel, y compris sur la conf ──────────────────────────────────

    def test_cocher_le_carrousel_sur_un_article_conf_le_place_bien(self):
        from cms.models import CarouselArticle
        art = make_article_page(section_slug='principal', title='Au carrousel',
                                slug='au-carrousel', in_carousel=True)
        self.assertTrue(
            CarouselArticle.objects.filter(page=self.conf, article=art).exists(),
            "la conf est `main` : la synchro l'excluait")

    def test_decocher_le_retire(self):
        from cms.models import CarouselArticle
        art = make_article_page(section_slug='principal', title='Puis retiré',
                                slug='puis-retire', in_carousel=True)
        art.in_carousel = False
        art.save()
        self.assertFalse(
            CarouselArticle.objects.filter(page=self.conf, article=art).exists())

    def test_le_carrousel_des_syndicats_marche_toujours(self):
        """Non-régression : c'était le seul cas qui fonctionnait."""
        from cms.models import CarouselArticle
        art = make_article_page(section_slug='stucs', title='Au STUCS',
                                slug='au-stucs', in_carousel=True)
        self.assertTrue(
            CarouselArticle.objects.filter(page=self.syndicat, article=art).exists())

    # ── La une confédérale, depuis n'importe quel syndicat ───────────────────

    def test_un_article_de_syndicat_hisse_a_la_une_apparait_sur_laccueil(self):
        art = make_article_page(section_slug='stucs', title='Grève au nettoyage',
                                slug='greve-nettoyage', featured_on_conf=True,
                                featured_image=self._image())
        r = self.client.get(reverse('content:home'))
        self.assertEqual(r.status_code, 200)
        pks = [a.pk for a in r.context['carousel_articles']]
        self.assertIn(art.pk, pks, "la case « à la une » ne produisait rien")

    def test_sans_la_case_larticle_de_syndicat_ne_monte_pas(self):
        """Contrôle négatif : sinon le test précédent passerait tout seul,
        l'accueil complétant le carrousel avec des articles récents."""
        art = make_article_page(section_slug='stucs', title='Article ordinaire',
                                slug='article-ordinaire',
                                featured_image=self._image())
        r = self.client.get(reverse('content:home'))
        pks = [a.pk for a in r.context['carousel_articles']]
        self.assertNotIn(art.pk, pks)

    def test_les_epingles_de_la_fiche_passent_devant(self):
        """L'ordre du carrousel est un choix éditorial : il ne se fait pas
        doubler par une case cochée sur un article."""
        from cms.models import CarouselArticle
        epingle = make_article_page(section_slug='principal', title='Épinglé',
                                    slug='epingle', featured_image=self._image())
        CarouselArticle.objects.create(page=self.conf, article=epingle, sort_order=0)
        promu = make_article_page(section_slug='stucs', title='Promu',
                                  slug='promu', featured_on_conf=True,
                                  featured_image=self._image())
        r = self.client.get(reverse('content:home'))
        pks = [a.pk for a in r.context['carousel_articles']]
        self.assertLess(pks.index(epingle.pk), pks.index(promu.pk))


class UneDesSyndicatsTest(TestCase):
    """Les sites de syndicat ont désormais la manchette de la confédération.

    Arnaud, 31/08/2026 : « il faut que les sites des syndicats aient eux aussi
    une une ». Ils avaient bien un gabarit nommé « Une de journal »
    (`_article_listing.html`), mais rendu à l'inverse de la règle du 16/08 :
    affiche recadrée en bandeau de 460 px (`object-fit: cover`), dégradé noir à
    82 %, titre écrit par-dessus. Cette règle avait été appliquée à l'accueil
    confédéral et jamais à ce gabarit — qui sert cinq écrans.
    """

    def setUp(self):
        self.conf = _ensure_section_page(slug='principal', name='CNT-SO',
                                         site_type='main')
        self.site = _ensure_section_page(slug='marseille', name='CNT-SO 13',
                                         site_type='regional')

    def _image(self):
        from wagtail.images.models import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io
        try:
            from PIL import Image as PILImage
        except ImportError:  # pragma: no cover
            self.skipTest('Pillow absent')
        tampon = io.BytesIO()
        PILImage.new('RGB', (60, 60), 'red').save(tampon, format='PNG')
        return Image.objects.create(
            title='Affiche', file=SimpleUploadedFile('a.png', tampon.getvalue(),
                                                     content_type='image/png'))

    def _peupler(self, nombre):
        return [
            make_article_page(section_slug='marseille', title=f'Article {i}',
                              slug=f'article-{i}', featured_image=self._image())
            for i in range(nombre)
        ]

    def _accueil(self):
        return self.client.get('/marseille/')

    # ── La manchette ─────────────────────────────────────────────────────────

    def test_un_accueil_de_syndicat_sert_une_manchette(self):
        self._peupler(12)
        r = self._accueil()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['manchette_articles'],
                        "les syndicats n'avaient que leur liste d'articles")

    def test_elle_partage_le_gabarit_de_la_conf(self):
        """Une seule définition : la recopie avait déjà fait diverger deux
        écrans d'édition en août."""
        self._peupler(12)
        self.assertContains(self._accueil(), 'hp-manchette')

    def test_un_syndicat_sans_article_illustre_n_affiche_pas_de_grille_vide(self):
        make_article_page(section_slug='marseille', title='Sans image',
                          slug='sans-image')
        r = self._accueil()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['manchette_articles'])

    # ── Aucun article trois fois sur le même écran ───────────────────────────

    def test_le_diaporama_et_la_manchette_ne_se_recoupent_pas(self):
        self._peupler(12)
        r = self._accueil()
        diapo = {a.pk for a in r.context['carousel_articles']}
        manch = {a.pk for a in r.context['manchette_articles']}
        self.assertEqual(diapo & manch, set())

    def test_la_liste_ne_reprend_pas_la_vitrine(self):
        self._peupler(15)
        r = self._accueil()
        vitrine = ({a.pk for a in r.context['carousel_articles']}
                   | {a.pk for a in r.context['manchette_articles']})
        liste = {a.pk for a in r.context['articles']}
        self.assertEqual(vitrine & liste, set(),
                         "le même article s'affichait jusqu'à trois fois")

    def test_un_syndicat_neuf_garde_sa_liste(self):
        """Repli : avec 3 articles, tout part en vitrine. Mieux vaut répéter
        que servir « Aucun article » sur un site qui vient d'ouvrir."""
        self._peupler(3)
        r = self._accueil()
        self.assertTrue(r.context['articles'])

    # ── La règle des affiches, enfin appliquée ───────────────────────────────

    def test_le_titre_n_est_plus_ecrit_sur_l_affiche(self):
        self._peupler(12)
        self.assertNotContains(self._accueil(), 'une-hero-overlay')

    def test_l_affiche_n_est_plus_recadree(self):
        """La règle vaut pour ce que l'accueil sert AUJOURD'HUI : des bandes.

        Ce test visait `.une-hero-img` — le grand article de tête — mais
        l'accueil ne l'emploie plus depuis le 03/09/2026 : il arrivait après le
        diaporama et la manchette, et répétait le même geste une fois de trop.
        Le gabarit partagé garde sa propre vérification, dans
        `test_le_gabarit_partage_ne_recadre_plus_aucune_affiche`.
        """
        self._peupler(12)
        html = self._accueil().content.decode()
        debut = html.index('.ab-visuel img {')
        regle = html[debut:html.index('}', debut)]
        self.assertIn('object-fit: contain', regle)
        self.assertNotIn('cover', regle)

    def test_les_autres_ecrans_heritent_du_meme_gabarit(self):
        """Le correctif tient parce que le gabarit est PARTAGÉ.

        Cinq écrans l'incluent : accueils de syndicat, pages de catégorie,
        pages de tag, espace presse, `site_home`. C'est ce partage qu'il faut
        garder — le jour où l'un d'eux se forke sa propre copie, il repartira
        avec le voile et le recadrage.

        On vérifie l'inclusion, pas le rendu : une page de catégorie sert zéro
        article sur des fixtures neuves, et une assertion « pas de voile » y
        passerait sans rien prouver (constaté en écrivant ce test).
        """
        categorie = make_cms_category(name='Droit', slug='droit',
                                      section_slug='principal')
        art = make_article_page(section_slug='principal', title='Un droit',
                                slug='un-droit', featured_image=self._image())
        art.cms_categories.add(categorie)
        r = self.client.get('/categorie/droit/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('content/_article_listing.html',
                      [t.name for t in r.templates if t.name])

    def test_le_gabarit_partage_ne_recadre_plus_aucune_affiche(self):
        """Le pendant du test précédent : la source du partiel, une fois pour
        les cinq écrans. Validé par mutation — réintroduire le voile fait
        tomber les tests d'accueil ci-dessus.

        On lit les RÈGLES, pas le fichier entier : la première version de ce
        test cherchait « object-fit: cover » n'importe où et échouait sur sa
        propre phrase d'explication. Il a en revanche débusqué deux vrais
        oublis — les petites cartes recadraient encore, et une hauteur fixe de
        300 px traînait sur le bloc de tête en mobile, où elle aurait rogné
        l'affiche ET le titre.
        """
        import re
        from django.template.loader import get_template
        source = open(get_template('content/_article_listing.html')
                      .origin.name, encoding='utf-8').read()
        self.assertNotIn('une-hero-overlay', source)
        for selecteur in ('.une-hero-img {', '.une-card-img img {'):
            with self.subTest(selecteur=selecteur):
                debut = source.index(selecteur)
                regle = source[debut:source.index('}', debut)]
                self.assertIn('object-fit: contain', regle)
                self.assertNotIn('cover', regle)
        # Une hauteur fixe sur le conteneur rognerait l'affiche et le titre.
        entete = source[source.index('.une-hero {'):source.index('}', source.index('.une-hero {'))]
        self.assertNotIn('height', entete)

    def test_la_conf_sert_toujours_sa_manchette(self):
        """Non-régression : le CSS a été déplacé hors de `home.html`."""
        for i in range(8):
            make_article_page(section_slug='principal', title=f'Conf {i}',
                              slug=f'conf-{i}', featured_image=self._image())
        r = self.client.get(reverse('content:home'))
        self.assertContains(r, 'hp-manchette')
        self.assertContains(r, 'object-fit: contain')


class RetirerDeLaUneNePerdRienTest(TestCase):
    """Décocher la une ne doit jamais faire disparaître un article.

    Arnaud, 31/08/2026 : « c'est cool d'éviter les doublons, mais si on
    l'enlève du carrousel il revient en bas ? ». Question juste : depuis que
    `get_queryset` retire la vitrine de la liste, un article mal repris nulle
    part serait devenu invisible sur son propre site.
    """

    def setUp(self):
        _ensure_section_page(slug='principal', name='CNT-SO', site_type='main')
        _ensure_section_page(slug='m', name='CNT-SO M', site_type='regional')
        self.arts = [self._article(i) for i in range(14)]

    def _article(self, i):
        from wagtail.images.models import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io
        try:
            from PIL import Image as PILImage
        except ImportError:  # pragma: no cover
            self.skipTest('Pillow absent')
        tampon = io.BytesIO()
        PILImage.new('RGB', (60, 60), 'red').save(tampon, format='PNG')
        image = Image.objects.create(
            title=f'Affiche {i}',
            file=SimpleUploadedFile(f'a{i}.png', tampon.getvalue(),
                                    content_type='image/png'))
        return make_article_page(section_slug='m', title=f'A{i}', slug=f'a-{i}',
                                 featured_image=image)

    def _ou_est(self, article):
        r = self.client.get('/m/')
        for zone in ('carousel_articles', 'manchette_articles', 'articles'):
            if article.pk in {a.pk for a in r.context[zone]}:
                return zone
        return None

    def test_un_article_ancien_retire_de_la_une_redescend_dans_la_page(self):
        ancien = self.arts[0]
        ancien.in_carousel = True
        ancien.save()
        self.assertEqual(self._ou_est(ancien), 'carousel_articles')
        ancien.in_carousel = False
        ancien.save()
        self.assertEqual(self._ou_est(ancien), 'articles',
                         "l'article a disparu de son propre site")

    def test_aucun_article_du_site_n_est_invisible(self):
        """Le garde-fou de fond : la vitrine retire des articles de la liste,
        donc la somme des trois zones doit couvrir tout ce qui est en ligne
        sur la première page."""
        self.arts[0].in_carousel = True
        self.arts[0].save()
        r = self.client.get('/m/')
        vus = set()
        for zone in ('carousel_articles', 'manchette_articles', 'articles'):
            vus |= {a.pk for a in r.context[zone]}
        # 14 articles = 5 au diaporama + 6 en manchette + 3 dans la liste.
        # (Il n'y a pas de page 2 : la vitrine en absorbe onze, et la demander
        # rend un 404 — ce qui a fait tomber la première version de ce test.)
        self.assertEqual(vus, {a.pk for a in self.arts},
                         "des articles ne sont servis nulle part")

    def test_l_aide_previent_que_les_recents_y_entrent_seuls(self):
        """Décocher un article récent ne change rien de visible : la complétion
        automatique le remet aussitôt. La case doit le dire, sans quoi elle
        passe pour cassée."""
        aide = str(ArticlePage._meta.get_field('in_carousel').help_text)
        self.assertIn('tout seuls', aide)
        self.assertIn("n'est pas perdu", aide)


class EnteteExpediteurValideTest(TestCase):
    """L'en-tête « De » du message de contact doit être une adresse valide.

    Le 26/08/2026, l'expéditeur est devenu « Untel via Syndicat <…> » pour que
    le destinataire sache d'où vient le message. Mais l'adresse insérée était
    `DEFAULT_FROM_EMAIL`, qui vaut déjà « CNT-SO <newsletter@cnt-so.org> » —
    nom d'affichage compris. D'où des chevrons imbriqués :

        Arnaud via CNT-SO confédération <CNT-SO <newsletter@cnt-so.org>>

    Django refuse cette adresse (`ValueError: Invalid address`). **Aucun
    message de contact ne pouvait donc partir pendant deux semaines**, et le
    défaut est resté invisible parce qu'hCaptcha bloquait les formulaires en
    amont : personne n'atteignait cette ligne. Découvert le 02/09/2026 sur le
    tout premier message jamais reçu.
    """

    def setUp(self):
        self.site = make_site(slug='principal', name='CNT-SO confédération')
        self.site.contact_email = 'contact@cnt-so.org'
        self.site.save(update_fields=['contact_email'])

    def _message(self, nom='Arnaud', prenom='D'):
        from content.models import ContactMessage
        return ContactMessage.objects.create(
            site=self.site, name=nom, first_name=prenom,
            email='visiteur@example.org', subject='Objet', message='Bonjour')

    @override_settings(DEFAULT_FROM_EMAIL='CNT-SO <newsletter@cnt-so.org>')
    def test_l_expediteur_est_une_adresse_acceptee(self):
        """Le contrôle qui aurait attrapé le défaut : Django valide l'adresse
        à la construction du message, avant tout envoi."""
        from django.core import mail
        from content.views import _send_contact_email
        self.assertTrue(_send_contact_email(self.site, self._message()))
        self.assertEqual(len(mail.outbox), 1)
        from email.utils import parseaddr
        nom, adresse = parseaddr(mail.outbox[0].from_email)
        self.assertEqual(adresse, 'newsletter@cnt-so.org')
        self.assertNotIn('<', nom, "des chevrons imbriqués dans le nom")

    @override_settings(DEFAULT_FROM_EMAIL='CNT-SO <newsletter@cnt-so.org>')
    def test_le_nom_de_l_expediteur_reste_lisible(self):
        """On ne corrige pas en supprimant l'information : le destinataire doit
        toujours voir de qui vient le message."""
        from django.core import mail
        from content.views import _send_contact_email
        _send_contact_email(self.site, self._message(nom='Dupont', prenom='Marie'))
        expediteur = mail.outbox[0].from_email
        self.assertIn('Marie', expediteur)
        self.assertIn('Dupont', expediteur)
        self.assertIn('CNT-SO confédération', expediteur)

    @override_settings(DEFAULT_FROM_EMAIL='sansnom@cnt-so.org')
    def test_marche_aussi_si_le_reglage_est_une_adresse_nue(self):
        """`parseaddr` rend l'adresse telle quelle quand il n'y a pas de nom."""
        from django.core import mail
        from content.views import _send_contact_email
        _send_contact_email(self.site, self._message())
        from email.utils import parseaddr
        _, adresse = parseaddr(mail.outbox[0].from_email)
        self.assertEqual(adresse, 'sansnom@cnt-so.org')

    @override_settings(DEFAULT_FROM_EMAIL='CNT-SO <newsletter@cnt-so.org>')
    def test_la_reponse_va_bien_au_visiteur(self):
        """Non-régression : l'expéditeur est le site, mais « Répondre » doit
        écrire à la personne qui a rempli le formulaire."""
        from django.core import mail
        from content.views import _send_contact_email
        _send_contact_email(self.site, self._message())
        self.assertEqual(mail.outbox[0].reply_to, ['visiteur@example.org'])

    @override_settings(DEFAULT_FROM_EMAIL='CNT-SO <newsletter@cnt-so.org>')
    def test_un_echec_d_envoi_dit_pourquoi_dans_le_journal(self):
        """Le journal disait « NON REMIS » sans la cause : il a fallu
        reproduire l'envoi à la main pour trouver l'en-tête malformé."""
        from unittest.mock import patch
        from content.views import _send_contact_email
        with patch('content.views.EmailMultiAlternatives.send',
                   side_effect=ValueError('adresse invalide')):
            with self.assertLogs('content.views', level='ERROR') as journal:
                self.assertFalse(_send_contact_email(self.site, self._message()))
        trace = '\n'.join(journal.output)
        self.assertIn('adresse invalide', trace)


class BoutonAdhererTest(TestCase):
    """Le bouton « Adhérer » ne doit jamais mener à un 404.

    Mesuré en production le 02/09/2026 : **sept boutons sur huit** rendaient un
    404, la confédération comprise. `/adherer/<slug>/` redirigeait toujours vers
    l'application d'adhésion, laquelle ne connaît qu'un seul syndicat — et le
    réglage prévu pour ça, `ADHESION_USE_NEW_APP`, valait bien `False` en
    production mais **n'était lu nulle part**.

    Sur un site syndical, c'est le lien qui compte le plus.
    """

    def setUp(self):
        self.conf = make_site(slug='principal', name='CNT-SO confédération')
        self.stucs = _ensure_section_page(slug='stucs', name='CNT-SO STUCS',
                                          site_type='sectoral')
        self.stucs.framaform_url = 'https://framaforms.org/adherer-au-stucs'
        self.stucs.contact_email = 'spectacle@cnt-so.org'
        self.stucs.save(update_fields=['framaform_url', 'contact_email'])

    # ── application d'adhésion désactivée : le cas d'aujourd'hui ─────────────

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_sans_formulaire_on_explique_au_lieu_de_renvoyer_un_404(self):
        r = self.client.get('/adherer/principal/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "arrive bientôt")
        self.assertContains(r, "Nous écrire")

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_la_page_mene_au_contact_du_bon_syndicat(self):
        r = self.client.get('/adherer/principal/')
        self.assertEqual(r.context['contact_url'], _url_contact_attendu(self.conf))

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_un_syndicat_avec_framaform_y_est_conduit(self):
        """Le STUCS a un Framaform qui fonctionne : il ne doit pas tomber sur
        la page d'attente."""
        r = self.client.get('/adherer/stucs/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://framaforms.org/adherer-au-stucs')

    # ── application activée : le jour où elle sera prête ─────────────────────

    @override_settings(ADHESION_USE_NEW_APP=True,
                       ADHESION_BASE_URL='https://adhesion.cnt-so.org')
    def test_le_reglage_active_bascule_tout_vers_l_application(self):
        for slug in ('principal', 'stucs'):
            with self.subTest(slug=slug):
                r = self.client.get(f'/adherer/{slug}/')
                self.assertEqual(r.status_code, 302)
                self.assertEqual(
                    r['Location'], f'https://adhesion.cnt-so.org/adherer/{slug}/')

    @override_settings(ADHESION_USE_NEW_APP=True)
    def test_le_reglage_prime_sur_le_framaform(self):
        """Sinon le STUCS resterait sur Framaform quand tout le monde aura
        basculé — et personne ne comprendrait pourquoi."""
        r = self.client.get('/adherer/stucs/')
        self.assertNotIn('framaforms', r['Location'])

    # ── garde-fous ───────────────────────────────────────────────────────────

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_un_syndicat_inconnu_reste_un_404(self):
        self.assertEqual(self.client.get('/adherer/nexiste-pas/').status_code, 404)

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_un_syndicat_depublie_aussi(self):
        ferme = _ensure_section_page(slug='ferme-adh', name='Fermé', live=False)
        self.assertEqual(self.client.get('/adherer/ferme-adh/').status_code, 404)

    @override_settings(ADHESION_USE_NEW_APP=False)
    def test_le_bouton_de_la_page_rejoindre_pointe_bien_ici(self):
        """Non-régression du chemin complet : la page « Rejoindre » construit
        son bouton avec {% url 'adherer' %}."""
        r = self.client.get('/principal/rejoindre/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '/adherer/principal/')


def _url_contact_attendu(section):
    from content.views import url_contact_du_syndicat
    return url_contact_du_syndicat(section)


class AdhesionUrlContradictoireTest(TestCase):
    """Une `framaform_url` qui pointe vers l'application d'adhésion contredit
    le réglage `ADHESION_USE_NEW_APP`.

    Cas réel : la fiche de l'Éducation porte
    `https://adhesion.cnt-so.org/adherer/education/`, une adresse qui rend 404.
    Le réglage dit « l'application n'est pas prête », cette valeur dit
    « vas-y ». Le réglage tranche (02/09/2026).
    """

    def setUp(self):
        make_site(slug='principal')
        self.educ = _ensure_section_page(slug='education', name='CNT-SO Éducation')
        self.educ.framaform_url = 'https://adhesion.cnt-so.org/adherer/education/'
        self.educ.save(update_fields=['framaform_url'])

    @override_settings(ADHESION_USE_NEW_APP=False,
                       ADHESION_BASE_URL='https://adhesion.cnt-so.org')
    def test_l_adresse_de_l_application_est_ignoree_quand_le_reglage_est_coupe(self):
        r = self.client.get('/adherer/education/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "arrive bientôt")

    @override_settings(ADHESION_USE_NEW_APP=False,
                       ADHESION_BASE_URL='https://adhesion.cnt-so.org')
    def test_un_vrai_formulaire_externe_reste_suivi(self):
        """Contrôle négatif : on n'ignore que l'application d'adhésion."""
        self.educ.framaform_url = 'https://framaforms.org/adherer-educ'
        self.educ.save(update_fields=['framaform_url'])
        r = self.client.get('/adherer/education/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://framaforms.org/adherer-educ')

    @override_settings(ADHESION_USE_NEW_APP=True,
                       ADHESION_BASE_URL='https://adhesion.cnt-so.org')
    def test_une_fois_l_application_prete_on_y_va(self):
        r = self.client.get('/adherer/education/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('adhesion.cnt-so.org', r['Location'])


class RepareMenuEducationTest(TestCase):
    """Deux entrées du menu Éducation menaient au mauvais endroit.

    « Liens CNT-SO » pointait `https://cnt-so.org` en dur — l'ancien WordPress,
    qui rend un HTTP 500 depuis juillet. « Rejoindre la CNT-SO » menait au
    formulaire de contact alors que la page d'adhésion existe.

    La commande ne touche QUE ces deux-là, et seulement si elles sont dans
    l'état attendu : un `pk` réattribué ou une entrée déjà modifiée à la main
    ne doit pas être écrasée en silence.
    """

    def setUp(self):
        from content.models import MenuItem
        self.educ = _ensure_section_page(slug='education', name='CNT-SO Éducation')
        self.liens = MenuItem.objects.create(
            pk=394, site=self.educ, menu='main', title='Liens CNT-SO',
            url='https://cnt-so.org', order=1)
        self.rejoindre = MenuItem.objects.create(
            pk=413, site=self.educ, menu='footer', title='Rejoindre la CNT-SO',
            url='/education/contact/', order=1)

    def _lancer(self, appliquer=False):
        from django.core.management import call_command
        from io import StringIO
        s = StringIO()
        call_command('repare_menu_education', *(['--appliquer'] if appliquer else []), stdout=s)
        return s.getvalue()

    def test_a_blanc_rien_n_est_ecrit(self):
        self._lancer()
        self.liens.refresh_from_db()
        self.assertEqual(self.liens.url, 'https://cnt-so.org')

    def test_le_lien_vers_l_ancien_serveur_devient_relatif(self):
        """`/` et non une adresse en dur : juste avant ET après la bascule."""
        self._lancer(appliquer=True)
        self.liens.refresh_from_db()
        self.assertEqual(self.liens.url, '/')

    def test_rejoindre_mene_a_la_page_d_adhesion(self):
        self._lancer(appliquer=True)
        self.rejoindre.refresh_from_db()
        self.assertEqual(self.rejoindre.url, '/education/rejoindre/')

    def test_une_entree_deja_modifiee_n_est_pas_ecrasee(self):
        """Garde-fou : si quelqu'un a corrigé à la main autrement, on n'écrase
        pas son choix."""
        self.liens.url = 'https://newsite.cnt-so.org/'
        self.liens.save(update_fields=['url'])
        sortie = self._lancer(appliquer=True)
        self.liens.refresh_from_db()
        self.assertEqual(self.liens.url, 'https://newsite.cnt-so.org/')
        self.assertIn('non touchée', sortie)

    def test_un_pk_reattribue_a_un_autre_titre_est_epargne(self):
        """Le contrôle porte sur le titre ET l'URL, pas sur le seul `pk`."""
        self.liens.title = 'Tout autre chose'
        self.liens.save(update_fields=['title'])
        self._lancer(appliquer=True)
        self.liens.refresh_from_db()
        self.assertEqual(self.liens.url, 'https://cnt-so.org')

    def test_relancee_elle_ne_fait_rien_de_plus(self):
        self._lancer(appliquer=True)
        sortie = self._lancer(appliquer=True)
        self.assertIn('déjà réparée', sortie)

    def test_le_reste_du_menu_est_intact(self):
        from content.models import MenuItem
        autre = MenuItem.objects.create(
            site=self.educ, menu='main', title='Ressources',
            url='/education/ressources/', order=9)
        self._lancer(appliquer=True)
        autre.refresh_from_db()
        self.assertEqual(autre.url, '/education/ressources/')


class ListeEnBandesTest(TestCase):
    """L'accueil d'un syndicat liste ses articles en bandes, pas en « une ».

    Arnaud, 03/09/2026 : la liste « Dernières actualités » arrive APRÈS le
    diaporama et APRÈS la manchette. Son grand article de tête répétait le même
    geste visuel une fois de trop — sur le STUCS, le logo du syndicat s'étalait
    sur 420 px de haut, presque entièrement blancs.

    Les pages de catégorie, de tag et l'espace presse GARDENT l'ancien gabarit :
    là, la liste est le seul contenu de la page, elle peut s'ouvrir sur un
    grand article. C'est la raison d'avoir deux gabarits et non un.
    """

    def setUp(self):
        make_site(slug='principal')
        self.site = _ensure_section_page(slug='marseille', name='CNT-SO 13')

    def _image(self):
        from wagtail.images.models import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io
        try:
            from PIL import Image as PILImage
        except ImportError:  # pragma: no cover
            self.skipTest('Pillow absent')
        t = io.BytesIO()
        PILImage.new('RGB', (60, 80), 'red').save(t, format='PNG')
        return Image.objects.create(
            title='Affiche', file=SimpleUploadedFile('a.png', t.getvalue(),
                                                     content_type='image/png'))

    def _peupler(self, n=14):
        return [make_article_page(section_slug='marseille', title=f'Article {i}',
                                  slug=f'art-{i}', featured_image=self._image())
                for i in range(n)]

    def test_l_accueil_sert_des_bandes(self):
        self._peupler()
        r = self.client.get('/marseille/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ab-bande')

    def test_l_accueil_n_a_plus_de_grand_article_de_tete(self):
        self._peupler()
        self.assertNotContains(self.client.get('/marseille/'), 'une-hero"')

    def test_les_pages_de_categorie_gardent_l_ancien_gabarit(self):
        """Contrôle négatif : on n'a pas basculé les cinq écrans d'un coup."""
        cat = make_cms_category(name='Droit', slug='droit', section_slug='principal')
        for i in range(3):
            make_article_page(section_slug='principal', title=f'D{i}',
                              slug=f'd-{i}', categories=[cat],
                              featured_image=self._image())
        r = self.client.get('/categorie/droit/')
        self.assertContains(r, 'une-hero"')
        self.assertNotContains(r, 'ab-bande')

    def test_les_affiches_ne_sont_pas_recadrees(self):
        """Règle du 16/08 : affiche entière, jamais `cover`."""
        self._peupler()
        html = self.client.get('/marseille/').content.decode()
        debut = html.index('.ab-visuel img {')
        regle = html[debut:html.index('}', debut)]
        self.assertIn('object-fit: contain', regle)
        self.assertNotIn('cover', regle)

    def test_un_article_sans_image_garde_sa_place(self):
        """Sans réserve, la bande se décalerait et la liste perdrait son peigne."""
        make_article_page(section_slug='marseille', title='Sans visuel',
                          slug='sans-visuel')
        r = self.client.get('/marseille/')
        self.assertContains(r, 'ab-sans-visuel')

    def test_la_liste_vide_le_dit(self):
        r = self.client.get('/marseille/')
        self.assertContains(r, 'Aucun article pour le moment')


class ArticleSlugPartageTest(TestCase):
    """`/article/<slug>/` rendait un 500 quand deux syndicats partagent un slug.

    `get_object_or_404(ArticlePage, slug=slug)` lève `MultipleObjectsReturned`
    sur un champ qui n'est pas unique. Mesuré en production le 03/09/2026 :
    **241 slugs en double, dont 43 rendaient une erreur serveur**, depuis le
    26 août au moins.

    Exactement le défaut des flux de catégorie corrigé le 01/09 — un
    `get_object_or_404` sur un champ non unique — dans un autre coin du code.
    """

    def setUp(self):
        self.conf = make_site(slug='principal', name='CNT-SO confédération')
        self.treize = _ensure_section_page(slug='marseille', name='CNT-SO 13')
        self.auvergne = _ensure_section_page(slug='auvergne', name='CNT-SO Auvergne')

    def _article(self, section, titre, slug):
        """Sous la SectionPage du syndicat, comme en production.

        Wagtail refuse deux pages de même slug sous le MÊME parent : les
        doublons de production n'existent que parce que chaque article vit sous
        la fiche de son syndicat. La factory commune, elle, range tout sous une
        HomePage unique — d'où un `ValidationError` si on l'emploie ici.
        """
        from cms.models import ArticlePage
        return section.add_child(instance=ArticlePage(
            title=titre, slug=slug, section_slug=section.slug, live=True))

    def test_un_slug_partage_par_deux_syndicats_ne_leve_plus_500(self):
        self._article(self.treize, 'Grève', 'greve')
        self._article(self.auvergne, 'Grève', 'greve')
        r = self.client.get('/article/greve/')
        self.assertEqual(r.status_code, 302)

    def test_il_est_renvoye_chez_son_syndicat(self):
        a = self._article(self.treize, 'Grève', 'greve')
        b = self._article(self.auvergne, 'Grève', 'greve')
        r = self.client.get('/article/greve/')
        self.assertIn(r['Location'], {a.get_absolute_url(), b.get_absolute_url()})

    def test_l_article_de_la_conf_prime_et_est_servi(self):
        """Non-régression : si la conf a ce slug, elle le sert, sans redirection."""
        self._article(self.conf, 'Grève conf', 'greve')
        self._article(self.treize, 'Grève 13', 'greve')
        r = self.client.get('/article/greve/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['article'].section_slug, 'principal')

    def test_le_choix_est_stable_d_une_requete_a_l_autre(self):
        """Sans tri, `.first()` rendait un résultat au hasard de la base."""
        self._article(self.treize, 'A', 'greve')
        self._article(self.auvergne, 'B', 'greve')
        cibles = {self.client.get('/article/greve/')['Location'] for _ in range(4)}
        self.assertEqual(len(cibles), 1)

    def test_un_syndicat_depublie_ne_sert_pas_de_destination(self):
        ferme = _ensure_section_page(slug='ferme-art', name='Fermé', live=False)
        self._article(ferme, 'Cachée', 'cachee')
        self.assertEqual(self.client.get('/article/cachee/').status_code, 404)

    def test_un_slug_inconnu_reste_un_404(self):
        self.assertEqual(self.client.get('/article/nexiste-pas/').status_code, 404)

    def test_un_seul_article_de_syndicat_redirige_aussi(self):
        """Même sans doublon : l'adresse de la conf ne sert pas le contenu
        d'un syndicat sous l'identité de la conf."""
        a = self._article(self.treize, 'Seule', 'seule')
        r = self.client.get('/article/seule/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], a.get_absolute_url())


class AlerteErreurParCourrielTest(TestCase):
    """Une erreur 500 doit prévenir quelqu'un, sans noyer la boîte.

    Les 43 adresses d'article en erreur ont duré **du 26/08 au 03/09/2026**
    sans que rien ne le signale : `ADMINS` n'était pas défini, la panne restait
    dans `django.log` et journald. Adresse dédiée créée le 04/09 :
    technique@cnt-so.org.

    Mais alerter sans limite serait pire : ces 43 adresses, martelées par les
    robots, auraient rempli la boîte de messages identiques.
    """

    def _enregistrement(self, chemin='/article/casse/', exception=ValueError):
        import logging
        from django.test import RequestFactory
        req = RequestFactory().get(chemin)
        rec = logging.LogRecord('django.request', logging.ERROR, __file__, 1,
                                'Internal Server Error: %s', (chemin,), None)
        rec.request = req
        try:
            raise exception('bing')
        except exception:
            import sys
            rec.exc_info = sys.exc_info()
        return rec

    def _handler(self):
        from cntso.alertes import AlerteLimitee
        return AlerteLimitee()

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_une_erreur_500_envoie_un_courriel(self):
        from django.core import mail
        self._handler().emit(self._enregistrement())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['technique@cnt-so.org'])

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_la_meme_erreur_repetee_n_envoie_qu_un_courriel(self):
        """Le cas qui compte : un robot qui martèle une page cassée."""
        from django.core import mail
        h = self._handler()
        for _ in range(30):
            h.emit(self._enregistrement())
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_une_deuxieme_page_cassee_passe_tout_de_suite(self):
        """Ce n'est pas un plafond global : chaque signature a son quota."""
        from django.core import mail
        h = self._handler()
        h.emit(self._enregistrement('/article/un/'))
        h.emit(self._enregistrement('/article/deux/'))
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_une_autre_exception_sur_la_meme_page_passe_aussi(self):
        from django.core import mail
        h = self._handler()
        h.emit(self._enregistrement('/article/un/', ValueError))
        h.emit(self._enregistrement('/article/un/', KeyError))
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_l_alerte_repasse_apres_la_fenetre(self):
        """Sinon une panne persistante ne serait signalée qu'une seule fois."""
        from django.core import mail
        h = self._handler()
        h.emit(self._enregistrement())
        for sig in list(h._vues):
            h._vues[sig] -= h.FENETRE + 1   # on avance d'une heure
        h.emit(self._enregistrement())
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_le_compteur_ne_grossit_pas_sans_fin(self):
        """Un gestionnaire d'alertes qui fuit serait une panne de plus."""
        h = self._handler()
        for i in range(h.MAX_SIGNATURES + 60):
            h.emit(self._enregistrement(f'/article/{i}/'))
        self.assertLessEqual(len(h._vues), h.MAX_SIGNATURES)

    @override_settings(ADMINS=[])
    def test_sans_destinataire_rien_ne_part(self):
        """Le défaut en développement et pendant les tests."""
        from django.core import mail
        self._handler().emit(self._enregistrement())
        self.assertEqual(len(mail.outbox), 0)

    def test_le_journal_django_request_est_bien_branche(self):
        """Explicite dans LOGGING : se reposer sur la fusion implicite de
        Django rendrait l'alerte silencieusement inopérante."""
        from django.conf import settings
        conf = settings.LOGGING['loggers']['django.request']
        self.assertIn('admins', conf['handlers'])
        self.assertEqual(conf['level'], 'ERROR')


class AlerteEchecSystemdTest(TestCase):
    """Une tâche systemd qui échoue doit prévenir, pas se taire.

    Si `pg-backup.service` ratait une nuit, on l'apprendrait le jour où il
    faudrait une sauvegarde — le pire moment (audit du 04/09/2026).
    """

    def _lancer(self, unite='pg-backup.service'):
        from django.core.management import call_command
        from io import StringIO
        s, e = StringIO(), StringIO()
        call_command('alerte_echec', unite, stdout=s, stderr=e)
        return s.getvalue(), e.getvalue()

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_l_echec_part_par_courriel(self):
        from django.core import mail
        self._lancer()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('pg-backup.service', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['technique@cnt-so.org'])

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_le_courriel_dit_quoi_faire(self):
        """Une alerte sans marche à suivre oblige à chercher : on joint la
        commande exacte."""
        from django.core import mail
        self._lancer()
        corps = mail.outbox[0].body
        self.assertIn('systemctl status pg-backup.service', corps)
        self.assertIn('journalctl -u pg-backup.service', corps)

    @override_settings(ADMINS=[])
    def test_sans_destinataire_elle_le_dit_au_lieu_de_se_taire(self):
        from django.core import mail
        _, erreur = self._lancer()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('ADMINS est vide', erreur)

    @override_settings(ADMINS=[('Technique', 'technique@cnt-so.org')])
    def test_un_journal_illisible_n_empeche_pas_l_alerte(self):
        """Mieux vaut une alerte sans extrait qu'aucune alerte."""
        from unittest.mock import patch
        from django.core import mail
        with patch('subprocess.run', side_effect=PermissionError('refusé')):
            self._lancer()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('journal illisible', mail.outbox[0].body)


class AdminsDepuisEnvironnementTest(TestCase):
    """Une entrée sans adresse ne doit JAMAIS entrer dans ADMINS.

    Le 04/09/2026, systemd a coupé `Environment=DJANGO_ADMINS=Technique
    CNT-SO:technique@cnt-so.org` sur l'espace du nom : il ne restait que
    « Technique ». L'ancien analyseur en tirait ('Technique', ''), et l'alerte
    partait « à personne » en annonçant un succès — un système d'alerte qui
    échoue en silence est pire que pas d'alerte du tout.
    """

    @staticmethod
    def _lire(valeur):
        """Rejoue exactement l'expression de settings.py."""
        return [
            (nom.strip() or 'Technique', adr.strip())
            for nom, _, adr in (
                couple.partition(':')
                for couple in valeur.split(',')
                if couple.strip()
            )
            if adr.strip()
        ]

    def test_un_couple_complet_est_lu(self):
        self.assertEqual(self._lire('Technique:technique@cnt-so.org'),
                         [('Technique', 'technique@cnt-so.org')])

    def test_une_entree_sans_adresse_est_rejetee(self):
        """Le cas réel : systemd n'a transmis que le premier mot."""
        self.assertEqual(self._lire('Technique'), [])

    def test_une_valeur_vide_donne_une_liste_vide(self):
        self.assertEqual(self._lire(''), [])

    def test_plusieurs_destinataires(self):
        self.assertEqual(
            self._lire('A:a@x.fr,B:b@x.fr'),
            [('A', 'a@x.fr'), ('B', 'b@x.fr')])

    def test_une_adresse_seule_reste_utilisable(self):
        """Sans nom, on ne perd pas le destinataire pour autant."""
        self.assertEqual(self._lire(':technique@cnt-so.org'),
                         [('Technique', 'technique@cnt-so.org')])
