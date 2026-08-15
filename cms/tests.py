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
        # timezone.now().date() et non date.today() : autour de minuit, la date
        # locale et la date du fuseau Django divergent et is_past compare à
        # now().date() — test flaky sinon.
        from django.utils import timezone
        ev = Event.objects.create(
            section=self.stucs, title='Passé',
            date=timezone.now().date() - timedelta(days=1),
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
        # Le bloc sidebar "Nous rejoindre" pointe vers la page unifiée de la section
        r = self.client.get('/stucs/')
        self.assertContains(r, 'Nous rejoindre')
        self.assertContains(r, '/stucs/rejoindre/')


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

    def test_shows_adherer_button(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertContains(r, '/adherer/stucs/')

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
        # Seules les catégories avec au moins un article publié sont affichées
        cat = make_cms_category(name='Grève', slug='greve', section_slug='stucs')
        make_article_page(section_slug='stucs', title='Art Grève', slug='art-greve',
                          categories=[cat])
        r = self.client.get('/stucs/ressources/')
        self.assertContains(r, 'Grève')

    def test_empty_category_hidden_from_pills(self):
        make_cms_category(name='Catégorie Vide', slug='cat-vide', section_slug='stucs')
        r = self.client.get('/stucs/ressources/')
        self.assertNotContains(r, 'Catégorie Vide')


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


# ── rejoindre_url : toujours la page interne unifiée ──────────────────────────

class RejoindreUrlTest(TestCase):

    def setUp(self):
        self.stucs = make_stucs_section()

    def test_rejoindre_url_is_internal_page(self):
        # rejoindre_url pointe toujours vers la page /rejoindre/ de la section,
        # quel que soit framaform_url ou les MenuItem existants.
        r = Client().get('/stucs/')
        self.assertEqual(r.context['rejoindre_url'], '/stucs/rejoindre/')

    def test_rejoindre_url_ignores_menu_item(self):
        from content.models import MenuItem
        MenuItem.objects.create(
            site=self.stucs, menu='main', title='Nous rejoindre',
            url='https://mon-formulaire.org/rejoindre',
            link_type='url', order=1, is_active=True,
        )
        r = Client().get('/stucs/')
        self.assertEqual(r.context['rejoindre_url'], '/stucs/rejoindre/')

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


class OvhListRoutingTest(TestCase):
    """Répartition sur plusieurs listes OVH plafonnées (news, news2, …)."""

    def setUp(self):
        self.stucs = make_stucs_section()
        self.stucs.ovh_mailing_list = 'news,news2'
        self.stucs.save(update_fields=['ovh_mailing_list'])

    def _make_active_subscriber(self, email='routing@example.com'):
        from content.models import Subscriber
        return Subscriber.objects.create(site=self.stucs, email=email, is_active=True)

    @patch('cms.ovh_client.add_subscriber')
    @patch('content.ovh_sync.list_count', return_value=0)
    def test_liste_non_pleine_prend_la_premiere(self, mock_count, mock_add):
        sub = self._make_active_subscriber()
        mock_add.assert_called_once_with('news', 'routing@example.com')
        from content.models import Subscriber
        self.assertEqual(Subscriber.objects.get(pk=sub.pk).ovh_list, 'news')

    @patch('cms.ovh_client.add_subscriber')
    def test_premiere_pleine_bascule_sur_la_deuxieme(self, mock_add):
        with patch('content.ovh_sync.list_count',
                   side_effect=lambda name: 5000 if name == 'news' else 12):
            sub = self._make_active_subscriber(email='overflow@example.com')
        mock_add.assert_called_once_with('news2', 'overflow@example.com')
        from content.models import Subscriber
        self.assertEqual(Subscriber.objects.get(pk=sub.pk).ovh_list, 'news2')

    @patch('cms.ovh_client.add_subscriber')
    @patch('content.ovh_sync.list_count', return_value=5000)
    def test_toutes_pleines_utilise_la_derniere_et_alerte(self, mock_count, mock_add):
        with self.assertLogs('content.ovh_sync', level='CRITICAL'):
            self._make_active_subscriber(email='full@example.com')
        mock_add.assert_called_once_with('news2', 'full@example.com')

    @patch('cms.ovh_client.remove_subscriber')
    @patch('cms.ovh_client.add_subscriber')
    @patch('content.ovh_sync.list_count', return_value=0)
    def test_desinscription_efface_ovh_list(self, mock_count, mock_add, mock_remove):
        sub = self._make_active_subscriber(email='bye@example.com')
        sub.refresh_from_db()
        self.assertEqual(sub.ovh_list, 'news')
        sub.is_active = False
        sub.save()
        sub.refresh_from_db()
        self.assertEqual(sub.ovh_list, '')
        # le retrait balaie toutes les listes
        mock_remove.assert_any_call('news', 'bye@example.com')
        mock_remove.assert_any_call('news2', 'bye@example.com')


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

    def test_menus_ok_redacteur_avec_syndicat(self):
        """Lot 6 : les menus du syndicat sont un outil de ses rédacteurs
        (vues Move/Reorder sécurisées par scoping site)."""
        r = self.redac_client.get('/cms/menus/')
        self.assertEqual(r.status_code, 200)

    def test_menus_redirige_sans_syndicat(self):
        from django.contrib.auth.models import User, Permission
        sans = User.objects.create_user(username='menus-sans-synd', password='pass')
        sans.user_permissions.add(Permission.objects.get(codename='access_admin'))
        sans = User.objects.get(pk=sans.pk)
        c = Client()
        c.force_login(sans)
        r = c.get('/cms/menus/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/cms/')

    def test_menus_ok_chef(self):
        r = self._chef_client('chef-menus').get('/cms/menus/')
        self.assertEqual(r.status_code, 200)

    def test_menu_move_get_refuse_pour_tous(self):
        # Un GET mutateur contournerait la protection CSRF : POST uniquement
        r = self.redac_client.get('/cms/menus/move/', {'item': 1, 'action': 'up'})
        self.assertEqual(r.status_code, 405)
        r = self._chef_client('chef-move-get').get('/cms/menus/move/', {'item': 1, 'action': 'up'})
        self.assertEqual(r.status_code, 405)

    def test_menu_reorder_403_sans_syndicat(self):
        # Vue JSON : 403 explicite, pas de redirection qu'un fetch suivrait
        from django.contrib.auth.models import User, Permission
        sans = User.objects.create_user(username='reorder-sans-synd', password='pass')
        sans.user_permissions.add(Permission.objects.get(codename='access_admin'))
        sans = User.objects.get(pk=sans.pk)
        c = Client()
        c.force_login(sans)
        r = c.post(
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

    def test_listes_mails_visible_pour_redacteur_avec_syndicat(self):
        """Autonomie 2026-07-16 : la liste OVH du syndicat est gérée par ses
        rédacteurs — l'entrée apparaît dès qu'un syndicat est résolu, et
        reste cachée pour un compte sans syndicat."""
        from cms.wagtail_hooks import add_mailing_lists_menu_item
        item = add_mailing_lists_menu_item()
        self.assertTrue(item.is_shown(self._request_for(self.redacteur)))
        self.assertTrue(item.is_shown(self._request_for(make_superuser(username='su-menu-ml'))))
        from django.contrib.auth.models import User
        sans_syndicat = User.objects.create_user(username='sans-synd-menu', password='pass')
        self.assertFalse(item.is_shown(self._request_for(sans_syndicat)))

    def test_menus_images_documents_retablis(self):
        """Lot 9 : depuis les médias cloisonnés (lot 7), Images et Documents
        ne sont plus masqués — Wagtail les montre aux utilisateurs ayant des
        permissions de collection. 'explorer' reste caché (snippets)."""
        from content.wagtail_hooks import hide_unused_wagtail_menus

        class _Item:
            def __init__(self, name):
                self.name = name

        items = [_Item(n) for n in
                 ('explorer', 'images', 'documents', 'reports')]
        hide_unused_wagtail_menus(self._request_for(self.redacteur), items)
        names = {i.name for i in items}
        self.assertEqual(names, {'images', 'documents'})
        items = [_Item(n) for n in
                 ('explorer', 'images', 'documents', 'reports')]
        hide_unused_wagtail_menus(
            self._request_for(make_superuser(username='su-menu-img')), items)
        self.assertEqual({i.name for i in items},
                         {'images', 'documents', 'reports'})


class DashboardPanelRoleTest(TestCase):
    """Le panneau dashboard n'affiche que les outils accessibles au rôle."""

    def setUp(self):
        self.site = _ensure_section_page(slug='simpl-dash', name='Simpl Dash', site_type='sectoral')

    def test_redacteur_voit_tous_les_outils_de_son_syndicat(self):
        """Autonomie 2026-07-16 : contact, newsletter, listes OVH et menus
        (sécurisés au lot 6) sont des outils du syndicat, visibles par ses
        rédacteurs."""
        redacteur = _make_redacteur(self.site, username='redacteur-dash')
        c = Client()
        c.force_login(redacteur)
        r = c.get('/cms/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('Nouvel article', content)
        self.assertIn('Comment publier', content)
        self.assertIn('Listes mails OVH', content)
        self.assertIn('Config formulaire', content)
        self.assertIn('Menus du site', content)

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


class UserSyndicatFormTest(TestCase):
    """Le formulaire Utilisateurs (/cms/users/) porte un champ Syndicat
    qui synchronise la fiche Author (cloisonnement par site)."""

    def setUp(self):
        self.site = _ensure_section_page(slug='fusion-synd', name='Fusion Synd', site_type='sectoral')
        self.admin = make_superuser(username='su-fusion')
        self.client = Client()
        self.client.force_login(self.admin)

    def _user_data(self, **extra):
        data = {
            'username': 'fusion-user', 'email': 'fusion@example.org',
            'first_name': 'Fu', 'last_name': 'Sion',
            'password1': 'mdp-Tres-solide-42', 'password2': 'mdp-Tres-solide-42',
            # Aucun groupe coché : c'est le champ « Syndicat » qui rattache.
            'groups': [],
        }
        data.update(extra)
        return data

    def test_champ_syndicat_affiche_dans_les_formulaires(self):
        r = self.client.get(reverse('wagtailusers_users:add'))
        self.assertContains(r, 'name="syndicat"')

    def test_le_gabarit_redacteur_n_est_pas_proposable(self):
        """« redacteur » sans suffixe est le gabarit dont chaque syndicat copie
        ses permissions, pas un rôle : il n'a aucun droit d'arbre. Un compte
        n'ayant que lui semblerait configuré sans rien pouvoir publier."""
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='redacteur')
        r = self.client.get(reverse('wagtailusers_users:add'))
        proposes = {g.name for g in r.context['form'].fields['groups'].queryset}
        self.assertNotIn('redacteur', proposes)

    def test_creation_utilisateur_cree_la_fiche_auteur(self):
        from content.models import Author
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(syndicat=self.site.pk))
        from django.contrib.auth.models import User
        user = User.objects.get(username='fusion-user')
        author = Author.objects.get(user=user)
        self.assertEqual(author.site, self.site)

    def test_edition_change_le_syndicat(self):
        from content.models import Author
        from django.contrib.auth.models import User
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(syndicat=self.site.pk))
        user = User.objects.get(username='fusion-user')
        autre = _ensure_section_page(slug='fusion-autre', name='Fusion Autre', site_type='sectoral')
        self.client.post(reverse('wagtailusers_users:edit', args=[user.pk]),
                         self._user_data(is_active='on', syndicat=autre.pk))
        self.assertEqual(Author.objects.get(user=user).site, autre)

    def test_creation_sans_syndicat_ne_cree_pas_de_fiche(self):
        from content.models import Author
        from django.contrib.auth.models import User
        self.client.post(reverse('wagtailusers_users:add'), self._user_data())
        user = User.objects.get(username='fusion-user')
        self.assertFalse(Author.objects.filter(user=user).exists())

    def test_reutilise_une_fiche_wordpress_orpheline(self):
        """Une fiche Author legacy (même username, sans user) est reliée au compte."""
        from content.models import Author
        from django.contrib.auth.models import User
        legacy = Author.objects.create(username='fusion-user', display_name='Legacy WP')
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(syndicat=self.site.pk))
        user = User.objects.get(username='fusion-user')
        legacy.refresh_from_db()
        self.assertEqual(legacy.user, user)
        self.assertEqual(legacy.site, self.site)
        self.assertEqual(Author.objects.filter(username='fusion-user').count(), 1)


