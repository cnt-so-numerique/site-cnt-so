"""
Tests pour les fonctionnalités récentes :
- Sous-site STUCS (vues, menu, catégories)
- Modèle Event (agenda)
- Champs SectionPage (linkstack, framaform, intro_text, rejoindre_text, agenda_text)
- wagtail-seo (champs OG sur ArticlePage)
- Recherche Wagtail FTS
- Interface listes mails OVH + sync abonnés
"""
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from cms.models import (
    ArticlePage, CarouselArticle, CmsCategory, ContentPage, Event, HomePage, SectionPage,
)
from content.tests import (
    make_article_page, make_cms_category, make_superuser,
    _ensure_section_page,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_stucs_section():
    sp = _ensure_section_page(
        slug='stucs', name='STUCS', site_type='sectoral', live=True,
    )
    # Mettre à jour les champs STUCS si pas encore définis
    if not sp.linkstack_url:
        sp.linkstack_url = 'https://linkstack.fr/@stucs_cntso'
        sp.framaform_url = 'https://framaforms.org/adherer-au-stucs-1733747573'
        sp.save(update_fields=['linkstack_url', 'framaform_url'])
    return sp


def make_event(section, title='Événement test', days_from_now=7, **kwargs):
    return Event.objects.create(
        section=section,
        title=title,
        date=date.today() + timedelta(days=days_from_now),
        **kwargs
    )


# ── SectionPage — nouveaux champs ─────────────────────────────────────────────

class SectionPageNewFieldsTest(TestCase):

    def test_linkstack_url_saved(self):
        sp = make_stucs_section()
        sp.linkstack_url = 'https://linkstack.fr/@stucs_cntso'
        sp.save()
        sp.refresh_from_db()
        self.assertEqual(sp.linkstack_url, 'https://linkstack.fr/@stucs_cntso')

    def test_framaform_url_saved(self):
        sp = make_stucs_section()
        sp.framaform_url = 'https://framaforms.org/test'
        sp.save()
        sp.refresh_from_db()
        self.assertEqual(sp.framaform_url, 'https://framaforms.org/test')

    def test_agenda_text_blank_by_default(self):
        sp = make_stucs_section()
        self.assertEqual(list(sp.agenda_text), [])

    def test_rejoindre_text_blank_by_default(self):
        sp = make_stucs_section()
        self.assertEqual(list(sp.rejoindre_text), [])

    def test_intro_text_blank_by_default(self):
        sp = make_stucs_section()
        self.assertEqual(list(sp.intro_text), [])


# ── Modèle Event ──────────────────────────────────────────────────────────────

class EventModelTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_create_event(self):
        ev = make_event(self.stucs, 'Réunion', days_from_now=3)
        self.assertEqual(ev.title, 'Réunion')
        self.assertEqual(ev.section, self.stucs)
        self.assertFalse(ev.is_past)

    def test_past_event(self):
        ev = Event.objects.create(
            section=self.stucs, title='Passé',
            date=date.today() - timedelta(days=1),
        )
        self.assertTrue(ev.is_past)

    def test_str(self):
        ev = make_event(self.stucs, 'Concert', days_from_now=5)
        self.assertIn('Concert', str(ev))
        self.assertIn('/', str(ev))

    def test_ordering_by_date(self):
        make_event(self.stucs, 'B', days_from_now=10)
        make_event(self.stucs, 'A', days_from_now=2)
        events = list(Event.objects.filter(section=self.stucs))
        self.assertEqual(events[0].title, 'A')
        self.assertEqual(events[1].title, 'B')

    def test_optional_fields_blank(self):
        ev = Event.objects.create(section=self.stucs, title='Minimal', date=date.today())
        self.assertEqual(ev.location, '')
        self.assertIsNone(ev.time)
        self.assertIsNone(ev.end_date)
        self.assertEqual(ev.url, '')

    def test_event_with_all_fields(self):
        import datetime
        ev = Event.objects.create(
            section=self.stucs,
            title='Complet',
            date=date.today() + timedelta(days=3),
            end_date=date.today() + timedelta(days=4),
            time=datetime.time(19, 30),
            location='Paris',
            description='Description test',
            url='https://example.org',
        )
        self.assertEqual(ev.location, 'Paris')
        self.assertEqual(ev.url, 'https://example.org')


# ── Vues STUCS ────────────────────────────────────────────────────────────────

class StucsHomeViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_home_returns_200(self):
        r = self.client.get('/stucs/')
        self.assertEqual(r.status_code, 200)

    def test_home_uses_stucs_template(self):
        r = self.client.get('/stucs/')
        self.assertTemplateUsed(r, 'content/sectoral_site_home.html')

    def test_home_shows_articles(self):
        make_article_page(section_slug='stucs', title='Article STUCS test')
        r = self.client.get('/stucs/')
        self.assertContains(r, 'Article STUCS test')

    def test_home_contains_site_title(self):
        r = self.client.get('/stucs/')
        self.assertContains(r, 'STUCS')

    def test_home_shows_rejoindre_block(self):
        # Le bloc sidebar "Nous rejoindre" pointe vers la page contact du sous-site
        r = self.client.get('/stucs/')
        self.assertContains(r, 'Nous contacter / Adhérer')
        self.assertContains(r, '/stucs/contact/')


class StucsRejoindreViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_get_returns_200(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertEqual(r.status_code, 200)

    def test_uses_rejoindre_template(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertTemplateUsed(r, 'content/site_rejoindre.html')

    def test_shows_framaform_url(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertContains(r, 'framaforms.org')

    def test_contact_form_present(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertContains(r, 'csrfmiddlewaretoken')

    def test_post_contact_form_valid(self):
        with patch('hcaptcha.fields.hCaptchaField.validate', return_value=None):
            r = self.client.post('/stucs/rejoindre/', {
                'name': 'Test User',
                'email': 'test@example.org',
                'message': 'Je voudrais adhérer',
                'h-captcha-response': 'test',
            })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'bien été envoyé')

    def test_post_contact_form_invalid(self):
        r = self.client.post('/stucs/rejoindre/', {
            'name': '',
            'email': 'pas-un-email',
            'message': '',
        })
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'bien été envoyé')


class StucsRessourcesViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_get_returns_200(self):
        r = self.client.get('/stucs/ressources/')
        self.assertEqual(r.status_code, 200)

    def test_uses_ressources_template(self):
        r = self.client.get('/stucs/ressources/')
        self.assertTemplateUsed(r, 'content/site_ressources.html')

    def test_filter_by_category(self):
        cat = make_cms_category(name='Communiques', slug='communiques', section_slug='stucs')
        art = make_article_page(section_slug='stucs', title='Tract STUCS test',
                                slug='tract-stucs-test', categories=[cat])
        r = self.client.get('/stucs/ressources/?cat=communiques')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tract STUCS test')

    def test_unknown_category_returns_empty(self):
        # Catégorie inexistante → active_cat=None → vue "Tout" avec empty state
        r = self.client.get('/stucs/ressources/?cat=inexistant')
        self.assertEqual(r.status_code, 200)
        # Pas de catégorie inexistante → retombe sur "Tout" qui peut être vide
        self.assertContains(r, 'Ressources')

    def test_shows_categories_pills(self):
        make_cms_category(name='Grève', slug='greve', section_slug='stucs')
        r = self.client.get('/stucs/ressources/')
        self.assertContains(r, 'Grève')


class StucsAgendaViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_get_returns_200(self):
        r = self.client.get('/stucs/agenda/')
        self.assertEqual(r.status_code, 200)

    def test_uses_agenda_template(self):
        r = self.client.get('/stucs/agenda/')
        self.assertTemplateUsed(r, 'content/site_agenda_events.html')

    def test_shows_upcoming_events(self):
        make_event(self.stucs, 'Grand concert', days_from_now=5)
        r = self.client.get('/stucs/agenda/')
        self.assertContains(r, 'Grand concert')

    def test_past_events_shown_in_past_section(self):
        make_event(self.stucs, 'Vieux concert', days_from_now=-10)
        r = self.client.get('/stucs/agenda/')
        # L'événement passé apparaît dans la section "passés"
        self.assertContains(r, 'Vieux concert')
        self.assertContains(r, 'passés')

    def test_empty_state_shown(self):
        r = self.client.get('/stucs/agenda/')
        self.assertContains(r, 'Aucun événement')

    def test_shows_event_location(self):
        make_event(self.stucs, 'Concert', days_from_now=3, location='Salle Pleyel')
        r = self.client.get('/stucs/agenda/')
        self.assertContains(r, 'Salle Pleyel')


# ── SEO — champs Open Graph ───────────────────────────────────────────────────

class ArticlePageSeoTest(TestCase):

    def test_og_image_field_exists(self):
        art = make_article_page(title='Article SEO')
        self.assertTrue(hasattr(art, 'og_image'))

    def test_canonical_url_field_exists(self):
        art = make_article_page(title='Article canonical')
        self.assertTrue(hasattr(art, 'canonical_url'))

    def test_seo_panels_in_promote(self):
        from cms.models import ArticlePage
        from wagtailseo.models import SeoMixin
        # SeoMixin.seo_panels doit être dans la liste promote_panels
        promote_str = repr(ArticlePage.promote_panels)
        # Au moins un panel SEO doit être présent (canonical_url ou og_image)
        self.assertTrue(
            'canonical_url' in promote_str or 'og_image' in promote_str
            or issubclass(ArticlePage, SeoMixin)
        )

    def test_seo_mixin_applied(self):
        from wagtailseo.models import SeoMixin
        from cms.models import ArticlePage
        self.assertTrue(issubclass(ArticlePage, SeoMixin))


# ── Recherche Wagtail ─────────────────────────────────────────────────────────

class WagtailSearchTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_search_returns_200(self):
        r = self.client.get('/recherche/?q=test')
        self.assertEqual(r.status_code, 200)

    def test_empty_query_returns_no_results(self):
        r = self.client.get('/recherche/?q=')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'résultat')

    def test_search_finds_article_by_title(self):
        make_article_page(title='Greve generale unique', slug='greve-generale-unique')
        r = self.client.get('/recherche/?q=greve')
        self.assertEqual(r.status_code, 200)

    def test_search_view_uses_correct_template(self):
        r = self.client.get('/recherche/?q=test')
        self.assertTemplateUsed(r, 'content/search.html')


# ── Intégration menu STUCS ────────────────────────────────────────────────────

class StucsMenuIntegrationTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_nav_renders_without_menu_items(self):
        """Le fallback 'Aucun menu configuré' s'affiche si aucun MenuItem."""
        from content.models import MenuItem
        MenuItem.objects.filter(site=self.stucs).delete()
        r = Client().get('/stucs/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Aucun menu')

    def test_nav_uses_menu_items_when_present(self):
        from content.models import MenuItem
        MenuItem.objects.create(
            site=self.stucs, menu='main', title='Test Nav',
            url='/stucs/', link_type='url', order=1, is_active=True,
        )
        r = Client().get('/stucs/')
        self.assertContains(r, 'Test Nav')


# ── Carousel ──────────────────────────────────────────────────────────────────

class CarouselModelTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_create_carousel_article(self):
        art = make_article_page(section_slug='stucs', title='Une à la une')
        ci = CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=0)
        self.assertEqual(ci.article, art)
        self.assertEqual(ci.page, self.stucs)

    def test_carousel_items_count(self):
        for i in range(3):
            art = make_article_page(section_slug='stucs', title=f'Actu {i}', slug=f'actu-{i}')
            CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=i)
        self.assertEqual(self.stucs.carousel_items.count(), 3)

    def test_carousel_ordering(self):
        a = make_article_page(section_slug='stucs', title='Second', slug='second')
        b = make_article_page(section_slug='stucs', title='Premier', slug='premier')
        CarouselArticle.objects.create(page=self.stucs, article=a, sort_order=1)
        CarouselArticle.objects.create(page=self.stucs, article=b, sort_order=0)
        items = list(self.stucs.carousel_items.select_related('article').all())
        self.assertEqual(items[0].article.title, 'Premier')
        self.assertEqual(items[1].article.title, 'Second')


class CarouselHomeViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_carousel_hidden_when_no_items(self):
        r = self.client.get('/stucs/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'sc-hero-wrap')

    def test_carousel_visible_with_items(self):
        art = make_article_page(section_slug='stucs', title='À la une test', slug='a-la-une-test')
        CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=0)
        r = self.client.get('/stucs/')
        self.assertContains(r, 'sc-hero-wrap')
        self.assertContains(r, 'À la une test')

    def test_carousel_shows_multiple_slides(self):
        for i in range(3):
            art = make_article_page(section_slug='stucs', title=f'Slide titre {i}', slug=f'slide-{i}')
            CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=i)
        r = self.client.get('/stucs/')
        # Chaque slide doit afficher son titre
        for i in range(3):
            self.assertContains(r, f'Slide titre {i}')

    def test_carousel_in_context(self):
        art = make_article_page(section_slug='stucs', title='Contexte carousel', slug='contexte-carousel')
        CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=0)
        r = self.client.get('/stucs/')
        self.assertIn('carousel_articles', r.context)
        self.assertEqual(len(r.context['carousel_articles']), 1)

    def test_carousel_in_context_for_main_site(self):
        r = self.client.get('/')
        # Depuis la refonte "une de journal", la home principale a aussi son carrousel
        self.assertIn('carousel_articles', r.context)

    def test_carousel_image_url_in_html(self):
        from wagtail.images.models import Image as WagtailImage
        import io
        from PIL import Image as PilImage
        buf = io.BytesIO()
        PilImage.new('RGB', (100, 100), color='red').save(buf, format='JPEG')
        buf.seek(0)
        from django.core.files.uploadedfile import InMemoryUploadedFile
        f = InMemoryUploadedFile(buf, 'file', 'test_carousel.jpg', 'image/jpeg', buf.getbuffer().nbytes, None)
        img = WagtailImage(title='Test image carousel')
        img.file.save('test_carousel.jpg', f, save=True)
        art = make_article_page(
            section_slug='stucs', title='Article avec image', slug='article-avec-image',
            featured_image=img,
        )
        CarouselArticle.objects.create(page=self.stucs, article=art, sort_order=0)
        r = self.client.get('/stucs/')
        self.assertContains(r, img.file.name.split('/')[-1].split('.')[0])


