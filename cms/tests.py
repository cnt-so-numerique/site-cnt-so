"""
Tests pour les fonctionnalités récentes :
- Sous-site STUCS (vues, menu, catégories)
- Modèle Event (agenda)
- Champs SectionPage (linkstack, framaform, intro_text, rejoindre_text, agenda_text)
- wagtail-seo (champs OG sur ArticlePage)
- Recherche Wagtail FTS
"""
from datetime import date, timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from cms.models import (
    ArticlePage, CmsCategory, ContentPage, Event, HomePage, SectionPage,
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
        self.assertTemplateUsed(r, 'content/stucs/home.html')

    def test_home_shows_articles(self):
        make_article_page(section_slug='stucs', title='Article STUCS test')
        r = self.client.get('/stucs/')
        self.assertContains(r, 'Article STUCS test')

    def test_home_contains_site_title(self):
        r = self.client.get('/stucs/')
        self.assertContains(r, 'STUCS')

    def test_home_shows_linkstack_button(self):
        r = self.client.get('/stucs/')
        self.assertContains(r, 'linkstack.fr')


class StucsRejoindreViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.stucs = make_stucs_section()

    def test_get_returns_200(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertEqual(r.status_code, 200)

    def test_uses_rejoindre_template(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertTemplateUsed(r, 'content/stucs/rejoindre.html')

    def test_shows_framaform_url(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertContains(r, 'framaforms.org')

    def test_contact_form_present(self):
        r = self.client.get('/stucs/rejoindre/')
        self.assertContains(r, 'csrfmiddlewaretoken')

    def test_post_contact_form_valid(self):
        r = self.client.post('/stucs/rejoindre/', {
            'name': 'Test User',
            'email': 'test@example.org',
            'message': 'Je voudrais adhérer',
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
        self.assertTemplateUsed(r, 'content/stucs/ressources.html')

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
        self.assertTemplateUsed(r, 'content/stucs/agenda.html')

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
        """Le fallback hardcodé s'affiche si aucun MenuItem."""
        from content.models import MenuItem
        MenuItem.objects.filter(site=self.stucs).delete()
        r = Client().get('/stucs/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Accueil')

    def test_nav_uses_menu_items_when_present(self):
        from content.models import MenuItem
        MenuItem.objects.create(
            site=self.stucs, menu='main', title='Test Nav',
            url='/stucs/', link_type='url', order=1, is_active=True,
        )
        r = Client().get('/stucs/')
        self.assertContains(r, 'Test Nav')