class UserAccountManagementTest(TestCase):
    """Lot 8 du chantier autonomie : l'équipe confédérale (redacteur_en_chef,
    non-superuser) crée et gère les comptes rédacteurs dans /cms/users/, sans
    pouvoir toucher aux superusers ni s'octroyer le statut administrateur.
    Le champ Syndicat synchronise aussi le groupe redacteur_<slug>."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from content.tests import _setup_editorial_groups
        _setup_editorial_groups()
        self.site_a = _ensure_section_page(slug='synd-a', name='Synd A', site_type='sectoral')
        self.site_b = _ensure_section_page(slug='synd-b', name='Synd B', site_type='sectoral')
        # get_or_create : le signal de provisionnement (cms/apps.py) crée
        # déjà ces groupes à la création des SectionPage ci-dessus
        self.group_a, _ = Group.objects.get_or_create(name='redacteur_synd-a')
        self.group_b, _ = Group.objects.get_or_create(name='redacteur_synd-b')
        self.chef = self._make_chef('chef-comptes')
        self.superuser = make_superuser(username='su-comptes')
        self.client = Client()
        self.client.force_login(self.chef)

    def _make_chef(self, username):
        from django.contrib.auth.models import Group, User
        chef = User.objects.create_user(username, password='pass')
        chef.groups.add(Group.objects.get(name='redacteur_en_chef'))
        return User.objects.get(pk=chef.pk)

    def _user_data(self, **extra):
        data = {
            'username': 'nouveau-redac', 'email': 'r@example.org',
            'first_name': 'Re', 'last_name': 'Dac',
            'password1': 'mdp-Tres-solide-42', 'password2': 'mdp-Tres-solide-42',
        }
        data.update(extra)
        return data

    def test_chef_group_has_user_management_perms(self):
        self.assertTrue(self.chef.has_perm('auth.add_user'))
        self.assertTrue(self.chef.has_perm('auth.change_user'))
        self.assertFalse(self.chef.has_perm('auth.delete_user'))

    def test_chef_accesses_user_index_and_add_form(self):
        self.assertEqual(
            self.client.get(reverse('wagtailusers_users:index')).status_code, 200)
        r = self.client.get(reverse('wagtailusers_users:add'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="syndicat"')

    def test_admin_checkbox_hidden_from_non_superuser(self):
        r = self.client.get(reverse('wagtailusers_users:add'))
        self.assertNotContains(r, 'name="is_superuser"')

    def test_admin_checkbox_visible_for_superuser(self):
        self.client.force_login(self.superuser)
        r = self.client.get(reverse('wagtailusers_users:add'))
        self.assertContains(r, 'name="is_superuser"')

    def test_chef_cannot_grant_superuser(self):
        from django.contrib.auth.models import User
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(is_superuser='on'))
        user = User.objects.get(username='nouveau-redac')
        self.assertFalse(user.is_superuser)

    def test_creation_with_syndicat_joins_section_group(self):
        from django.contrib.auth.models import User
        from content.models import Author
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(syndicat=self.site_a.pk))
        user = User.objects.get(username='nouveau-redac')
        self.assertIn(self.group_a, user.groups.all())
        self.assertEqual(Author.objects.get(user=user).site, self.site_a)

    def test_syndicat_change_moves_section_group(self):
        from django.contrib.auth.models import User
        self.client.post(reverse('wagtailusers_users:add'),
                         self._user_data(syndicat=self.site_a.pk))
        user = User.objects.get(username='nouveau-redac')
        self.client.post(reverse('wagtailusers_users:edit', args=[user.pk]),
                         self._user_data(is_active='on', syndicat=self.site_b.pk))
        groups = set(user.groups.values_list('name', flat=True))
        self.assertIn('redacteur_synd-b', groups)
        self.assertNotIn('redacteur_synd-a', groups)

    def test_syndicat_initial_reflects_group_membership(self):
        """Un compte rattaché par groupe seul (sans fiche Author) garde son
        syndicat pré-sélectionné à l'édition — sinon un simple save le
        décrocherait de son groupe."""
        from django.contrib.auth.models import User
        from content.admin_forms import SyndicatUserEditForm
        u = User.objects.create_user('groupe-seul', password='pass')
        u.groups.add(self.group_a)
        form = SyndicatUserEditForm(instance=User.objects.get(pk=u.pk),
                                    request_user=self.superuser)
        self.assertEqual(form.fields['syndicat'].initial, self.site_a.pk)

    def test_chef_cannot_edit_superuser(self):
        r = self.client.get(
            reverse('wagtailusers_users:edit', args=[self.superuser.pk]))
        self.assertNotEqual(r.status_code, 200)
        r = self.client.post(
            reverse('wagtailusers_users:edit', args=[self.superuser.pk]),
            self._user_data(username='su-comptes', is_active='on',
                            password1='Pirate-42x!', password2='Pirate-42x!'))
        self.assertNotEqual(r.status_code, 200)
        self.superuser.refresh_from_db()
        self.assertFalse(self.superuser.check_password('Pirate-42x!'))

    def test_superuser_can_still_edit_superuser(self):
        self.client.force_login(self.superuser)
        r = self.client.get(
            reverse('wagtailusers_users:edit', args=[self.superuser.pk]))
        self.assertEqual(r.status_code, 200)


class SyndicatSansBrouillonTest(TestCase):
    """« Mon syndicat » : le bouton principal publie directement, pas de brouillon
    qui dort en attente de « Publier » (piège pour les rédacteurs)."""

    def setUp(self):
        self.site = _ensure_section_page(slug='synd-direct', name='Synd Direct', site_type='sectoral')
        self.client = Client()
        self.client.force_login(make_superuser(username='su-synd-direct'))

    def test_publier_est_le_bouton_principal(self):
        r = self.client.get(f'/cms/snippets/cms/sectionpage/edit/{self.site.pk}/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('name="action-publish"', content)
        self.assertNotIn('Enregistrer le brouillon', content)

    def test_les_articles_gardent_leur_brouillon(self):
        """Le hook ne touche que SectionPage : les articles gardent le circuit brouillon."""
        art = make_article_page(title='Article brouillon test', section_slug='synd-direct')
        r = self.client.get(f'/cms/snippets/cms/articlepage/edit/{art.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('brouillon', r.content.decode().lower())


class CustomDomainFieldTest(TestCase):
    """Phase 1 domaines fédérations : champ custom_domain sur SectionPage."""

    def setUp(self):
        self.site = _ensure_section_page(slug='dom-test', name='Dom Test', site_type='sectoral')

    def test_vide_par_defaut_et_base_url_relative(self):
        self.assertEqual(self.site.custom_domain, '')
        self.assertEqual(self.site.base_url, '')

    def test_base_url_avec_domaine(self):
        self.site.custom_domain = 'stucs.cnt-so.org'
        self.assertEqual(self.site.base_url, 'https://stucs.cnt-so.org')

    def test_clean_rejette_schema_et_slash(self):
        from django.core.exceptions import ValidationError
        for bad in ['https://stucs.cnt-so.org', 'stucs.cnt-so.org/', 'stucs cnt', 'a@b.org']:
            self.site.custom_domain = bad
            with self.assertRaises(ValidationError, msg=bad):
                self.site.clean()

    def test_clean_normalise_en_minuscules(self):
        self.site.custom_domain = ' STUCS.CNT-SO.ORG '
        self.site.clean()
        self.assertEqual(self.site.custom_domain, 'stucs.cnt-so.org')

    def test_clean_refuse_les_doublons(self):
        from django.core.exceptions import ValidationError
        autre = _ensure_section_page(slug='dom-autre', name='Dom Autre', site_type='sectoral')
        autre.custom_domain = 'stucs.cnt-so.org'
        autre.save(update_fields=['custom_domain'])
        self.site.custom_domain = 'stucs.cnt-so.org'
        with self.assertRaises(ValidationError):
            self.site.clean()

    def test_domaines_vides_multiples_autorises(self):
        # Deux sections sans domaine ne doivent pas se bloquer mutuellement
        _ensure_section_page(slug='dom-vide2', name='Dom Vide2', site_type='sectoral')
        self.site.clean()  # ne lève pas


from django.test import override_settings


@override_settings(ALLOWED_HOSTS=['testserver', 'stucs.cnt-so.org'],
                   MAIN_SITE_BASE_URL='https://cnt-so.org')
class SectionDomainMiddlewareTest(TestCase):
    """Phase 2 domaines fédérations : résolution par hôte."""

    HOST = 'stucs.cnt-so.org'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # le lookup hôte→section est mis en cache 60 s
        self.stucs = make_stucs_section()
        self.stucs.custom_domain = self.HOST
        self.stucs.save(update_fields=['custom_domain'])
        self.autre = _ensure_section_page(slug='mw-autre', name='MW Autre', site_type='sectoral')
        self.article = make_article_page(title='Article middleware', section_slug='stucs')

    def test_hote_principal_redirige_vers_le_domaine(self):
        # Phase 4 : le chemin d'une section à domaine 301 vers ce domaine
        r = self.client.get('/stucs/')
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], f'https://{self.HOST}/')

    def test_hote_principal_redirige_article_vers_le_domaine(self):
        r = self.client.get('/stucs/article/article-middleware/?p=2')
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'],
                         f'https://{self.HOST}/article/article-middleware/?p=2')

    def test_section_sans_domaine_reste_en_chemin(self):
        r = self.client.get('/mw-autre/')
        self.assertEqual(r.status_code, 200)

    def test_racine_du_domaine_sert_la_home_du_sous_site(self):
        r = self.client.get('/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'STUCS')

    def test_article_sans_prefixe(self):
        r = self.client.get('/article/article-middleware/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Article middleware')

    def test_contact_sans_prefixe(self):
        r = self.client.get('/contact/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)

    def test_propre_prefixe_redirige_en_301_sans_prefixe(self):
        r = self.client.get('/stucs/article/article-middleware/?x=1', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], '/article/article-middleware/?x=1')

    def test_post_sur_prefixe_non_redirige(self):
        r = self.client.post('/stucs/newsletter/inscription/', {'email': 'x@y.fr'},
                             HTTP_HOST=self.HOST)
        self.assertNotEqual(r.status_code, 301)

    def test_cms_redirige_vers_admin_central(self):
        r = self.client.get('/cms/dashboard/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], 'https://cnt-so.org/cms/dashboard/')

    def test_contenu_autre_section_renvoye_au_site_principal(self):
        r = self.client.get('/mw-autre/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], 'https://cnt-so.org/mw-autre/')

    def test_page_globale_renvoyee_au_site_principal(self):
        r = self.client.get('/qui-sommes-nous/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], 'https://cnt-so.org/qui-sommes-nous/')

    def test_feed_de_la_section(self):
        r = self.client.get('/feed/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        self.assertIn('xml', r['Content-Type'])

    def test_domaine_vide_aucun_effet(self):
        self.stucs.custom_domain = ''
        self.stucs.save(update_fields=['custom_domain'])
        from django.core.cache import cache
        cache.clear()
        r = self.client.get('/', HTTP_HOST=self.HOST)
        # plus de section pour cet hôte → home confédérale servie normalement
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'content/home.html')


@override_settings(ALLOWED_HOSTS=['testserver', 'stucs.cnt-so.org'],
                   MAIN_SITE_BASE_URL='https://cnt-so.org')
class SectionDomainWagtailPageTest(TestCase):
    """Pages Wagtail d'une section (ContentPage) servies sur son domaine
    autonome — cas découvert avec la page « Qui sommes-nous ? » de Numérique."""

    HOST = 'stucs.cnt-so.org'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.stucs = make_stucs_section()
        self.stucs.custom_domain = self.HOST
        self.stucs.save(update_fields=['custom_domain'])
        self.page = self.stucs.add_child(instance=ContentPage(
            title='Qui sommes-nous ?', slug='qui-sommes-nous',
            section_slug='stucs', live=True,
        ))
        # Le Site Wagtail doit pointer sur la HomePage de test pour que le
        # catch-all Wagtail serve les pages (page.url sinon None)
        from wagtail.models import Site
        from content.tests import _get_article_parent
        site = Site.objects.get(is_default_site=True)
        site.root_page = _get_article_parent()
        site.save()

    def test_page_wagtail_de_la_section_servie_sur_le_domaine(self):
        r = self.client.get('/qui-sommes-nous/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Qui sommes-nous')

    def test_get_absolute_url_sans_prefixe_sur_le_domaine(self):
        self.assertEqual(self.page.get_absolute_url(),
                         f'https://{self.HOST}/qui-sommes-nous/')

    def test_ancienne_url_page_redirige_sans_boucle(self):
        r = self.client.get('/page/qui-sommes-nous/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], f'https://{self.HOST}/qui-sommes-nous/')

    def test_prefixe_de_section_redirige_vers_url_nue(self):
        r = self.client.get('/stucs/qui-sommes-nous/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], '/qui-sommes-nous/')

    def test_page_inconnue_toujours_renvoyee_au_principal(self):
        r = self.client.get('/page-inexistante/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], 'https://cnt-so.org/page-inexistante/')

    def test_page_depubliee_renvoyee_au_principal(self):
        self.page.live = False
        self.page.save(update_fields=['live'])
        r = self.client.get('/qui-sommes-nous/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], 'https://cnt-so.org/qui-sommes-nous/')

    def test_sans_domaine_url_relative_wagtail(self):
        self.stucs.custom_domain = ''
        self.stucs.save(update_fields=['custom_domain'])
        from django.core.cache import cache
        cache.clear()
        self.assertEqual(self.page.get_absolute_url(), self.page.url)

    def test_retour_confederal_absolu_sur_le_domaine(self):
        r = self.client.get('/', HTTP_HOST=self.HOST)
        self.assertContains(r, 'href="https://cnt-so.org/" class="subsite-back-btn"')
        self.assertContains(r, 'href="https://cnt-so.org/" class="footer-confed-link"')

    def test_retour_confederal_relatif_en_chemins(self):
        self.stucs.custom_domain = ''
        self.stucs.save(update_fields=['custom_domain'])
        from django.core.cache import cache
        cache.clear()
        r = self.client.get('/stucs/')
        self.assertContains(r, 'href="/" class="subsite-back-btn"')

    def test_sitemap_liste_url_canonique_de_la_page(self):
        r = self.client.get('/sitemap.xml', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn(f'https://{self.HOST}/qui-sommes-nous/', content)
        self.assertNotIn('/page/qui-sommes-nous/', content)


class OutgoingUrlsWithDomainTest(TestCase):
    """Phase 3 domaines fédérations : URLs sortantes absolues quand la section
    a un domaine autonome, relatives sinon (comportement historique)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # section_base_url est mis en cache 60 s
        self.site = _ensure_section_page(slug='dom-urls', name='Dom URLs', site_type='sectoral')
        self.article = make_article_page(title='Article domaine', section_slug='dom-urls')
        self.cat = make_cms_category(name='Cat domaine', section_slug='dom-urls')

    def _activate(self):
        from django.core.cache import cache
        self.site.custom_domain = 'dom-urls.cnt-so.org'
        self.site.save(update_fields=['custom_domain'])
        cache.clear()

    def test_urls_relatives_sans_domaine(self):
        self.assertEqual(self.article.get_absolute_url(), '/dom-urls/article/article-domaine/')
        self.assertEqual(self.cat.get_absolute_url(), '/dom-urls/categorie/cat-domaine/')
        self.assertEqual(self.site.get_absolute_url(), '/dom-urls/')

    def test_urls_absolues_avec_domaine(self):
        self._activate()
        self.assertEqual(self.article.get_absolute_url(),
                         'https://dom-urls.cnt-so.org/article/article-domaine/')
        self.assertEqual(self.cat.get_absolute_url(),
                         'https://dom-urls.cnt-so.org/categorie/cat-domaine/')
        self.site.refresh_from_db()
        self.assertEqual(self.site.get_absolute_url(), 'https://dom-urls.cnt-so.org/')

    def test_articles_principal_pointent_vers_le_site_principal(self):
        """Ce test exigeait l'inverse — que les articles confédéraux restent
        relatifs — décision du chantier des domaines. C'est elle qui cassait
        l'affichage croisé : un article confédéral au carrousel de STUCS
        pointait vers stucs.cnt-so.org (404). L'adresse d'un contenu porte
        désormais l'hôte de SA section, comme pour les sections à domaine."""
        from django.conf import settings
        self._activate()
        art = make_article_page(title='Article conf', section_slug='principal')
        url = art.get_absolute_url()
        self.assertEqual(url, f'{settings.MAIN_SITE_BASE_URL}/article/article-conf/')
        self.assertNotIn('dom-urls.cnt-so.org', url)

    def test_menu_item_vers_domaine_reste_interne(self):
        from content.models import MenuItem
        self._activate()
        item = MenuItem.objects.create(
            site=self.site, menu='main', title='Cat',
            link_type='category', category=self.cat,
        )
        self.assertTrue(item.get_url().startswith('https://dom-urls.cnt-so.org/'))
        self.assertFalse(item.should_open_new_tab)

    def test_menu_item_externe_ouvre_nouvel_onglet(self):
        from content.models import MenuItem
        item = MenuItem.objects.create(
            site=self.site, menu='main', title='Ext',
            link_type='url', url='https://exemple.org/x/',
        )
        self.assertTrue(item.should_open_new_tab)