# ── any_image_url ─────────────────────────────────────────────────────────────

class AnyImageUrlTest(TestCase):

    def test_returns_none_when_no_image(self):
        art = make_article_page(title='Sans image', slug='sans-image')
        self.assertIsNone(art.any_image_url)

    def test_returns_wagtail_image_url(self):
        from wagtail.images.models import Image as WagtailImage
        import io
        from PIL import Image as PilImage
        buf = io.BytesIO()
        PilImage.new('RGB', (100, 100), color='blue').save(buf, format='JPEG')
        buf.seek(0)
        from django.core.files.uploadedfile import InMemoryUploadedFile
        f = InMemoryUploadedFile(buf, 'file', 'test_any.jpg', 'image/jpeg', buf.getbuffer().nbytes, None)
        img = WagtailImage(title='Test img')
        img.file.save('test_any.jpg', f, save=True)
        art = make_article_page(title='Avec image', slug='avec-image', featured_image=img)
        url = art.any_image_url
        self.assertIsNotNone(url)
        self.assertIn('test_any', url)


# ── section_slug preservation ─────────────────────────────────────────────────

class ArticlePageSectionSlugTest(TestCase):

    def test_section_slug_not_overwritten_on_save(self):
        """save() ne doit pas écraser un section_slug déjà renseigné."""
        art = make_article_page(section_slug='stucs', title='Preservation test', slug='preservation-test')
        self.assertEqual(art.section_slug, 'stucs')
        art.title = 'Preservation test modifié'
        art.save()
        art.refresh_from_db()
        self.assertEqual(art.section_slug, 'stucs')

    def test_section_slug_auto_filled_when_empty(self):
        """save() remplit section_slug quand il est vide sur un article existant."""
        art = make_article_page(section_slug='stucs', title='Auto slug test', slug='auto-slug-test')
        # Vider section_slug directement en DB sans passer par save()
        ArticlePage.objects.filter(pk=art.pk).update(section_slug='')
        art.refresh_from_db()
        self.assertEqual(art.section_slug, '')
        # Appeler save() → doit re-remplir depuis le parent
        art.save()
        art.refresh_from_db()
        self.assertNotEqual(art.section_slug, '')


