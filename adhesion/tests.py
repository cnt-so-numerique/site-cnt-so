from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from content.models import Author

from .models import Adhesion, ChampCustom, FormulaireAdhesion, ZoneGeographique


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_section_page(slug, name=None, site_type='regional', live=True):
    """Crée (ou retourne) le SectionPage correspondant — bridge Phase 1+."""
    from cms.models import SectionPage, HomePage
    from django.db.models import Q
    from wagtail.models import Page as WagtailPage
    sp = SectionPage.objects.filter(Q(slug=slug) | Q(legacy_site_slug=slug)).first()
    if sp:
        return sp
    home = HomePage.objects.filter(slug='home-test').first()
    if not home:
        root = WagtailPage.objects.filter(depth=1).first()
        home = root.add_child(instance=HomePage(title='Home Test', slug='home-test', live=True))
    return home.add_child(instance=SectionPage(
        title=name or slug,
        slug=slug,
        section_type=site_type,
        live=live,
        legacy_site_slug=slug,
    ))


def make_site(slug='syndicat-test', wp_blog_id=2, site_type='regional', name='Syndicat Test', **kwargs):
    """Crée un SectionPage et le retourne (FK target de tous les modèles)."""
    live = kwargs.get('is_active', True)
    return _ensure_section_page(slug=slug, name=name, site_type=site_type, live=live)


def make_formulaire(site, is_active=True, **kwargs):
    return FormulaireAdhesion.objects.create(site=site, is_active=is_active, **kwargs)


def make_adhesion(site, formulaire=None, email='test@example.com', status='pending', **kwargs):
    return Adhesion.objects.create(
        site=site,
        formulaire=formulaire,
        email=email,
        status=status,
        **kwargs
    )


def make_user(username, password='testpass123', is_superuser=False):
    return User.objects.create_user(username=username, password=password, is_superuser=is_superuser)


def _setup_groups():
    """Configure les groupes avec permissions complètes (content + access_admin Wagtail)."""
    from content.apps import create_editorial_groups
    from django.apps import apps
    create_editorial_groups(apps.get_app_config('auth'))
    from django.contrib.auth.models import Permission
    try:
        access = Permission.objects.get(codename='access_admin')
        for name in ['redacteur', 'redacteur_en_chef']:
            g, _ = Group.objects.get_or_create(name=name)
            g.permissions.add(access)
    except Permission.DoesNotExist:
        pass


def make_chef(username='chef'):
    group = Group.objects.get_or_create(name='redacteur_en_chef')[0]
    user = make_user(username)
    user.groups.add(group)
    return User.objects.get(pk=user.pk)


def make_redacteur(username='redac', site=None):
    group = Group.objects.get_or_create(name='redacteur')[0]
    user = make_user(username)
    user.groups.add(group)
    if site:
        Author.objects.create(user=user, username=username, site=site)
    return User.objects.get(pk=user.pk)


def set_chef_site(client, site):
    session = client.session
    session['redac_current_site_id'] = site.pk
    session.save()


# ═══════════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class FormulaireAdhesionModelTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_fixed_amount_euros_converts_cents(self):
        f = make_formulaire(self.site, fixed_amount_cents=1500)
        self.assertEqual(f.fixed_amount_euros, Decimal('15.00'))

    def test_fixed_amount_euros_none_when_no_amount(self):
        f = make_formulaire(self.site)
        self.assertIsNone(f.fixed_amount_euros)

    def test_fixed_amount_euros_none_when_zero(self):
        f = make_formulaire(self.site, fixed_amount_cents=0)
        self.assertIsNone(f.fixed_amount_euros)

    def test_str(self):
        f = make_formulaire(self.site)
        self.assertIn(self.site.name, str(f))

    def test_one_formulaire_per_site(self):
        make_formulaire(self.site)
        from django.db import IntegrityError
        with self.assertRaises(Exception):
            FormulaireAdhesion.objects.create(site=self.site, is_active=False)


class ChampCustomModelTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)

    def test_slug_auto_generated_from_label(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Mon Champ Spécial', field_type='text'
        )
        self.assertEqual(champ.slug, 'mon-champ-special')

    def test_slug_collision_gets_suffix(self):
        ChampCustom.objects.create(
            formulaire=self.formulaire, label='Commentaire', field_type='text'
        )
        champ2 = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Commentaire', field_type='textarea'
        )
        self.assertEqual(champ2.slug, 'commentaire-1')

    def test_slug_multiple_collisions(self):
        for _ in range(3):
            ChampCustom.objects.create(
                formulaire=self.formulaire, label='Question', field_type='text'
            )
        slugs = list(ChampCustom.objects.values_list('slug', flat=True))
        self.assertEqual(set(slugs), {'question', 'question-1', 'question-2'})

    def test_slug_not_regenerated_on_update(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Original', field_type='text', slug='mon-slug'
        )
        champ.label = 'Changé'
        champ.save()
        champ.refresh_from_db()
        self.assertEqual(champ.slug, 'mon-slug')

    def test_get_choices_list_parses_lines(self):
        champ = ChampCustom(choices_text='Option A\nOption B\n  Option C  \n')
        self.assertEqual(champ.get_choices_list(), ['Option A', 'Option B', 'Option C'])

    def test_get_choices_list_empty(self):
        champ = ChampCustom(choices_text='')
        self.assertEqual(champ.get_choices_list(), [])

    def test_str(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Test', field_type='text'
        )
        self.assertIn('Test', str(champ))
        self.assertIn(self.site.name, str(champ))


class ZoneGeographiqueModelTest(TestCase):
    def test_str(self):
        site = make_site()
        zone = ZoneGeographique.objects.create(site=site, code_prefix='69', label='Rhône')
        self.assertIn('69', str(zone))
        self.assertIn(site.name, str(zone))


class AdhesionModelTest(TestCase):
    def setUp(self):
        self.site = make_site()

    def test_amount_euros_converts_cents(self):
        a = make_adhesion(self.site, amount_cents=2000)
        self.assertEqual(a.amount_euros, Decimal('20.00'))

    def test_amount_euros_none_when_null(self):
        a = make_adhesion(self.site)
        self.assertIsNone(a.amount_euros)

    def test_marquer_actif_sets_status(self):
        a = make_adhesion(self.site)
        a.marquer_actif()
        a.refresh_from_db()
        self.assertEqual(a.status, 'actif')

    def test_marquer_actif_sets_actif_at(self):
        a = make_adhesion(self.site)
        self.assertIsNone(a.actif_at)
        a.marquer_actif()
        a.refresh_from_db()
        self.assertIsNotNone(a.actif_at)

    def test_marquer_actif_does_not_overwrite_existing_actif_at(self):
        original_time = timezone.now() - timedelta(days=10)
        a = make_adhesion(self.site, actif_at=original_time)
        a.marquer_actif()
        a.refresh_from_db()
        self.assertEqual(a.actif_at.date(), original_time.date())

    def test_str(self):
        a = make_adhesion(self.site, nom='Dupont', prenom='Marie')
        self.assertIn('Dupont', str(a))
        self.assertIn('Marie', str(a))

    def test_token_auto_generated(self):
        a = make_adhesion(self.site)
        self.assertIsNotNone(a.token)


# ═══════════════════════════════════════════════════════════════════════════════
# FORMS
# ═══════════════════════════════════════════════════════════════════════════════

class AdhesionFormTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)

    def _form_data(self, **overrides):
        data = {
            'email': 'adhesion@test.fr',
            'nom': 'Durand',
            'prenom': 'Jean',
            'payment_frequency': 'monthly',
            'montant': '10',
            'lieu_signature': 'Paris',
            'certifie': True,
        }
        data.update(overrides)
        return data

    def test_form_has_email_field_always(self):
        from .forms import AdhesionForm
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIn('email', form.fields)

    def test_form_has_nom_prenom_by_default(self):
        from .forms import AdhesionForm
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIn('nom', form.fields)
        self.assertIn('prenom', form.fields)

    def test_form_no_adresse_when_disabled(self):
        from .forms import AdhesionForm
        self.formulaire.field_adresse = False
        self.formulaire.save()
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertNotIn('adresse', form.fields)

    def test_form_has_adresse_when_enabled(self):
        from .forms import AdhesionForm
        self.formulaire.field_adresse = True
        self.formulaire.save()
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIn('adresse', form.fields)

    def test_form_libre_price_has_montant_field(self):
        from .forms import AdhesionForm
        self.formulaire.price_mode = 'libre'
        self.formulaire.save()
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIn('montant', form.fields)

    def test_form_fixed_price_no_montant_field(self):
        from .forms import AdhesionForm
        self.formulaire.price_mode = 'fixed'
        self.formulaire.fixed_amount_cents = 1000
        self.formulaire.save()
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertNotIn('montant', form.fields)

    def test_frequency_choices_match_formulaire(self):
        from .forms import AdhesionForm
        self.formulaire.allow_monthly = True
        self.formulaire.allow_annual = False
        self.formulaire.allow_onetime = False
        self.formulaire.save()
        form = AdhesionForm(formulaire=self.formulaire)
        keys = [k for k, _ in form.fields['payment_frequency'].choices]
        self.assertIn('monthly', keys)
        self.assertNotIn('annual', keys)
        self.assertNotIn('onetime', keys)

    def test_custom_text_field_added(self):
        from .forms import AdhesionForm
        ChampCustom.objects.create(
            formulaire=self.formulaire, label='Question ouverte', field_type='text', is_required=True
        )
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIn('custom_question-ouverte', form.fields)

    def test_custom_select_field_has_choices(self):
        from .forms import AdhesionForm
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Secteur', field_type='select',
            choices_text='Bâtiment\nCommerce\nSanté'
        )
        form = AdhesionForm(formulaire=self.formulaire)
        field = form.fields[f'custom_{champ.slug}']
        choice_values = [v for v, _ in field.choices]
        self.assertIn('Bâtiment', choice_values)
        self.assertIn('Commerce', choice_values)

    def test_custom_checkbox_field_type(self):
        from .forms import AdhesionForm
        from django.forms import BooleanField
        ChampCustom.objects.create(
            formulaire=self.formulaire, label='Accord', field_type='checkbox', is_required=False
        )
        form = AdhesionForm(formulaire=self.formulaire)
        self.assertIsInstance(form.fields['custom_accord'], BooleanField)

    def test_valid_form_is_valid(self):
        from .forms import AdhesionForm
        form = AdhesionForm(self._form_data(), formulaire=self.formulaire)
        self.assertTrue(form.is_valid(), form.errors)

    def test_montant_below_minimum_invalid(self):
        from .forms import AdhesionForm
        form = AdhesionForm(self._form_data(montant='0'), formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('montant', form.errors)

    def test_get_amount_cents_libre(self):
        from .forms import AdhesionForm
        form = AdhesionForm(self._form_data(montant='15'), formulaire=self.formulaire)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_amount_cents(self.formulaire), 1500)

    def test_get_amount_cents_fixed(self):
        from .forms import AdhesionForm
        self.formulaire.price_mode = 'fixed'
        self.formulaire.fixed_amount_cents = 800
        self.formulaire.save()
        data = {
            'email': 'test@test.fr',
            'nom': 'X',
            'prenom': 'Y',
            'payment_frequency': 'monthly',
            'lieu_signature': 'Lyon',
            'certifie': True,
        }
        form = AdhesionForm(data, formulaire=self.formulaire)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_amount_cents(self.formulaire), 800)

    def test_get_custom_data(self):
        from .forms import AdhesionForm
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Poste', field_type='text', is_required=True
        )
        data = self._form_data()
        data[f'custom_{champ.slug}'] = 'Technicien'
        form = AdhesionForm(data, formulaire=self.formulaire)
        self.assertTrue(form.is_valid(), form.errors)
        custom = form.get_custom_data(self.formulaire)
        self.assertEqual(custom[champ.slug], 'Technicien')


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC VIEWS
# ═══════════════════════════════════════════════════════════════════════════════

class FormulaireViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire(self.site, is_active=True)
        self.url = reverse('adhesion:formulaire', kwargs={'site_slug': self.site.slug})

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_get_404_if_site_inactive(self):
        self.site.live = False
        self.site.save(update_fields=['live'])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_get_404_if_site_not_found(self):
        response = self.client.get(
            reverse('adhesion:formulaire', kwargs={'site_slug': 'inexistant'})
        )
        self.assertEqual(response.status_code, 404)

    def test_get_404_if_formulaire_inactive(self):
        self.formulaire.is_active = False
        self.formulaire.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_post_valid_creates_adhesion(self):
        data = {
            'email': 'nouveau@membre.fr',
            'nom': 'Martin',
            'prenom': 'Alice',
            'payment_frequency': 'monthly',
            'montant': '12',
            'lieu_signature': 'Marseille',
            'certifie': True,
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Adhesion.objects.filter(email='nouveau@membre.fr').exists())

    def test_post_valid_redirects_to_succes(self):
        data = {
            'email': 'test@membre.fr',
            'nom': 'Test',
            'prenom': 'User',
            'payment_frequency': 'monthly',
            'montant': '5',
            'lieu_signature': 'Lyon',
            'certifie': True,
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(
            response,
            reverse('adhesion:paiement_succes', kwargs={'site_slug': self.site.slug}),
            fetch_redirect_response=False,
        )

    def test_post_invalid_rerenders_form(self):
        response = self.client.post(self.url, {'email': 'invalide', 'certifie': False})
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_post_sets_adhesion_fields(self):
        data = {
            'email': 'complet@test.fr',
            'nom': 'Duval',
            'prenom': 'Lucie',
            'payment_frequency': 'annual',
            'montant': '50',
            'lieu_signature': 'Nantes',
            'certifie': True,
        }
        self.client.post(self.url, data)
        a = Adhesion.objects.get(email='complet@test.fr')
        self.assertEqual(a.nom, 'Duval')
        self.assertEqual(a.payment_frequency, 'annual')
        self.assertEqual(a.amount_cents, 5000)
        self.assertEqual(a.status, 'pending')

    def test_embed_mode_uses_embed_template(self):
        response = self.client.get(self.url + '?embed=1')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'adhesion/formulaire_embed.html')

    def test_normal_mode_uses_standard_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'adhesion/formulaire.html')


class PaiementSuccesViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.url = reverse('adhesion:paiement_succes', kwargs={'site_slug': self.site.slug})

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_site_in_context(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['site'], self.site)


class PaiementAnnuleViewTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.url = reverse('adhesion:paiement_annule', kwargs={'site_slug': self.site.slug})

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_site_in_context(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['site'], self.site)


# ═══════════════════════════════════════════════════════════════════════════════
# REDACTION VIEWS
# ═══════════════════════════════════════════════════════════════════════════════

class AdhesionListViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)
        self.chef = make_chef('chef1')
        self.url = '/cms/adhesions/'

    def test_anonymous_redirected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_non_chef_redirected_to_dashboard(self):
        user = User.objects.create_user(username='pleb', password='pass')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cms/', response['Location'])

    def test_chef_with_site_sees_site_adhesions(self):
        other_site = make_site(slug='autre', wp_blog_id=3)
        make_adhesion(self.site, email='mine@test.fr')
        make_adhesion(other_site, email='other@test.fr')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        emails = [a.email for a in response.context['adhesions']]
        self.assertIn('mine@test.fr', emails)
        self.assertNotIn('other@test.fr', emails)

    def test_superuser_without_site_sees_all(self):
        other_site = make_site(slug='autre2', wp_blog_id=4)
        make_adhesion(self.site, email='a1@test.fr')
        make_adhesion(other_site, email='a2@test.fr')
        superuser = User.objects.create_superuser(username='sup', password='pass')
        self.client.force_login(superuser)
        response = self.client.get(self.url)
        emails = [a.email for a in response.context['adhesions']]
        self.assertIn('a1@test.fr', emails)
        self.assertIn('a2@test.fr', emails)

    def test_filter_by_status(self):
        make_adhesion(self.site, email='pending@test.fr', status='pending')
        make_adhesion(self.site, email='actif@test.fr', status='actif')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url + '?status=actif')
        emails = [a.email for a in response.context['adhesions']]
        self.assertIn('actif@test.fr', emails)
        self.assertNotIn('pending@test.fr', emails)

    def test_search_by_email(self):
        make_adhesion(self.site, email='trouve@test.fr', nom='Quelconque')
        make_adhesion(self.site, email='autre@test.fr', nom='Autre')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url + '?q=trouve')
        emails = [a.email for a in response.context['adhesions']]
        self.assertIn('trouve@test.fr', emails)
        self.assertNotIn('autre@test.fr', emails)

    def test_search_by_nom(self):
        make_adhesion(self.site, email='a@test.fr', nom='Bertrand')
        make_adhesion(self.site, email='b@test.fr', nom='Dupont')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url + '?q=Bertrand')
        emails = [a.email for a in response.context['adhesions']]
        self.assertIn('a@test.fr', emails)
        self.assertNotIn('b@test.fr', emails)


class AdhesionDetailViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)
        self.chef = make_chef('chef2')
        self.adhesion = make_adhesion(self.site, email='detail@test.fr', status='pending')
        self.url = f'/cms/adhesions/{self.adhesion.pk}/' 

    def test_get_returns_200(self):
        self.client.force_login(self.chef)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['adhesion'], self.adhesion)

    def test_changer_statut_actif(self):
        self.client.force_login(self.chef)
        self.client.post(self.url, {'action': 'changer_statut', 'status': 'actif'})
        self.adhesion.refresh_from_db()
        self.assertEqual(self.adhesion.status, 'actif')

    def test_changer_statut_actif_sets_actif_at(self):
        self.client.force_login(self.chef)
        self.client.post(self.url, {'action': 'changer_statut', 'status': 'actif'})
        self.adhesion.refresh_from_db()
        self.assertIsNotNone(self.adhesion.actif_at)

    def test_changer_statut_invalide_ignored(self):
        self.client.force_login(self.chef)
        self.client.post(self.url, {'action': 'changer_statut', 'status': 'bidon'})
        self.adhesion.refresh_from_db()
        self.assertEqual(self.adhesion.status, 'pending')

    def test_changer_syndicat(self):
        other_site = make_site(slug='autre3', wp_blog_id=5)
        self.client.force_login(self.chef)
        self.client.post(self.url, {'action': 'changer_syndicat', 'site_id': other_site.pk})
        self.adhesion.refresh_from_db()
        self.assertEqual(self.adhesion.site, other_site)

    def test_note_interne(self):
        self.client.force_login(self.chef)
        self.client.post(self.url, {'action': 'note_interne', 'note_interne': 'À relancer'})
        self.adhesion.refresh_from_db()
        self.assertEqual(self.adhesion.note_interne, 'À relancer')

    def test_post_redirects_to_detail(self):
        self.client.force_login(self.chef)
        response = self.client.post(self.url, {'action': 'note_interne', 'note_interne': 'note'})
        self.assertRedirects(
            response,
            f'/cms/adhesions/{self.adhesion.pk}/' ,
            fetch_redirect_response=False,
        )


class AdhesionExportViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.chef = make_chef('chef3')
        self.url = '/cms/adhesions/export/'

    def test_no_site_redirects(self):
        self.client.force_login(self.chef)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_with_site_returns_csv(self):
        make_adhesion(self.site, email='export@test.fr', nom='Legrand', prenom='Paul')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])

    def test_csv_contains_adhesion_data(self):
        make_adhesion(self.site, email='csv@test.fr', nom='Moreau')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        content = response.content.decode('utf-8-sig')
        self.assertIn('csv@test.fr', content)
        self.assertIn('Moreau', content)

    def test_csv_filename_contains_site_slug(self):
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        disposition = response['Content-Disposition']
        self.assertIn(self.site.slug, disposition)


class AdhesionRelanceViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.chef = make_chef('chef4')
        self.url = '/cms/adhesions/relance/'

    def _make_old_pending(self, email='relance@test.fr'):
        a = make_adhesion(self.site, email=email, status='pending')
        Adhesion.objects.filter(pk=a.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        return a

    def test_no_site_get_redirects(self):
        self.client.force_login(self.chef)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_with_site_shows_pending(self):
        self._make_old_pending()
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['adhesions'].count(), 1)

    def test_recent_pending_not_shown(self):
        make_adhesion(self.site, email='recent@test.fr', status='pending')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.get(self.url)
        self.assertEqual(response.context['adhesions'].count(), 0)

    @patch('adhesion.views.send_relance_email')
    def test_post_sends_relance_emails(self, mock_send):
        self._make_old_pending()
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()

    @patch('adhesion.views.send_relance_email')
    def test_post_skips_recent_pending(self, mock_send):
        make_adhesion(self.site, email='recent2@test.fr', status='pending')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        self.client.post(self.url)
        mock_send.assert_not_called()


class FormulaireConfigViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.chef = make_chef('chef5')
        self.url = '/cms/adhesion-config/'

    def test_no_site_redirects(self):
        self.client.force_login(self.chef)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_creates_formulaire_if_none(self):
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        self.assertFalse(FormulaireAdhesion.objects.filter(site=self.site).exists())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(FormulaireAdhesion.objects.filter(site=self.site).exists())

    def test_get_reuses_existing_formulaire(self):
        f = make_formulaire(self.site)
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        self.client.get(self.url)
        self.assertEqual(FormulaireAdhesion.objects.filter(site=self.site).count(), 1)

    def test_post_saves_config(self):
        make_formulaire(self.site, is_active=False)
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        self.client.post(self.url, {
            'is_active': 'on',
            'price_mode': 'fixed',
            'fixed_amount_euros': '5',
            'allow_monthly': 'on',
            'field_nom': 'on',
            'field_prenom': 'on',
            'lieu_defaut': 'Paris',
            'email_from': 'from@test.fr',
            'email_contact': 'contact@test.fr',
        })
        f = FormulaireAdhesion.objects.get(site=self.site)
        self.assertTrue(f.is_active)
        self.assertEqual(f.price_mode, 'fixed')
        self.assertEqual(f.fixed_amount_cents, 500)
        self.assertEqual(f.lieu_defaut, 'Paris')

    def test_post_redirects_to_config(self):
        make_formulaire(self.site)
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)
        response = self.client.post(self.url, {'price_mode': 'libre'})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)