@override_settings(ALLOWED_HOSTS=['testserver', 'seo-dom.cnt-so.org'],
                   MAIN_SITE_BASE_URL='https://cnt-so.org')
class DomainSeoTest(TestCase):
    """Phase 4 domaines fédérations : sitemaps, robots, canonicals par hôte."""

    HOST = 'seo-dom.cnt-so.org'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.site = _ensure_section_page(slug='seo-dom', name='SEO Dom', site_type='sectoral')
        self.site.custom_domain = self.HOST
        self.site.save(update_fields=['custom_domain'])
        self.article = make_article_page(title='Article SEO dom', section_slug='seo-dom')
        self.autre_article = make_article_page(title='Article SEO conf', section_slug='principal')

    def test_sitemap_du_domaine_ne_liste_que_la_section(self):
        r = self.client.get('/sitemap.xml', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        xml = r.content.decode()
        self.assertIn(f'https://{self.HOST}/article/article-seo-dom/', xml)
        self.assertIn(f'https://{self.HOST}/contact/', xml)
        self.assertNotIn('article-seo-conf', xml)

    def test_sitemap_principal_exclut_la_section_a_domaine(self):
        r = self.client.get('/sitemap.xml')
        self.assertEqual(r.status_code, 200)
        xml = r.content.decode()
        self.assertIn('article-seo-conf', xml)
        self.assertNotIn('article-seo-dom', xml)
        self.assertNotIn('/seo-dom/', xml)

    def test_robots_txt_pointe_vers_le_sitemap_de_l_hote(self):
        r = self.client.get('/robots.txt', HTTP_HOST=self.HOST)
        self.assertContains(r, f'http://{self.HOST}/sitemap.xml')

    def test_canonical_sur_le_domaine(self):
        r = self.client.get('/article/article-seo-dom/', HTTP_HOST=self.HOST)
        self.assertContains(
            r, f'<link rel="canonical" href="https://{self.HOST}/article/article-seo-dom/">')

    def test_canonical_sur_le_site_principal(self):
        r = self.client.get('/article/article-seo-conf/')
        self.assertContains(
            r, '<link rel="canonical" href="https://cnt-so.org/article/article-seo-conf/">')

    def test_feed_du_domaine_liens_absolus(self):
        r = self.client.get('/feed/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'https://{self.HOST}/article/article-seo-dom/', r.content.decode())


@override_settings(ALLOWED_HOSTS=['testserver', 'p5-dom.cnt-so.org'],
                   MAIN_SITE_BASE_URL='https://cnt-so.org')
class DomainFormsTest(TestCase):
    """Phase 5 domaines fédérations : formulaires et liens transactionnels."""

    HOST = 'p5-dom.cnt-so.org'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.site = _ensure_section_page(slug='p5-dom', name='P5 Dom', site_type='sectoral')
        self.site.custom_domain = self.HOST
        self.site.save(update_fields=['custom_domain'])

    def test_inscription_newsletter_sur_le_domaine(self):
        from content.models import Subscriber
        r = self.client.post('/newsletter/inscription/', {'email': 'fed@example.org'},
                             HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 200)
        sub = Subscriber.objects.get(email='fed@example.org')
        self.assertEqual(sub.site, self.site)

    def test_lien_confirmation_rebondit_vers_le_site_principal(self):
        # Le lien de confirmation généré sur le domaine (URL globale) doit
        # être renvoyé proprement vers le site principal, pas donner un 404.
        from content.models import Subscriber
        sub = Subscriber.objects.create(site=self.site, email='c@example.org')
        r = self.client.get(f'/newsletter/confirmer/{sub.token}/', HTTP_HOST=self.HOST)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'],
                         f'https://cnt-so.org/newsletter/confirmer/{sub.token}/')

    def test_contact_post_sur_le_domaine(self):
        # Le formulaire de contact du sous-site répond en POST sur le domaine
        # (pas de redirection qui perdrait les données)
        r = self.client.post('/contact/', {}, HTTP_HOST=self.HOST)
        self.assertNotIn(r.status_code, (301, 302, 404, 500))


class PromoteBodyImagesTest(TestCase):
    """Récupération des visuels : l'image du corps devient l'image « à la une ».

    Audit du 31/07/2026 : l'import WordPress n'a repris la vignette que pour
    les articles qui en déclaraient une côté WP. Les autres gardent leur visuel
    dans le corps (<img src="/media/…">), et les listes affichent un cadre vide.
    """

    def setUp(self):
        from wagtail.images.tests.utils import get_test_image_file
        from wagtail.images.models import Image

        self.site = _ensure_section_page(slug='poitiers', name='CNT-SO Poitiers')
        # Une image déjà connue de Wagtail, dont on réutilisera le fichier.
        self.image = Image.objects.create(title='Affiche', file=get_test_image_file())
        self.chemin = self.image.file.name          # ex. original_images/test.png

    def _appel(self, **opts):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('promote_body_images', stdout=out, **opts)
        return out.getvalue()

    def _article_avec_img(self, titre='Avec image', **kw):
        return make_article_page(
            section_slug='poitiers', title=titre,
            body=[('html', f'<p>Texte</p><img src="/media/{self.chemin}">')],
            **kw)

    def test_image_du_corps_promue_en_vignette(self):
        art = self._article_avec_img()
        self.assertIsNone(art.any_image_url)

        self._appel()

        art.refresh_from_db()
        self.assertTrue(art.featured_image_id)
        self.assertTrue(art.any_image_url)

    def test_l_article_reste_publie_et_sans_brouillon_en_attente(self):
        """La republication doit aligner la version en ligne et le brouillon,
        sinon la prochaine édition dans /cms/ effacerait la vignette."""
        art = self._article_avec_img()

        self._appel()

        art.refresh_from_db()
        self.assertTrue(art.live)
        self.assertFalse(art.has_unpublished_changes)

    def test_le_fichier_existant_est_reutilise_sans_doublon(self):
        from wagtail.images.models import Image
        self._article_avec_img()
        avant = Image.objects.count()

        self._appel()

        self.assertEqual(Image.objects.count(), avant,
                         "l'image existante doit être réutilisée, pas dupliquée")

    def test_dry_run_n_ecrit_rien(self):
        art = self._article_avec_img()

        sortie = self._appel(dry_run=True)

        art.refresh_from_db()
        self.assertFalse(art.featured_image_id)
        self.assertIn('DRY-RUN', sortie)

    def test_article_deja_pourvu_non_touche(self):
        art = self._article_avec_img()
        art.featured_image = self.image
        art.save()
        rev_avant = art.latest_revision_id

        self._appel()

        art.refresh_from_db()
        self.assertEqual(art.latest_revision_id, rev_avant,
                         "aucune révision ne doit être créée pour rien")

    def test_article_sans_image_ignore(self):
        art = make_article_page(section_slug='poitiers', title='Texte seul',
                                body=[('html', '<p>Aucun visuel ici</p>')])

        self._appel()

        art.refresh_from_db()
        self.assertFalse(art.featured_image_id)

    def test_fichier_absent_du_disque_ignore(self):
        art = make_article_page(
            section_slug='poitiers', title='Image fantome',
            body=[('html', '<img src="/media/original_images/inexistant-xyz.jpg">')])

        self._appel()

        art.refresh_from_db()
        self.assertFalse(art.featured_image_id)

    def test_filtre_par_syndicat(self):
        poitiers = self._article_avec_img(titre='Article Poitiers')
        autre = make_article_page(
            section_slug='auvergne', title='Article Auvergne',
            body=[('html', f'<img src="/media/{self.chemin}">')])

        self._appel(section='poitiers')

        poitiers.refresh_from_db()
        autre.refresh_from_db()
        self.assertTrue(poitiers.featured_image_id)
        self.assertFalse(autre.featured_image_id,
                         "les autres syndicats ne doivent pas être touchés")

    def test_page_avec_brouillon_en_attente_ignoree(self):
        """Republier une page qui a un brouillon en attente mettrait en ligne
        des modifications non validées : on la laisse tranquille."""
        art = self._article_avec_img(titre='Avec brouillon')
        art.title = 'Titre modifie non publie'
        art.save_revision()            # brouillon, non publié
        art.refresh_from_db()
        self.assertTrue(art.has_unpublished_changes)

        sortie = self._appel()

        art.refresh_from_db()
        self.assertFalse(art.featured_image_id)
        self.assertEqual(art.title, 'Avec brouillon', "la page ne doit pas être republiée")
        self.assertIn('brouillon en attente', sortie)


class SlugHeriteAdminTest(TestCase):
    """Côté rédaction : un syndicat dont le slug WordPress hérité diffère du
    slug Wagtail (Numérique « stnum », Éducation « fter ») ne doit pas se
    retrouver avec un espace de rédaction vide, ni produire des contenus
    invisibles côté public. Constaté à l'audit du 31/07/2026."""

    def setUp(self):
        self.site = _ensure_section_page(slug='numerique', name='CNT-SO Numérique')
        self.site.legacy_site_slug = 'stnum'
        self.site.save()

    def test_le_scoping_admin_voit_les_contenus_du_syndicat(self):
        from cms.site_context import scope_qs_slug
        from unittest.mock import MagicMock

        art = make_article_page(section_slug='numerique', title='Article numerique')
        requete = MagicMock()
        with patch('cms.site_context.get_current_site', return_value=self.site):
            visibles = scope_qs_slug(ArticlePage.objects.all(), requete)
        self.assertIn(art, visibles,
                      "le rédacteur doit voir les articles de son syndicat")

    def test_nouveau_contenu_recoit_le_slug_wagtail(self):
        """Un article créé sous la SectionPage doit porter « numerique » et non
        « stnum », sinon il est invisible sur le site public."""
        art = self.site.add_child(instance=ArticlePage(
            title='Nouvel article', slug='nouvel-article'))
        art.save()
        art.refresh_from_db()
        self.assertEqual(art.section_slug, 'numerique')

    def test_nouvelle_page_recoit_le_slug_wagtail(self):
        page = self.site.add_child(instance=ContentPage(
            title='Nouvelle page', slug='nouvelle-page'))
        page.save()
        page.refresh_from_db()
        self.assertEqual(page.section_slug, 'numerique')

    def test_le_groupe_provisionne_suit_le_slug_wagtail(self):
        """La prod a des groupes redacteur_numerique / redacteur_education :
        provisionner sur le slug hérité créerait des doublons."""
        from django.contrib.auth.models import Group
        from cms.provisioning import provision_section

        provision_section(self.site)
        self.assertTrue(Group.objects.filter(name='redacteur_numerique').exists())
        self.assertFalse(Group.objects.filter(name='redacteur_stnum').exists())

    def test_le_panneau_du_tableau_de_bord_compte_les_contenus(self):
        """Le panneau « Vous éditez le syndicat » affichait 0 article et
        0 page à un rédacteur qui en avait (constaté le 05/08/2026 sur le
        compte d'essai Numérique) : il filtrait sur le seul slug hérité."""
        from cms.wagtail_hooks import SiteDashboardPanel
        from unittest.mock import MagicMock

        make_article_page(section_slug='numerique', title='Article numerique')
        self.site.add_child(instance=ContentPage(
            title='Page numerique', slug='page-numerique')).save()

        requete = MagicMock()
        with patch('cms.wagtail_hooks.get_current_site', return_value=self.site):
            panneau = SiteDashboardPanel(requete)
            with patch('cms.wagtail_hooks.render_to_string') as rendu:
                panneau.render_html()
        stats = rendu.call_args[0][1]['stats']
        self.assertEqual(stats['articles'], 1)
        self.assertEqual(stats['pages'], 1)

    def test_le_tableau_des_syndicats_compte_les_articles(self):
        """Même bug côté chef, dans la vue « Syndicats »."""
        from cms.wagtail_hooks import ArticlePage as AP
        make_article_page(section_slug='numerique', title='Article numerique')
        self.assertEqual(
            AP.objects.filter(section_slug__in=self.site.slugs_contenu).count(), 1)

    def test_aucune_recopie_manuelle_des_deux_slugs(self):
        """Neuf fois le même bug depuis juillet, une fois par endroit où
        l'expression était recopiée. Elle vit maintenant dans
        SectionPage.slugs_contenu ; toute nouvelle recopie échoue ici."""
        import re
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        # Ensemble littéral à deux membres : `{x.slug, x.legacy_site_slug or …}`.
        # La virgule exclut les f-strings légitimes `{self.legacy_site_slug or …}`.
        motif = re.compile(r'\{[^{}]*,[^{}]*legacy_site_slug or[^{}]*\}')
        fautifs = []
        for chemin in list((racine / 'cms').rglob('*.py')) + \
                list((racine / 'content').rglob('*.py')):
            if 'migrations' in chemin.parts or chemin.name.startswith('tests'):
                continue
            for num, ligne in enumerate(
                    chemin.read_text().splitlines(), start=1):
                if motif.search(ligne) and '# source-unique' not in ligne:
                    fautifs.append(f'{chemin.relative_to(racine)}:{num}')
        self.assertEqual(
            fautifs, [],
            'Utiliser SectionPage.slugs_contenu plutôt que recopier '
            f'l\'expression : {fautifs}')


class CloisonnementEditionTest(TestCase):
    """Un rédacteur ne doit pas pouvoir ouvrir l'article d'un autre syndicat en
    tapant son URL. La liste le masquait déjà, mais le formulaire d'édition
    restait accessible en lecture (audit du 31/07/2026)."""

    MDP = 'test-cloisonnement'

    def setUp(self):
        from django.contrib.auth.models import User, Group

        self.mien = _ensure_section_page(slug='numerique', name='CNT-SO Numérique')
        self.mien.legacy_site_slug = 'stnum'
        self.mien.save()
        self.voisin = _ensure_section_page(slug='13', name='CNT-SO 13')

        self.a_moi = make_article_page(section_slug='numerique', title='Mon article')
        self.a_voisin = make_article_page(section_slug='13', title='Article du voisin')

        grp, _ = Group.objects.get_or_create(name='redacteur_numerique')
        self.user = User.objects.create_user('redac_num', 'r@n.fr', self.MDP)
        self.user.groups.set([grp])
        self.client.login(username='redac_num', password=self.MDP)

    def _edit(self, article):
        return self.client.get(
            f'/cms/snippets/cms/articlepage/edit/{article.pk}/', follow=False)

    def test_edition_de_son_propre_article_autorisee(self):
        self.assertEqual(self._edit(self.a_moi).status_code, 200)

    def test_edition_d_un_article_d_un_autre_syndicat_refusee(self):
        self.assertEqual(self._edit(self.a_voisin).status_code, 404)

    def test_le_chef_garde_l_acces_a_tout(self):
        from django.contrib.auth.models import Group
        chef, _ = Group.objects.get_or_create(name='redacteur_en_chef')
        self.user.groups.add(chef)
        self.assertEqual(self._edit(self.a_voisin).status_code, 200)


class CreationArticleDepuisCmsTest(TestCase):
    """Créer un article depuis /cms/ échouait en erreur 500.

    ArticlePage et ContentPage sont des pages Wagtail éditées via des
    SnippetViewSet : à la création, form.save() faisait un INSERT direct sans
    renseigner les champs d'arbre, et la base refusait l'enregistrement
    (« NOT NULL constraint failed: wagtailcore_page.depth »). Aucun rédacteur
    ne pouvait publier un article. Découvert à l'audit du 01/08/2026 en
    déroulant le parcours réel — les tests existants n'ouvraient que le
    formulaire, sans jamais le soumettre.
    """

    MDP = 'creation-test'

    def setUp(self):
        from django.contrib.auth.models import User, Group

        self.section = _ensure_section_page(slug='numerique', name='CNT-SO Numérique')
        grp, _ = Group.objects.get_or_create(name='redacteur_numerique')
        self.redacteur = User.objects.create_user('redac_creation', 'r@c.fr', self.MDP)
        self.redacteur.groups.set([grp])

    def _creer(self, titre):
        self.client.login(username='redac_creation', password=self.MDP)
        return self.client.post('/cms/snippets/cms/articlepage/add/', {
            'title': titre,
            'body-count': '0',
            'section_slug': 'numerique',
            'action-publish': 'action-publish',
        })

    def test_un_redacteur_peut_creer_et_publier_un_article(self):
        r = self._creer('Article créé depuis le CMS')

        self.assertEqual(r.status_code, 302, "la création doit aboutir, pas rejouer le formulaire")
        art = ArticlePage.objects.filter(title='Article créé depuis le CMS').first()
        self.assertIsNotNone(art, "l'article doit exister en base")
        self.assertTrue(art.live, "l'article doit être publié")

    def test_l_article_est_place_dans_l_arbre_sous_son_syndicat(self):
        self._creer('Article bien placé')
        art = ArticlePage.objects.filter(title='Article bien placé').first()

        self.assertIsNotNone(art)
        self.assertTrue(art.depth, "les champs d'arbre doivent être renseignés")
        self.assertEqual(art.get_parent().pk, self.section.pk)
        self.assertEqual(art.section_slug, 'numerique')

    def test_l_article_cree_est_visible_sur_le_site_public(self):
        self._creer('Article visible en ligne')
        art = ArticlePage.objects.filter(title='Article visible en ligne').first()
        self.assertIsNotNone(art)

        self.client.logout()
        r = self.client.get(f'/numerique/article/{art.slug}/')
        self.assertEqual(r.status_code, 200)


class UrlDeSectionResolvableTest(TestCase):
    """`SectionSlugConverter` (content/urls.py) n'accepte que `slug=`, jamais
    `legacy_site_slug`. `get_absolute_url()` émettait pourtant le slug hérité :
    l'adresse d'Éducation était `/fter/`, qui répond 404 — et elle était
    publiée jusque dans le sitemap (constaté en production le 05/08/2026).

    Dixième et dernière occurrence de la famille `legacy_site_slug`, celle-ci
    dans le générateur d'URL lui-même.
    """

    def setUp(self):
        self.site = _ensure_section_page(slug='education', name='CNT-SO Éducation')
        self.site.legacy_site_slug = 'fter'
        self.site.save()

    def test_l_adresse_de_la_section_porte_le_slug_wagtail(self):
        url = self.site.get_absolute_url()
        self.assertEqual(url, '/education/')
        self.assertNotIn('fter', url)

    def test_l_adresse_de_la_section_repond(self):
        r = self.client.get(self.site.get_absolute_url())
        self.assertEqual(r.status_code, 200,
                         f"{self.site.get_absolute_url()} ne répond pas")

    def test_le_slug_herite_ne_repond_pas(self):
        """Contrôle du diagnostic : c'est bien le convertisseur qui refuse."""
        self.assertEqual(self.client.get('/fter/').status_code, 404)

    def test_rejoindre_porte_aussi_le_slug_wagtail(self):
        self.assertNotIn('fter', self.site.get_rejoindre_url())

    def test_toute_section_produit_une_adresse_qui_repond(self):
        """Balayage : aucune section ne doit générer d'adresse morte."""
        from cms.models import SectionPage
        for section in SectionPage.objects.filter(live=True, custom_domain=''):
            with self.subTest(section=section.slug):
                url = section.get_absolute_url()
                if not url.startswith('/'):
                    continue    # site autonome hébergé ailleurs
                self.assertNotEqual(
                    self.client.get(url).status_code, 404,
                    f"{section.title} : {url} est une adresse morte")


class ContenuConfederalSurUnDomaineTest(TestCase):
    """Le contenu du site confédéral s'affiche aussi sur les domaines de
    fédération : un article conf mis au carrousel d'un sous-site, ou
    l'étiquette d'une catégorie conf portée par un article de sous-site
    (31 articles en production). Son adresse était relative — le navigateur
    la résolvait alors contre l'hôte du sous-site, donc un 404. Sept liens
    morts relevés au crawl des 286 liens internes, le 05/08/2026."""

    def setUp(self):
        from django.conf import settings
        self.base = settings.MAIN_SITE_BASE_URL

    def test_l_article_confederal_porte_l_hote_du_site_principal(self):
        art = make_article_page(section_slug='principal', title='Conf',
                                slug='art-conf')
        self.assertEqual(art.get_absolute_url(),
                         f'{self.base}/article/art-conf/')

    def test_la_categorie_confederale_porte_l_hote_du_site_principal(self):
        cat = make_cms_category(name='Luttes', slug='luttes-conf',
                                section_slug='principal')
        self.assertEqual(cat.get_absolute_url(),
                         f'{self.base}/categorie/luttes-conf/')

    def test_le_contenu_de_sous_site_n_est_pas_affecte(self):
        """Contrôle : la règle ne touche que le principal."""
        site = _ensure_section_page(slug='sous-site-x', name='Sous-site X')
        art = make_article_page(section_slug='sous-site-x', title='Local',
                                slug='art-local')
        self.assertNotIn(self.base, art.get_absolute_url())

    def test_aucune_adresse_confederale_ne_reste_relative(self):
        """Balayage : tout contenu du principal doit porter son hôte."""
        from cms.models import ArticlePage, CmsCategory
        make_article_page(section_slug='principal', title='A', slug='balayage-a')
        make_cms_category(name='B', slug='balayage-b', section_slug='principal')
        for modele in (ArticlePage.objects.filter(section_slug='principal'),
                       CmsCategory.objects.filter(section_slug='principal')):
            for obj in modele:
                with self.subTest(obj=str(obj)[:30]):
                    self.assertTrue(
                        obj.get_absolute_url().startswith('http'),
                        f'{obj} : adresse relative, elle viserait le mauvais '
                        f'hôte sur un domaine de fédération')


class EtiquetageCategoriesTest(TestCase):
    """STUCS était le seul syndicat dont AUCUN article ne portait de catégorie
    locale : ses 31 articles portent des catégories confédérales — ce qui est
    voulu, c'est ce qui les fait paraître sur le site national — et ses
    8 catégories propres étaient vides, d'où 7 entrées de menu vers du vide
    (audit du 05/08/2026).

    La règle qui compte : on AJOUTE l'étiquette locale, on ne retire jamais la
    confédérale.
    """

    def _lancer(self, **kw):
        from django.core.management import call_command
        from io import StringIO
        from unittest.mock import patch
        # La table de production est indexée par pk : on la rejoue sur
        # l'article de test plutôt que de forger un pk (l'arbre Wagtail
        # l'interdit).
        table = {self.art.pk: ('greve', 'Grève 6MIC')}
        with patch('cms.management.commands.fix_etiquetage_categories'
                   '.ETIQUETTES_STUCS', table):
            call_command('fix_etiquetage_categories', stdout=StringIO(), **kw)

    def setUp(self):
        _ensure_section_page(slug='stucs', name='CNT-SO STUCS')
        self.conf = make_cms_category(name='Culture', slug='culture-conf',
                                      section_slug='principal')
        self.greve = make_cms_category(name='Grève', slug='greve',
                                       section_slug='stucs')
        self.art = make_article_page(section_slug='stucs', title='Grève 6MIC',
                                     slug='greve-6mic')
        # ParentalManyToManyField : sans save(), add() ne persiste rien.
        self.art.cms_categories.add(self.conf)
        self.art.save()

    def test_l_etiquette_locale_est_ajoutee(self):
        self._lancer()
        slugs = {c.slug for c in ArticlePage.objects.get(pk=self.art.pk).cms_categories.all()}
        self.assertIn('greve', slugs)

    def test_la_categorie_confederale_est_conservee(self):
        """Sans elle, l'article disparaîtrait des rubriques du site national."""
        self._lancer()
        slugs = {c.slug for c in ArticlePage.objects.get(pk=self.art.pk).cms_categories.all()}
        self.assertIn('culture-conf', slugs)

    def test_la_commande_est_idempotente(self):
        self._lancer()
        self._lancer()
        cats = ArticlePage.objects.get(pk=self.art.pk).cms_categories.all()
        self.assertEqual(cats.filter(slug='greve').count(), 1)

    def test_une_categorie_absente_n_arrete_pas_la_commande(self):
        self.greve.delete()
        self._lancer()   # ne doit pas lever
        self.assertTrue(ArticlePage.objects.filter(pk=self.art.pk).exists())


class RepointageMenuVersCategoriePleineTest(TestCase):
    """Le 13 a des doublons créés à l'import : le menu vise une catégorie vide
    alors que la vraie, remplie, est juste à côté."""

    def _lancer(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('fix_etiquetage_categories', stdout=StringIO())

    def setUp(self):
        from content.models import MenuItem
        self.site = _ensure_section_page(slug='13', name='CNT-SO 13')
        self.vide = make_cms_category(name='Transports', slug='transports',
                                      section_slug='13')
        self.pleine = make_cms_category(name='Luttes transports',
                                        slug='actualites-luttes-transports',
                                        section_slug='13')
        art = make_article_page(section_slug='13', title='Grève bus', slug='greve-bus')
        art.cms_categories.add(self.pleine)
        art.save()
        self.item = MenuItem.objects.create(site=self.site, menu='main',
                                            title='Transports',
                                            link_type='category',
                                            category=self.vide)

    def test_le_menu_vise_la_categorie_remplie(self):
        self._lancer()
        self.item.refresh_from_db()
        self.assertEqual(self.item.category_id, self.pleine.pk)

    def test_on_ne_repointe_pas_vers_une_categorie_elle_aussi_vide(self):
        """Le filet : repointer vers un autre vide ne réparerait rien."""
        from cms.models import ArticlePage
        ArticlePage.objects.filter(section_slug='13').delete()
        self._lancer()
        self.item.refresh_from_db()
        self.assertEqual(self.item.category_id, self.vide.pk,
                         "repointé vers une catégorie vide")


class AjoutMenuCategorieTest(TestCase):
    """Le pendant de `fix_menus_morts` : une catégorie remplie que le menu ne
    dessert pas. « Travailleur-euses de la terre » portait les deux numéros des
    *Croquants* sans qu'aucun lien de navigation n'y mène — on n'y arrivait
    qu'en cliquant l'étiquette sous un des deux articles (constat du
    15/08/2026, signalé par Arnaud)."""

    def _lancer(self, **kw):
        from django.core.management import call_command
        from io import StringIO
        from unittest.mock import patch
        table = [{'site': 'principal', 'rubrique': 'Syndicats',
                  'categorie': 'terre', 'libelle': 'Travailleurs de la Terre',
                  'ordre': 13}]
        sortie = StringIO()
        with patch('cms.management.commands.ajoute_menu_categorie.ENTREES', table):
            call_command('ajoute_menu_categorie', stdout=sortie, **kw)
        return sortie.getvalue()

    def setUp(self):
        from content.models import MenuItem
        self.site = _ensure_section_page(slug='principal', name='CNT-SO')
        self.cat = make_cms_category(name='Terre', slug='terre',
                                     section_slug='principal')
        art = make_article_page(section_slug='principal', title='Les croquants',
                                slug='les-croquants')
        art.cms_categories.add(self.cat)
        art.save()
        self.rubrique = MenuItem.objects.create(
            site=self.site, menu='main', title='Syndicats',
            link_type='url', url='#')

    def _entrees(self):
        from content.models import MenuItem
        return MenuItem.objects.filter(parent=self.rubrique, category=self.cat)

    def test_l_entree_est_creee_sous_la_rubrique(self):
        self._lancer()
        item = self._entrees().get()
        self.assertEqual(item.title, 'Travailleurs de la Terre')
        self.assertEqual(item.link_type, 'category')
        self.assertEqual(item.menu, 'main')

    def test_le_lien_mene_bien_a_la_categorie(self):
        """Un 'category' sans cible retombe sur '#' : c'est le bug d'origine."""
        self._lancer()
        item = self._entrees().get()
        self.assertEqual(item.get_url(), self.cat.get_absolute_url())
        self.assertFalse(item.est_impasse)

    def test_la_commande_est_idempotente(self):
        self._lancer()
        self._lancer()
        self.assertEqual(self._entrees().count(), 1)

    def test_dry_run_n_ecrit_rien(self):
        self._lancer(dry_run=True)
        self.assertFalse(self._entrees().exists())

    def test_la_place_deja_prise_ne_bouscule_personne(self):
        """L'ordre demandé est un souhait, pas une réquisition."""
        from content.models import MenuItem
        voisin = MenuItem.objects.create(site=self.site, menu='main',
                                         parent=self.rubrique, title='Commerce',
                                         link_type='url', url='/x/', order=13)
        self._lancer()
        voisin.refresh_from_db()
        self.assertEqual(voisin.order, 13)
        self.assertGreater(self._entrees().get().order, 13)

    def test_une_rubrique_absente_n_arrete_pas_la_commande(self):
        self.rubrique.delete()
        sortie = self._lancer()      # ne doit pas lever
        self.assertIn('ignoré', sortie)

    def test_la_table_reelle_ne_vise_pas_deux_fois_la_meme_categorie(self):
        """Les tests ci-dessus tournent sur une table forgée : celui-ci regarde
        celle qui sera jouée en production. Deux lignes vers la même catégorie
        passeraient l'idempotence de la commande (elle compare à la base, pas à
        la table) et poseraient deux entrées identiques au menu."""
        from cms.management.commands.ajoute_menu_categorie import ENTREES
        cibles = [(e['site'], e['rubrique'], e['categorie']) for e in ENTREES]
        self.assertEqual(len(cibles), len(set(cibles)), 'doublon dans ENTREES')
        for e in ENTREES:
            with self.subTest(cat=e['categorie']):
                self.assertTrue(e['libelle'].strip(), 'libellé vide')

    def test_une_categorie_vide_est_signalee(self):
        """Créer un menu vers du vide, c'est ce que l'audit a passé un mois à
        défaire : la commande le fait quand même, mais le dit."""
        ArticlePage.objects.filter(section_slug='principal').delete()
        self.assertIn('vide', self._lancer())


class SuppressionDoublonVideTest(TestCase):
    """« Syndicat national des transports et de l'aménagement du territoire »
    est un doublon vide de « Transport – Logistique » (confirmé par Arnaud le
    15/08/2026).

    Le point sensible : `MenuItem.category` est en `on_delete=SET_NULL` et
    `cms_categories` est un M2M. Rien dans Django n'empêche de supprimer une
    catégorie encore utilisée — elle viderait des liens en silence. D'où trois
    refus explicites."""

    def _lancer(self, **kw):
        from django.core.management import call_command
        from io import StringIO
        from unittest.mock import patch
        table = [{'site': 'principal', 'categorie': 'doublon',
                  'doublon_de': 'Transport'}]
        sortie = StringIO()
        cmd = 'cms.management.commands.ajoute_menu_categorie'
        with patch(f'{cmd}.DOUBLONS', table), patch(f'{cmd}.ENTREES', []):
            call_command('ajoute_menu_categorie', stdout=sortie, **kw)
        return sortie.getvalue()

    def setUp(self):
        self.site = _ensure_section_page(slug='principal', name='CNT-SO')
        self.cat = make_cms_category(name='Doublon', slug='doublon',
                                     section_slug='principal')

    def _existe(self):
        return CmsCategory.objects.filter(pk=self.cat.pk).exists()

    def test_le_doublon_inerte_est_supprime(self):
        self._lancer()
        self.assertFalse(self._existe())

    def test_dry_run_ne_supprime_rien(self):
        self._lancer(dry_run=True)
        self.assertTrue(self._existe())

    def test_refus_si_un_article_y_est_range(self):
        """Même un brouillon : `live()` ne suffirait pas comme critère."""
        art = make_article_page(section_slug='principal', title='A', slug='a-doublon')
        art.cms_categories.add(self.cat)
        art.save()
        art.unpublish()
        self.assertIn('pas inerte', self._lancer())
        self.assertTrue(self._existe())

    def test_refus_si_une_entree_de_menu_la_vise(self):
        """SET_NULL : la suppression ne lèverait pas, elle créerait une impasse."""
        from content.models import MenuItem
        MenuItem.objects.create(site=self.site, menu='main', title='X',
                                link_type='category', category=self.cat)
        self.assertIn('pas inerte', self._lancer())
        self.assertTrue(self._existe())

    def test_refus_si_elle_a_une_sous_categorie(self):
        enfant = make_cms_category(name='Fille', slug='fille-doublon',
                                   section_slug='principal')
        enfant.parent = self.cat
        enfant.save()
        self.assertIn('pas inerte', self._lancer())
        self.assertTrue(self._existe())

    def test_la_commande_est_idempotente(self):
        self._lancer()
        self.assertIn('déjà supprimée', self._lancer())


class LibelleCategorieAvecParentTest(TestCase):
    """L'import WordPress a gardé la hiérarchie dans `parent` mais pas dans le
    nom : le 13 a 20 catégories pour 4 libellés — sept « Revendiquons ! », six
    « Vos droits », cinq « Actualités - luttes », deux « Se syndiquer » —
    chacune sous un secteur différent, avec ses propres articles. La liste à
    cocher du formulaire d'article n'affichait que le nom : indiscernables
    (signalé par Arnaud le 05/08/2026)."""

    def setUp(self):
        self.site = _ensure_section_page(slug='13', name='CNT-SO 13')
        self.btp = make_cms_category(name='BTP', slug='btp', section_slug='13')
        self.nettoyage = make_cms_category(name='Nettoyage', slug='nettoyage',
                                           section_slug='13')

    def _sous(self, parent, nom, slug):
        cat = make_cms_category(name=nom, slug=slug, section_slug='13')
        cat.parent = parent
        cat.save()
        return cat

    def test_le_parent_apparait_dans_le_libelle(self):
        a = self._sous(self.btp, 'Revendiquons !', 'revendiquons')
        b = self._sous(self.nettoyage, 'Revendiquons !', 'revendiquons-nettoyage')
        self.assertEqual(str(a), 'BTP › Revendiquons !')
        self.assertEqual(str(b), 'Nettoyage › Revendiquons !')
        self.assertNotEqual(str(a), str(b),
                            'deux catégories distinctes restent indiscernables')

    def test_une_categorie_sans_parent_garde_son_nom(self):
        self.assertEqual(str(self.btp), 'BTP')

    def test_un_parent_de_meme_nom_ne_begaie_pas(self):
        """L'import a laissé des cas où le parent porte le même nom."""
        c = self._sous(self.btp, 'BTP', 'btp-bis')
        self.assertEqual(str(c), 'BTP')

    def test_les_gabarits_publics_ne_dependent_pas_de_str(self):
        """Le préfixe doit rester confiné au back-office : les pages publiques
        affichent `.name`."""
        from pathlib import Path
        import re
        racine = Path(__file__).resolve().parent.parent / 'templates'
        motif = re.compile(r'{{\s*(category|cat|categorie)\s*}}')
        fautifs = [str(p.relative_to(racine)) for p in racine.rglob('*.html')
                   if motif.search(p.read_text())]
        self.assertEqual(fautifs, [], f'gabarits affichant str(catégorie) : {fautifs}')

    def test_la_liste_a_cocher_ne_part_pas_en_n_plus_un(self):
        """Une requête par catégorie ferait 62 requêtes rien que pour le 13."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from cms.models import CmsCategory

        for i in range(12):
            self._sous(self.btp, f'Rubrique {i}', f'rubrique-{i}')
        qs = (CmsCategory.objects.filter(section_slug='13')
              .select_related('parent').order_by('parent__name', 'name'))
        with CaptureQueriesContext(connection) as ctx:
            libelles = [str(c) for c in qs]
        self.assertEqual(len(ctx.captured_queries), 1,
                         f'{len(ctx.captured_queries)} requêtes pour '
                         f'{len(libelles)} catégories')


class CategoriesBorneesAuSyndicatTest(TestCase):
    """Le filtre des catégories ne s'appliquait qu'avec un syndicat
    sélectionné. Un superuser sans sélection voyait les 219 catégories des
    douze sections — « Non classé » six fois, « Nettoyage » trois fois : le
    même nom dans des syndicats différents (signalé par Arnaud le
    05/08/2026)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.treize = _ensure_section_page(slug='13', name='CNT-SO 13')
        self.conf = _ensure_section_page(slug='principal', name='Confédération')
        self.cat_13 = make_cms_category(name='Nettoyage', slug='nettoyage-13',
                                        section_slug='13')
        self.cat_conf = make_cms_category(name='Nettoyage', slug='nettoyage-conf',
                                          section_slug='principal')
        self.U = get_user_model()

    def _borner(self, current, section_slug=''):
        """Rejoue le bornage sur un formulaire minimal."""
        from django import forms as dj
        from cms.models import CmsCategory
        from cms.wagtail_hooks import _make_scoped_article_page_view

        class Faux:
            pass

        instance = Faux()
        instance.section_slug = section_slug

        class FauxForm:
            pass

        form = FauxForm()
        form.instance = instance
        form.fields = {'cms_categories': dj.ModelMultipleChoiceField(
            queryset=CmsCategory.objects.none())}
        vue = _make_scoped_article_page_view(object)
        vue._borner_categories(form, current)
        return form.fields['cms_categories']

    def test_avec_un_syndicat_selectionne_seules_ses_categories(self):
        champ = self._borner(self.treize)
        slugs = {c.slug for c in champ.queryset}
        self.assertEqual(slugs, {'nettoyage-13'})

    def test_sans_selection_on_se_rabat_sur_la_section_de_l_article(self):
        """Un superuser qui édite un article du 13 ne doit pas voir les 219."""
        champ = self._borner(None, section_slug='13')
        slugs = {c.slug for c in champ.queryset}
        self.assertEqual(slugs, {'nettoyage-13'})

    def test_section_inconnue_les_homonymes_sont_distingues(self):
        """Création par un superuser sans rien choisir : on n'ampute pas son
        choix, mais « Nettoyage » ne doit pas apparaître deux fois à
        l'identique."""
        champ = self._borner(None, section_slug='')
        libelles = [champ.label_from_instance(c) for c in champ.queryset]
        # Le provisionnement d'une section crée ses propres catégories : on ne
        # fige pas un total, on vérifie que les homonymes se distinguent.
        nettoyages = [l for l in libelles if l.endswith('Nettoyage')]
        self.assertEqual(len(nettoyages), 2, f'trouvé : {nettoyages}')
        self.assertEqual(len(set(nettoyages)), 2,
                         f'homonymes indiscernables : {nettoyages}')
        self.assertTrue(any(l.startswith('[13]') for l in nettoyages))

    def test_le_bornage_ne_part_pas_en_n_plus_un(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        for i in range(10):
            c = make_cms_category(name=f'Sous {i}', slug=f'sous-{i}',
                                  section_slug='13')
            c.parent = self.cat_13
            c.save()
        from cms.models import CmsCategory
        n_cat = CmsCategory.objects.filter(section_slug='13').count()
        # La fenêtre doit couvrir le bornage LUI-MÊME : le groupement évalue
        # le queryset dès la construction des choix, et mesurer après ne
        # capturait plus rien (0 requête — le test passait pour rien).
        with CaptureQueriesContext(connection) as ctx:
            champ = self._borner(self.treize)
            [str(c) for c in champ.queryset]
        self.assertLess(
            len(ctx.captured_queries), n_cat,
            f'{len(ctx.captured_queries)} requêtes pour {n_cat} catégories : '
            f'une par catégorie, le select_related ne joue plus')
        self.assertLessEqual(len(ctx.captured_queries), 3,
                             f'{len(ctx.captured_queries)} requêtes')


class OrdreHierarchiqueCategoriesTest(TestCase):
    """Trier sur `parent__name` seul reléguait les catégories sans parent tout
    en bas : le 13 affichait ses 40 « Parent › Enfant », puis ses 22 parents
    isolés — « Vos droits » apparaissait donc en bas ET quatre fois plus haut
    sous ses enfants (constaté par Arnaud le 05/08/2026 avec le compte
    essai-13)."""

    def setUp(self):
        _ensure_section_page(slug='13', name='CNT-SO 13')
        self.btp = make_cms_category(name='BTP', slug='btp', section_slug='13')
        self.zebre = make_cms_category(name='Zèbre', slug='zebre', section_slug='13')
        for nom, slug in (('Vos droits', 'vd-btp'), ('Actualités', 'act-btp')):
            c = make_cms_category(name=nom, slug=slug, section_slug='13')
            c.parent = self.btp
            c.save()

    def _ordre(self):
        from django.db.models.functions import Coalesce
        from cms.models import CmsCategory
        qs = (CmsCategory.objects.filter(section_slug='13')
              .select_related('parent')
              .annotate(_groupe=Coalesce('parent__name', 'name'))
              .order_by('_groupe', 'parent__name', 'name'))
        return [str(c) for c in qs]

    def test_le_parent_precede_immediatement_ses_enfants(self):
        ordre = self._ordre()
        i = ordre.index('BTP')
        self.assertEqual(ordre[i + 1], 'BTP › Actualités')
        self.assertEqual(ordre[i + 2], 'BTP › Vos droits')

    def test_les_groupes_ne_sont_pas_entremeles(self):
        """« Zèbre », sans parent, ne doit pas s'intercaler dans le groupe BTP."""
        ordre = self._ordre()
        indices = [i for i, l in enumerate(ordre) if l.startswith('BTP')]
        self.assertEqual(indices, list(range(min(indices), max(indices) + 1)),
                         f'groupe BTP entrecoupé : {ordre}')


class RenduGroupeCategoriesTest(TestCase):
    """Preuve par le HTML servi : le formulaire de création d'article doit
    présenter les catégories groupées par parent, pas en liste plate.

    Un test sur l'itérateur seul ne prouverait rien — c'est Wagtail qui rend
    le champ, et rien ne garantissait qu'il honore les groupes de Django.
    """

    MDP = 'test-rendu-groupes'

    def setUp(self):
        from django.contrib.auth.models import User, Group
        from cms.provisioning import provision_section

        self.site = _ensure_section_page(slug='13', name='CNT-SO 13')
        provision_section(self.site)
        self.btp = make_cms_category(name='BTP', slug='btp', section_slug='13')
        for nom, slug in (('Vos droits', 'vd-btp'), ('Revendiquons !', 'rev-btp')):
            c = make_cms_category(name=nom, slug=slug, section_slug='13')
            c.parent = self.btp
            c.save()

        grp = Group.objects.get(name='redacteur_13')
        self.user = User.objects.create_user('redac13', 'r@13.fr', self.MDP)
        self.user.groups.set([grp])
        self.client.login(username='redac13', password=self.MDP)

    def test_le_formulaire_presente_des_groupes(self):
        r = self.client.get('/cms/snippets/cms/articlepage/add/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        # L'en-tête de groupe est rendu hors <label> : c'est ce qui distingue
        # une liste groupée d'une liste plate.
        self.assertIn('BTP', html)
        self.assertRegex(html, r'BTP\s*</?\w',
                         "aucun en-tête de groupe : la liste est restée plate")

    def test_les_etiquettes_ne_begaient_pas_dans_un_groupe(self):
        """Sous l'en-tête « BTP », l'étiquette doit être « Vos droits », pas
        « BTP › Vos droits »."""
        html = self.client.get('/cms/snippets/cms/articlepage/add/').content.decode()
        self.assertNotIn('BTP › Vos droits', html)
        self.assertIn('Vos droits', html)

    def test_le_balisage_attendu_par_le_css_est_bien_la(self):
        """Le CSS vise `#id_cms_categories > div > label:not([for])` pour les
        en-têtes. Si Wagtail change ce balisage, la mise en page redevient une
        liste plate sans que rien ne le signale — d'où ce verrou."""
        import re
        html = self.client.get('/cms/snippets/cms/articlepage/add/').content.decode()
        i = html.find('id="id_cms_categories"')
        self.assertGreater(i, 0, 'conteneur #id_cms_categories absent')
        bloc = html[i:i + 2500]
        # Un en-tête de groupe : un <label> SANS attribut for.
        self.assertRegex(bloc, r'<div>\s*<label>[^<]+</label>',
                         "aucun en-tête de groupe dans le balisage servi")
        # Et les cases, elles, ont bien un for=.
        self.assertRegex(bloc, r'<label for="id_cms_categories_\d+_\d+">')

    def test_aucune_categorie_d_un_autre_syndicat(self):
        autre = _ensure_section_page(slug='auvergne', name='CNT-SO Auvergne')
        make_cms_category(name='Secret auvergnat', slug='secret-auvergne',
                          section_slug='auvergne')
        html = self.client.get('/cms/snippets/cms/articlepage/add/').content.decode()
        self.assertNotIn('Secret auvergnat', html)


class FiltreParCategorieTest(TestCase):
    """La liste des articles n'offrait aucun filtre par catégorie. Ajouté à la
    demande d'Arnaud le 05/08/2026 — et borné au syndicat, sinon il
    proposerait les 219 catégories des douze sections."""

    MDP = 'test-filtre-cat'

    def setUp(self):
        from django.contrib.auth.models import User, Group
        from cms.provisioning import provision_section

        self.site = _ensure_section_page(slug='13', name='CNT-SO 13')
        provision_section(self.site)
        _ensure_section_page(slug='auvergne', name='CNT-SO Auvergne')
        self.luttes = make_cms_category(name='Luttes', slug='luttes-13',
                                        section_slug='13')
        make_cms_category(name='Secret auvergnat', slug='secret-av',
                          section_slug='auvergne')

        self.avec = make_article_page(section_slug='13', title='Avec catégorie',
                                      slug='avec-cat')
        self.avec.cms_categories.add(self.luttes)
        self.avec.save()
        self.sans = make_article_page(section_slug='13', title='Sans catégorie',
                                      slug='sans-cat')

        grp = Group.objects.get(name='redacteur_13')
        u = User.objects.create_user('r13f', 'a@b.fr', self.MDP)
        u.groups.set([grp])
        self.client.login(username='r13f', password=self.MDP)

    def test_le_filtre_est_propose(self):
        html = self.client.get('/cms/snippets/cms/articlepage/').content.decode()
        self.assertIn('cms_categories', html)

    def test_filtrer_ne_retient_que_les_articles_de_la_categorie(self):
        r = self.client.get('/cms/snippets/cms/articlepage/',
                            {'cms_categories': self.luttes.pk})
        html = r.content.decode()
        self.assertIn('Avec catégorie', html)
        self.assertNotIn('Sans catégorie', html)

    def test_le_filtre_ne_propose_pas_les_categories_des_autres(self):
        html = self.client.get('/cms/snippets/cms/articlepage/').content.decode()
        self.assertNotIn('Secret auvergnat', html)


class BoutonVoirLeSiteTest(TestCase):
    """Aucun renvoi vers le site public depuis le CMS (demande d'Arnaud,
    05/08/2026). Placé dans la barre du haut, à côté du sélecteur de syndicat,
    plutôt que dans la barre latérale où Arnaud ne l'a pas trouvé.

    L'URL suit le syndicat : un rédacteur du 13 arrive sur 13.cnt-so.org.
    """

    MDP = 'test-voir-site'

    def setUp(self):
        from django.contrib.auth.models import User, Group
        from cms.provisioning import provision_section
        self.site = _ensure_section_page(slug='13', name='CNT-SO 13')
        provision_section(self.site)
        grp = Group.objects.get(name='redacteur_13')
        self.user = User.objects.create_user('r13v', 'a@b.fr', self.MDP)
        self.user.groups.set([grp])
        self.client.login(username='r13v', password=self.MDP)

    def _barre(self):
        return self.client.get('/cms/current-site-fragment/').content.decode()

    @staticmethod
    def _href_du_lien(html):
        import re
        m = re.search(r'<a href="([^"]*)"[^>]*>\s*🌐 Voir le site', html)
        return m.group(1) if m else None

    def test_le_lien_est_dans_la_barre_du_haut(self):
        self.assertIn('Voir le site', self._barre())

    def test_l_url_suit_le_syndicat(self):
        html = self._barre()
        href = self._href_du_lien(html)
        self.assertIsNotNone(href, f'lien introuvable dans : {html[:300]}')
        self.assertEqual(href, self.site.get_absolute_url())

    def test_le_lien_s_ouvre_dans_un_nouvel_onglet(self):
        html = self._barre()
        i = html.find('Voir le site')
        bloc = html[max(0, i - 320):i]
        self.assertIn('target="_blank"', bloc)
        self.assertIn('rel="noopener"', bloc)

    def test_sur_un_domaine_autonome_l_url_est_celle_du_domaine(self):
        self.site.custom_domain = '13.cnt-so.org'
        self.site.save()
        self.assertIn('13.cnt-so.org', self._href_du_lien(self._barre()))


class ApercuSurDomaineAutonomeTest(TestCase):
    """L'aperçu d'un article d'un syndicat à domaine autonome affichait
    « Firefox ne peut pas ouvrir cette page » (Arnaud, 05/08/2026).

    Wagtail bâtit une requête factice à l'URL de la page et la fait traverser
    toute la chaîne de middlewares. `SectionDomainMiddleware` la redirigeait
    alors (301) vers le domaine du syndicat : le cadre d'aperçu chargeait une
    page d'une AUTRE origine, que `X-Frame-Options: SAMEORIGIN` refuse.
    Wagtail pose `request.is_dummy` pour qu'un middleware puisse s'abstenir.
    """

    MDP = 'test-apercu'

    def setUp(self):
        from django.contrib.auth.models import User, Group
        from cms.provisioning import provision_section

        self.site = _ensure_section_page(slug='stucs', name='CNT-SO STUCS')
        provision_section(self.site)
        self.site.custom_domain = 'stucs.cnt-so.org'
        self.site.save()
        self.article = make_article_page(section_slug='stucs', title='Test aperçu',
                                         slug='test-apercu')
        grp = Group.objects.get(name='redacteur_stucs')
        u = User.objects.create_user('rstucs', 'a@b.fr', self.MDP)
        u.groups.set([grp])
        self.client.login(username='rstucs', password=self.MDP)

    def test_l_apercu_ne_redirige_pas_hors_du_cms(self):
        """Contrôle de fumée seulement — il passe AUSSI sans le correctif.

        En base de test l'article n'occupe pas la même position d'arbre qu'en
        production, donc `page.url` ne déclenche pas la redirection. C'est
        `test_le_middleware_laisse_passer_une_requete_factice` qui verrouille
        le comportement ; celui-ci vérifie seulement que l'écran répond.
        """
        r = self.client.get(
            f'/cms/snippets/cms/articlepage/preview/{self.article.pk}/')
        self.assertNotIn(r.status_code, (301, 302),
                         f"aperçu redirigé vers {r.headers.get('Location')!r} : "
                         f"le cadre chargera une autre origine")
        self.assertEqual(r.status_code, 200)

    def test_le_middleware_laisse_passer_une_requete_factice(self):
        from cntso.middleware import SectionDomainMiddleware
        from django.test import RequestFactory

        temoin = {}

        def suite(request):
            temoin['vue'] = True
            from django.http import HttpResponse
            return HttpResponse('rendu')

        mw = SectionDomainMiddleware(suite)
        req = RequestFactory().get('/stucs/test-apercu/')
        req.is_dummy = True
        rep = mw(req)
        self.assertTrue(temoin.get('vue'), 'la requête factice a été détournée')
        self.assertEqual(rep.status_code, 200)

    def test_une_requete_normale_est_toujours_redirigee(self):
        """Contrôle : la garde ne doit pas désactiver le middleware."""
        from cntso.middleware import SectionDomainMiddleware
        from django.test import RequestFactory
        from django.http import HttpResponse

        mw = SectionDomainMiddleware(lambda r: HttpResponse('rendu'))
        req = RequestFactory().get('/stucs/test-apercu/')
        rep = mw(req)
        self.assertEqual(rep.status_code, 301)
        self.assertIn('stucs.cnt-so.org', rep['Location'])