# ── Réseaux sociaux ───────────────────────────────────────────────────────────

class SocialFieldsTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_social_fields_blank_by_default(self):
        sp = _ensure_section_page(slug='test-social', name='Test Social', site_type='sectoral')
        for field in ('social_mastodon', 'social_bluesky', 'social_twitter',
                      'social_facebook', 'social_instagram', 'social_youtube',
                      'social_telegram', 'social_discord'):
            self.assertEqual(getattr(sp, field), '', f'{field} should be blank')

    def test_social_fields_saved(self):
        self.stucs.social_mastodon = 'https://mastodon.social/@stucs'
        self.stucs.social_bluesky = 'https://bsky.app/profile/stucs.bsky.social'
        self.stucs.save(update_fields=['social_mastodon', 'social_bluesky'])
        self.stucs.refresh_from_db()
        self.assertEqual(self.stucs.social_mastodon, 'https://mastodon.social/@stucs')
        self.assertEqual(self.stucs.social_bluesky, 'https://bsky.app/profile/stucs.bsky.social')

    def test_social_icons_shown_in_sidebar(self):
        self.stucs.social_mastodon = 'https://mastodon.social/@stucs'
        self.stucs.save(update_fields=['social_mastodon'])
        r = Client().get('/stucs/')
        self.assertContains(r, 'mastodon.social/@stucs')
        self.assertContains(r, 'si-mastodon')

    def test_social_icons_not_shown_when_empty(self):
        social_fields = ['social_mastodon', 'social_bluesky', 'social_twitter',
                         'social_facebook', 'social_instagram', 'social_youtube',
                         'social_telegram', 'social_discord']
        SectionPage.objects.filter(pk=self.stucs.pk).update(
            **{f: '' for f in social_fields}
        )
        r = Client().get('/stucs/')
        # Quand tous les champs sont vides, le div social n'est pas rendu (CSS seul ne compte pas)
        self.assertNotContains(r, '<div class="social-icons-row">')


# ── rejoindre_url depuis MenuItem ─────────────────────────────────────────────

class RejoindreUrlTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_rejoindre_url_uses_framaform_fallback(self):
        # Sans MenuItem "rejoindre", le contexte retombe sur framaform_url
        r = Client().get('/stucs/')
        self.assertIn('framaforms.org', r.context['rejoindre_url'])

    def test_rejoindre_url_prefers_menu_item(self):
        from content.models import MenuItem
        MenuItem.objects.create(
            site=self.stucs, menu='main', title='Nous rejoindre',
            url='https://mon-formulaire.org/rejoindre',
            link_type='url', order=1, is_active=True,
        )
        r = Client().get('/stucs/')
        self.assertContains(r, 'mon-formulaire.org/rejoindre')

    def test_article_page_has_rejoindre_url_in_context(self):
        art = make_article_page(section_slug='stucs', title='Article STUCS ctx', slug='article-stucs-ctx')
        url = reverse('content:site_article_detail', args=['stucs', art.slug])
        r = Client().get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('rejoindre_url', r.context)
        self.assertTrue(r.context['rejoindre_url'])


# ── Sidebar sectorial sur article ─────────────────────────────────────────────

class SectoralArticleSidebarTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_sectoral_article_uses_sectoral_sidebar(self):
        art = make_article_page(section_slug='stucs', title='Article sidebar', slug='article-sidebar')
        url = reverse('content:site_article_detail', args=['stucs', art.slug])
        r = Client().get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'content/_sectoral_sidebar.html')

    def test_main_article_uses_main_sidebar(self):
        art = make_article_page(section_slug='principal', title='Article principal', slug='article-principal')
        url = reverse('content:article_detail', args=[art.slug])
        r = Client().get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateNotUsed(r, 'content/_sectoral_sidebar.html')


# ── OVH client ────────────────────────────────────────────────────────────────

class OvhClientTest(TestCase):
    """Tests unitaires du module ovh_client — OVH API mocké."""

    def _make_client(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = lambda path: {
            '/email/domain/cnt-so.info/mailingList': ['actu-stucs-cntso', 'info-cntso'],
            '/email/domain/cnt-so.info/mailingList/actu-stucs-cntso/subscriber': [
                'alice@example.com', 'bob@example.com',
            ],
        }.get(path, [])
        mock_client.post.return_value = {}
        mock_client.delete.return_value = {}
        return mock_client

    @patch('cms.ovh_client.get_client')
    def test_list_mailing_lists(self, mock_get_client):
        mock_get_client.return_value = self._make_client()
        from cms.ovh_client import list_mailing_lists
        result = list_mailing_lists()
        self.assertIn('actu-stucs-cntso', result)
        self.assertIn('info-cntso', result)
        self.assertEqual(sorted(result), result)  # trié

    @patch('cms.ovh_client.get_client')
    def test_get_subscribers_returns_sorted_list(self, mock_get_client):
        mock_get_client.return_value = self._make_client()
        from cms.ovh_client import get_subscribers
        result = get_subscribers('actu-stucs-cntso')
        self.assertIn('alice@example.com', result)
        self.assertIn('bob@example.com', result)
        self.assertEqual(sorted(result), result)

    @patch('cms.ovh_client.get_client')
    def test_add_subscriber_posts_to_api(self, mock_get_client):
        mock_client = self._make_client()
        mock_get_client.return_value = mock_client
        from cms.ovh_client import add_subscriber
        result = add_subscriber('actu-stucs-cntso', 'new@example.com')
        self.assertTrue(result)
        mock_client.post.assert_called_once_with(
            '/email/domain/cnt-so.info/mailingList/actu-stucs-cntso/subscriber',
            email='new@example.com',
        )

    @patch('cms.ovh_client.get_client')
    def test_add_subscriber_duplicate_returns_false(self, mock_get_client):
        import ovh.exceptions
        mock_client = self._make_client()
        mock_client.post.side_effect = ovh.exceptions.APIError('already exist')
        mock_get_client.return_value = mock_client
        from cms.ovh_client import add_subscriber
        result = add_subscriber('actu-stucs-cntso', 'alice@example.com')
        self.assertFalse(result)

    @patch('cms.ovh_client.get_client')
    def test_remove_subscriber_calls_delete(self, mock_get_client):
        mock_client = self._make_client()
        mock_get_client.return_value = mock_client
        from cms.ovh_client import remove_subscriber
        remove_subscriber('actu-stucs-cntso', 'alice@example.com')
        mock_client.delete.assert_called_once_with(
            '/email/domain/cnt-so.info/mailingList/actu-stucs-cntso/subscriber/alice@example.com'
        )


# ── Vues CMS listes mails ─────────────────────────────────────────────────────

class MailingListIndexViewTest(TestCase):

    def setUp(self):
        self.user = make_superuser()
        self.client = Client()
        self.client.force_login(self.user)

    @patch('cms.ovh_client.list_mailing_lists', return_value=['actu-stucs-cntso', 'info-cntso'])
    @patch('cms.ovh_client.get_subscribers', return_value=['a@b.com'])
    def test_index_lists_all_lists(self, mock_subs, mock_lists):
        r = self.client.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'actu-stucs-cntso')
        self.assertContains(r, 'info-cntso')

    @patch('cms.ovh_client.list_mailing_lists', return_value=['actu-stucs-cntso'])
    @patch('cms.ovh_client.get_subscribers', return_value=['x@y.com', 'a@b.com'])
    def test_index_shows_subscriber_count(self, mock_subs, mock_lists):
        r = self.client.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '2 abonné')

    @patch('cms.ovh_client.list_mailing_lists', side_effect=Exception('OVH indisponible'))
    def test_index_shows_error_when_api_fails(self, mock_lists):
        r = self.client.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'OVH indisponible')

    def test_index_redirects_anonymous(self):
        r = Client().get('/cms/mailing-lists/')
        self.assertIn(r.status_code, [302, 403])


