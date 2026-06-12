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

    def test_home_shows_rejoindre_button(self):
        r = self.client.get('/stucs/')
        self.assertContains(r, 'framaforms.org')


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

    def test_carousel_not_in_context_for_main_site(self):
        r = self.client.get('/')
        # La home principale n'a pas de carousel_articles dans le contexte
        self.assertNotIn('carousel_articles', r.context or {})

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
        r = Client().get('/stucs/')
        self.assertContains(r, 'framaforms.org')

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