class ChampCustomCRUDViewTest(TestCase):
    def setUp(self):
        _setup_groups()
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)
        self.chef = make_chef('chef6')
        self.client.force_login(self.chef)
        set_chef_site(self.client, self.site)

    def test_create_champ(self):
        self.client.post(
            '/cms/adhesion-config/champ/ajouter/',
            {'label': 'Poste occupé', 'field_type': 'text', 'choices_text': '', 'is_required': ''}
        )
        self.assertTrue(ChampCustom.objects.filter(formulaire=self.formulaire, label='Poste occupé').exists())

    def test_create_champ_empty_label_rejected(self):
        self.client.post(
            '/cms/adhesion-config/champ/ajouter/',
            {'label': '', 'field_type': 'text'}
        )
        self.assertFalse(ChampCustom.objects.filter(formulaire=self.formulaire).exists())

    def test_edit_champ(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Ancien libellé', field_type='text'
        )
        self.client.post(
            f'/cms/adhesion-config/champ/{champ.pk}/modifier/' ,
            {'label': 'Nouveau libellé', 'field_type': 'textarea', 'choices_text': ''}
        )
        champ.refresh_from_db()
        self.assertEqual(champ.label, 'Nouveau libellé')
        self.assertEqual(champ.field_type, 'textarea')

    def test_delete_champ(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='À supprimer', field_type='text'
        )
        self.client.post(
            f'/cms/adhesion-config/champ/{champ.pk}/supprimer/' 
        )
        self.assertFalse(ChampCustom.objects.filter(pk=champ.pk).exists())

    def test_create_redirects_to_config(self):
        response = self.client.post(
            '/cms/adhesion-config/champ/ajouter/',
            {'label': 'Test', 'field_type': 'text'}
        )
        self.assertRedirects(
            response, '/cms/adhesion-config/', fetch_redirect_response=False
        )

    def test_delete_redirects_to_config(self):
        champ = ChampCustom.objects.create(
            formulaire=self.formulaire, label='Del', field_type='text'
        )
        response = self.client.post(
            f'/cms/adhesion-config/champ/{champ.pk}/supprimer/' 
        )
        self.assertRedirects(
            response, '/cms/adhesion-config/', fetch_redirect_response=False
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS DE SÉCURITÉ — IDOR et validation
# ═══════════════════════════════════════════════════════════════════════════════

def make_chef_user(username='chef', site=None):
    from django.contrib.auth.models import Group
    from content.models import Author
    group, _ = Group.objects.get_or_create(name='redacteur_en_chef')
    user = User.objects.create_user(username=username, password='pass')
    user.groups.add(group)
    if site:
        Author.objects.create(user=user, site=site, username=username)
    return user


class IDORAdhesionDetailTest(TestCase):
    """Vérifie qu'un chef ne peut pas accéder aux adhésions d'un autre site."""

    def setUp(self):
        from django.contrib.auth.models import Permission
        from content.admin_utils import WagtailChefRequiredMixin
        # Wagtail access_admin permission
        try:
            from django.contrib.auth.models import Group, Permission
            access = Permission.objects.get(codename='access_admin')
            chef_group, _ = Group.objects.get_or_create(name='redacteur_en_chef')
            chef_group.permissions.add(access)
        except Exception:
            pass

        self.site_a = make_site(slug='site-a', wp_blog_id=10, name='Site A')
        self.site_b = make_site(slug='site-b', wp_blog_id=11, name='Site B')
        self.form_a = make_formulaire(self.site_a)
        self.form_b = make_formulaire(self.site_b)
        self.adhesion_a = make_adhesion(self.site_a, self.form_a, email='a@test.com')
        self.adhesion_b = make_adhesion(self.site_b, self.form_b, email='b@test.com')
        self.chef_a = make_chef_user('chef_a', site=self.site_a)

    def test_chef_cannot_access_other_site_adhesion(self):
        """Chef de site A ne peut pas voir les adhésions de site B."""
        self.client.force_login(self.chef_a)
        session = self.client.session
        session['redac_current_site_id'] = self.site_a.pk
        session.save()
        url = f'/cms/adhesions/{self.adhesion_b.pk}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_chef_cannot_modify_other_site_adhesion(self):
        """Chef de site A ne peut pas modifier le statut d'une adhésion de site B."""
        self.client.force_login(self.chef_a)
        session = self.client.session
        session['redac_current_site_id'] = self.site_a.pk
        session.save()
        url = f'/cms/adhesions/{self.adhesion_b.pk}/'
        response = self.client.post(url, {'action': 'changer_statut', 'status': 'actif'})
        self.assertEqual(response.status_code, 404)
        self.adhesion_b.refresh_from_db()
        self.assertNotEqual(self.adhesion_b.status, 'actif')

    def test_chef_can_access_own_site_adhesion(self):
        """Chef de site A peut voir ses propres adhésions."""
        self.client.force_login(self.chef_a)
        session = self.client.session
        session['redac_current_site_id'] = self.site_a.pk
        session.save()
        url = f'/cms/adhesions/{self.adhesion_a.pk}/'
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 302])

    def test_superuser_can_access_any_adhesion(self):
        """Superuser sans site sélectionné → accès à tout."""
        superuser = User.objects.create_superuser('super2', password='pass')
        self.client.force_login(superuser)
        url = f'/cms/adhesions/{self.adhesion_b.pk}/'
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 302])


class AdhesionFormMaxAmountTest(TestCase):
    """Vérifie la validation du montant."""

    def setUp(self):
        self.site = make_site()
        self.formulaire = make_formulaire(self.site)

    def test_montant_above_maximum_invalid(self):
        from adhesion.forms import AdhesionForm
        form = AdhesionForm({'email': 'a@b.com', 'montant': '10000'}, formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('montant', form.errors)

    def test_montant_at_maximum_valid(self):
        from adhesion.forms import AdhesionForm
        form = AdhesionForm({'email': 'a@b.com', 'montant': '9999'}, formulaire=self.formulaire)
        self.assertNotIn('montant', form.errors)

    def test_montant_below_minimum_still_invalid(self):
        from adhesion.forms import AdhesionForm
        form = AdhesionForm({'email': 'a@b.com', 'montant': '0'}, formulaire=self.formulaire)
        self.assertFalse(form.is_valid())
        self.assertIn('montant', form.errors)