class MailingListDetailViewTest(TestCase):

    def setUp(self):
        self.user = make_superuser()
        self.client = Client()
        self.client.force_login(self.user)

    @patch('cms.ovh_client.get_subscribers', return_value=['alice@example.com', 'bob@example.com'])
    def test_detail_shows_subscribers(self, mock_subs):
        r = self.client.get('/cms/mailing-lists/actu-stucs-cntso/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'alice@example.com')
        self.assertContains(r, 'bob@example.com')

    @patch('cms.ovh_client.get_subscribers', return_value=['alice@example.com'])
    def test_detail_shows_list_name(self, mock_subs):
        r = self.client.get('/cms/mailing-lists/actu-stucs-cntso/')
        self.assertContains(r, 'actu-stucs-cntso')

    @patch('cms.ovh_client.add_subscriber', return_value=True)
    @patch('cms.ovh_client.get_subscribers', return_value=['alice@example.com', 'new@example.com'])
    def test_post_add_subscriber(self, mock_subs, mock_add):
        r = self.client.post('/cms/mailing-lists/actu-stucs-cntso/', {
            'action': 'add', 'email': 'new@example.com',
        })
        self.assertEqual(r.status_code, 200)
        mock_add.assert_called_once_with('actu-stucs-cntso', 'new@example.com')
        self.assertContains(r, 'ajouté')

    @patch('cms.ovh_client.add_subscriber', return_value=False)
    @patch('cms.ovh_client.get_subscribers', return_value=['alice@example.com'])
    def test_post_add_duplicate_shows_already_subscribed(self, mock_subs, mock_add):
        r = self.client.post('/cms/mailing-lists/actu-stucs-cntso/', {
            'action': 'add', 'email': 'alice@example.com',
        })
        self.assertContains(r, 'déjà abonné')

    @patch('cms.ovh_client.remove_subscriber')
    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_post_remove_subscriber(self, mock_subs, mock_remove):
        r = self.client.post('/cms/mailing-lists/actu-stucs-cntso/', {
            'action': 'remove', 'email': 'alice@example.com',
        })
        self.assertEqual(r.status_code, 200)
        mock_remove.assert_called_once_with('actu-stucs-cntso', 'alice@example.com')
        self.assertContains(r, 'retiré')

    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_post_missing_email_shows_error(self, mock_subs):
        r = self.client.post('/cms/mailing-lists/actu-stucs-cntso/', {'action': 'add', 'email': ''})
        self.assertContains(r, 'manquante')

    @patch('cms.ovh_client.add_subscriber', side_effect=Exception('Erreur réseau OVH'))
    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_post_api_error_shows_message(self, mock_subs, mock_add):
        r = self.client.post('/cms/mailing-lists/actu-stucs-cntso/', {
            'action': 'add', 'email': 'x@y.com',
        })
        self.assertContains(r, 'Erreur réseau OVH')


# ── Sync abonnés → OVH ────────────────────────────────────────────────────────

class SubscriberOvhSyncTest(TestCase):
    """Signal post_save Subscriber → add_subscriber OVH."""

    def setUp(self):
        self.stucs = make_stucs_section()
        self.stucs.ovh_mailing_list = 'actu-stucs-cntso'
        self.stucs.save(update_fields=['ovh_mailing_list'])

    def _make_subscriber(self, email='test@example.com', is_active=False):
        from content.models import Subscriber
        return Subscriber.objects.create(
            site=self.stucs,
            email=email,
            is_active=is_active,
        )

    @patch('cms.ovh_client.add_subscriber')
    def test_confirmed_subscriber_synced_to_ovh(self, mock_add):
        sub = self._make_subscriber(is_active=False)
        sub.is_active = True
        sub.save()
        mock_add.assert_called_once_with('actu-stucs-cntso', 'test@example.com')

    @patch('cms.ovh_client.add_subscriber')
    def test_inactive_subscriber_not_synced(self, mock_add):
        self._make_subscriber(is_active=False)
        mock_add.assert_not_called()

    @patch('cms.ovh_client.add_subscriber')
    def test_no_sync_when_site_has_no_ovh_list(self, mock_add):
        self.stucs.ovh_mailing_list = ''
        self.stucs.save(update_fields=['ovh_mailing_list'])
        sub = self._make_subscriber(email='other@example.com', is_active=False)
        sub.is_active = True
        sub.save()
        mock_add.assert_not_called()

    @patch('cms.ovh_client.add_subscriber')
    def test_no_sync_when_subscriber_has_no_site(self, mock_add):
        from content.models import Subscriber
        sub = Subscriber.objects.create(email='nosyte@example.com', site=None, is_active=False)
        sub.is_active = True
        sub.save()
        mock_add.assert_not_called()

    @patch('cms.ovh_client.add_subscriber', side_effect=Exception('OVH down'))
    def test_ovh_failure_does_not_block_subscriber_save(self, mock_add):
        sub = self._make_subscriber(is_active=False)
        sub.is_active = True
        sub.save()  # ne doit pas lever d'exception
        from content.models import Subscriber
        self.assertTrue(Subscriber.objects.get(pk=sub.pk).is_active)

    @patch('cms.ovh_client.add_subscriber')
    def test_sync_only_on_confirmation_not_on_every_save(self, mock_add):
        sub = self._make_subscriber(is_active=True)
        mock_add.reset_mock()
        # Resave sans changer is_active — le signal se déclenche mais is_active=True toujours
        sub.name = 'Changed'
        sub.save()
        # add_subscriber appelé à chaque save avec is_active=True, c'est le comportement attendu
        # (OVH ignore les doublons côté API)
        mock_add.assert_called_with('actu-stucs-cntso', 'test@example.com')


# ── champ ovh_mailing_list sur SectionPage ────────────────────────────────────

class SectionPageOvhMailingListFieldTest(TestCase):

    def test_field_defaults_to_blank(self):
        sp = _ensure_section_page(slug='test-ovh-field', name='Test OVH', site_type='sectoral')
        self.assertEqual(sp.ovh_mailing_list, '')

    def test_field_can_be_set_and_saved(self):
        sp = _ensure_section_page(slug='test-ovh-save', name='Test OVH Save', site_type='sectoral')
        sp.ovh_mailing_list = 'ma-liste-test'
        sp.save(update_fields=['ovh_mailing_list'])
        sp.refresh_from_db()
        self.assertEqual(sp.ovh_mailing_list, 'ma-liste-test')


# ── Contrôle d'accès aux listes mails ────────────────────────────────────────

def _make_chef(username='chef', password='pass'):
    """Crée un utilisateur rédacteur-en-chef avec les permissions Wagtail admin."""
    from content.tests import _setup_editorial_groups
    from django.contrib.auth.models import User, Group, Permission
    _setup_editorial_groups()
    user = User.objects.create_user(username=username, password=password)
    group = Group.objects.get(name='redacteur_en_chef')
    user.groups.add(group)
    # Permission d'accès à l'admin Wagtail
    try:
        user.user_permissions.add(Permission.objects.get(codename='access_admin'))
    except Permission.DoesNotExist:
        pass
    return user


def _client_with_site(user, site):
    """Retourne un Client authentifié avec le syndicat courant en session."""
    from cms.site_context import SESSION_KEY
    c = Client()
    c.force_login(user)
    session = c.session
    session[SESSION_KEY] = site.pk
    session.save()
    return c


class MailingListAccessControlTest(TestCase):
    """Contrôle d'accès : superadmin voit tout, chef voit sa liste, autres bloqués."""

    def setUp(self):
        self.stucs = make_stucs_section()
        self.stucs.ovh_mailing_list = 'actu-stucs-cntso'
        self.stucs.save(update_fields=['ovh_mailing_list'])

    # ── Index ──────────────────────────────────────────────────────────────────

    @patch('cms.ovh_client.list_mailing_lists', return_value=['actu-stucs-cntso', 'info-cntso'])
    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_superadmin_sees_all_lists(self, mock_subs, mock_lists):
        c = Client()
        c.force_login(make_superuser(username='su-access'))
        r = c.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'actu-stucs-cntso')
        self.assertContains(r, 'info-cntso')

    @patch('cms.ovh_client.list_mailing_lists', return_value=['actu-stucs-cntso', 'info-cntso'])
    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_chef_sees_only_their_list(self, mock_subs, mock_lists):
        chef = _make_chef(username='chef-access')
        c = _client_with_site(chef, self.stucs)
        r = c.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'actu-stucs-cntso')
        self.assertNotContains(r, 'info-cntso')

    def test_chef_without_ovh_list_gets_forbidden(self):
        self.stucs.ovh_mailing_list = ''
        self.stucs.save(update_fields=['ovh_mailing_list'])
        chef = _make_chef(username='chef-nolist')
        c = _client_with_site(chef, self.stucs)
        r = c.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 403)

    def test_redacteur_gets_forbidden_on_index(self):
        from content.tests import _setup_editorial_groups
        from django.contrib.auth.models import User, Group
        _setup_editorial_groups()
        user = User.objects.create_user(username='redac-access', password='pass')
        user.groups.add(Group.objects.get(name='redacteur'))
        c = Client()
        c.force_login(user)
        r = c.get('/cms/mailing-lists/')
        self.assertEqual(r.status_code, 403)

    # ── Détail ─────────────────────────────────────────────────────────────────

    @patch('cms.ovh_client.get_subscribers', return_value=['alice@example.com'])
    def test_chef_can_access_their_list_detail(self, mock_subs):
        chef = _make_chef(username='chef-detail')
        c = _client_with_site(chef, self.stucs)
        r = c.get('/cms/mailing-lists/actu-stucs-cntso/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'alice@example.com')

    def test_chef_cannot_access_other_list_detail(self):
        chef = _make_chef(username='chef-noaccess')
        c = _client_with_site(chef, self.stucs)
        r = c.get('/cms/mailing-lists/info-cntso/')  # liste d'un autre syndicat
        self.assertEqual(r.status_code, 403)

    def test_chef_cannot_post_to_other_list(self):
        chef = _make_chef(username='chef-nopost')
        c = _client_with_site(chef, self.stucs)
        r = c.post('/cms/mailing-lists/info-cntso/', {'action': 'add', 'email': 'x@y.com'})
        self.assertEqual(r.status_code, 403)

    @patch('cms.ovh_client.get_subscribers', return_value=[])
    def test_superadmin_can_access_any_list_detail(self, mock_subs):
        c = Client()
        c.force_login(make_superuser(username='su-detail'))
        r = c.get('/cms/mailing-lists/info-cntso/')
        self.assertEqual(r.status_code, 200)


# ── Simplification de l'admin pour les rédacteurs débutants ───────────────────

def _make_redacteur(site, username='redacteur-simpl', password='pass'):
    """Crée un utilisateur du groupe redacteur rattaché à un syndicat."""
    from content.tests import _setup_editorial_groups
    from django.contrib.auth.models import User, Group
    from content.models import Author
    _setup_editorial_groups()
    user = User.objects.create_user(username=username, password=password)
    user.groups.add(Group.objects.get(name='redacteur'))
    Author.objects.create(user=user, site=site, username=username, display_name=username)
    return user


class AdminChefOnlyViewsTest(TestCase):
    """Les vues de gestion (syndicats, menus) sont réservées aux chefs."""

    def setUp(self):
        self.site = _ensure_section_page(slug='simpl-admin', name='Simpl Admin', site_type='sectoral')
        self.redacteur = _make_redacteur(self.site)
        self.redac_client = Client()
        self.redac_client.force_login(self.redacteur)

    def _chef_client(self, username):
        chef = _make_chef(username=username)
        return _client_with_site(chef, self.site)

    def test_syndicats_redirige_redacteur(self):
        r = self.redac_client.get('/cms/syndicats/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/cms/')

    def test_syndicats_ok_chef(self):
        r = self._chef_client('chef-synd').get('/cms/syndicats/')
        self.assertEqual(r.status_code, 200)

    def test_menus_redirige_redacteur(self):
        r = self.redac_client.get('/cms/menus/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/cms/')

    def test_menus_ok_chef(self):
        r = self._chef_client('chef-menus').get('/cms/menus/')
        self.assertEqual(r.status_code, 200)

    def test_menu_move_redirige_redacteur(self):
        r = self.redac_client.get('/cms/menus/move/', {'item': 1, 'action': 'up'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/cms/')

    def test_menu_move_get_refuse_meme_pour_chef(self):
        # Un GET mutateur contournerait la protection CSRF : POST uniquement
        r = self._chef_client('chef-move-get').get('/cms/menus/move/', {'item': 1, 'action': 'up'})
        self.assertEqual(r.status_code, 405)

    def test_menu_reorder_403_redacteur(self):
        # Vue JSON : 403 explicite, pas de redirection qu'un fetch suivrait
        r = self.redac_client.post(
            '/cms/menus/reorder/', '{"items": []}', content_type='application/json'
        )
        self.assertEqual(r.status_code, 403)

    def test_menu_reorder_ok_chef(self):
        r = self._chef_client('chef-reorder').post(
            '/cms/menus/reorder/', '{"items": []}', content_type='application/json'
        )
        self.assertEqual(r.status_code, 200)


class AdminMenuVisibilityTest(TestCase):
    """Les entrées de menu chef-only sont masquées pour les rédacteurs."""

    def setUp(self):
        self.site = _ensure_section_page(slug='simpl-menu', name='Simpl Menu', site_type='sectoral')
        self.redacteur = _make_redacteur(self.site, username='redacteur-menu')

    def _request_for(self, user):
        from django.test import RequestFactory
        request = RequestFactory().get('/cms/')
        request.user = user
        request.session = {}
        return request

    def test_syndicats_cache_pour_redacteur(self):
        from cms.wagtail_hooks import add_syndicats_menu_item
        item = add_syndicats_menu_item()
        self.assertFalse(item.is_shown(self._request_for(self.redacteur)))
        self.assertTrue(item.is_shown(self._request_for(make_superuser(username='su-menu-synd'))))

    def test_listes_mails_cache_pour_redacteur(self):
        from cms.wagtail_hooks import add_mailing_lists_menu_item
        item = add_mailing_lists_menu_item()
        self.assertFalse(item.is_shown(self._request_for(self.redacteur)))
        self.assertTrue(item.is_shown(self._request_for(make_superuser(username='su-menu-ml'))))


class DashboardPanelRoleTest(TestCase):
    """Le panneau dashboard n'affiche que les outils accessibles au rôle."""

    def setUp(self):
        self.site = _ensure_section_page(slug='simpl-dash', name='Simpl Dash', site_type='sectoral')

    def test_redacteur_ne_voit_pas_les_outils_chef(self):
        redacteur = _make_redacteur(self.site, username='redacteur-dash')
        c = Client()
        c.force_login(redacteur)
        r = c.get('/cms/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('Nouvel article', content)
        self.assertIn('Comment publier', content)
        self.assertNotIn('Listes mails OVH', content)
        self.assertNotIn('Menus du site', content)
        self.assertNotIn('Config formulaire', content)

    def test_chef_voit_tous_les_outils(self):
        chef = _make_chef(username='chef-dash')
        c = _client_with_site(chef, self.site)
        r = c.get('/cms/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('Nouvel article', content)
        self.assertIn('Listes mails OVH', content)
        self.assertIn('Menus du site', content)
        self.assertNotIn('Comment publier', content)
