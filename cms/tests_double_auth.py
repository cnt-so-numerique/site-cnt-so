"""Double authentification de /cms/ et /admin/ (cms/double_auth.py).

Les tests tournent avec `DOUBLE_AUTH_OBLIGATOIRE = 'personne'` (settings.py) ;
ceux-ci remettent le réglage de prod.
"""
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from cms.double_auth import AjouterTelephoneView
from cms.models import EchecsDoubleAuth

CODE = reverse('cms_double_auth_code')
AJOUTER = reverse('cms_double_auth_ajouter')


def code_de(telephone):
    return str(totp(telephone.bin_key)).zfill(6)


def redacteur(nom='redac'):
    user = User.objects.create_user(nom, password='mdp-redac')
    user.user_permissions.add(Permission.objects.get(
        codename='access_admin', content_type__app_label='wagtailadmin'))
    return user


def telephone(user, nom='téléphone de Sam'):
    return TOTPDevice.objects.create(user=user, name=nom, confirmed=True)


@override_settings(DOUBLE_AUTH_OBLIGATOIRE='superutilisateurs')
class DoubleAuthTest(TestCase):

    def setUp(self):
        self.redac = redacteur()
        self.chef = User.objects.create_superuser('chef', 'chef@example.org', 'mdp-chef')

    def _donner_code(self, code, suite='/cms/'):
        return self.client.post(CODE, {'code': code, 'next': suite})

    # ── Rédacteurs : facultative ──────────────────────────────────────────

    def test_redacteur_sans_telephone_entre_au_mot_de_passe(self):
        self.client.force_login(self.redac)
        self.assertEqual(self.client.get('/cms/').status_code, 200)

    def test_redacteur_avec_telephone_doit_donner_son_code(self):
        tel = telephone(self.redac)
        self.client.force_login(self.redac)
        r = self.client.get('/cms/pages/')
        self.assertRedirects(r, CODE + '?next=%2Fcms%2Fpages%2F', fetch_redirect_response=False)

        r = self._donner_code(code_de(tel), suite='/cms/pages/')
        self.assertRedirects(r, '/cms/pages/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/cms/').status_code, 200)

    def test_code_faux_refuse_et_compte(self):
        telephone(self.redac)
        self.client.force_login(self.redac)
        r = self._donner_code('000000')
        self.assertContains(r, 'pas bon, ou il a déjà servi')
        self.assertEqual(EchecsDoubleAuth.objects.get(user=self.redac).nombre, 1)
        self.assertEqual(self.client.get('/cms/').status_code, 302)

    def test_essais_limites_meme_avec_le_bon_code(self):
        tel = telephone(self.redac)
        self.client.force_login(self.redac)
        for _ in range(3):
            self._donner_code('000000')
        r = self._donner_code(code_de(tel))
        self.assertContains(r, 'Trop de codes faux')
        self.assertEqual(self.client.get('/cms/').status_code, 302)

    def test_compte_partage_un_telephone_ne_bloque_pas_l_autre(self):
        # Avec la limitation par appareil de django-otp, chaque connexion par
        # le téléphone de Sam comptait un échec sur celui de Lou.
        sam = telephone(self.redac, 'Sam')
        lou = telephone(self.redac, 'Lou')
        if sam.pk > lou.pk:  # Sam, essayé le premier, est celui qui encaissait
            sam, lou = lou, sam
        for _ in range(3):
            self.client.force_login(self.redac)
            self.assertEqual(self._donner_code(code_de(lou)).status_code, 302)
            self.client.logout()
            TOTPDevice.objects.filter(pk=lou.pk).update(last_t=-1)
        self.client.force_login(self.redac)
        r = self._donner_code(code_de(sam))
        self.assertRedirects(r, '/cms/', fetch_redirect_response=False)

    def test_suite_vers_un_autre_site_refusee(self):
        tel = telephone(self.redac)
        self.client.force_login(self.redac)
        r = self._donner_code(code_de(tel), suite='https://ailleurs.example/')
        self.assertRedirects(r, '/cms/', fetch_redirect_response=False)

    def test_session_sans_code_ne_peut_pas_ajouter_son_telephone(self):
        # Un mot de passe volé ne doit pas permettre d'enregistrer un téléphone.
        telephone(self.redac)
        self.client.force_login(self.redac)
        r = self.client.get(AJOUTER)
        self.assertRedirects(r, CODE + '?next=' + AJOUTER.replace('/', '%2F'),
                             fetch_redirect_response=False)

    # ── Superutilisateurs : obligatoire, /admin/ compris ──────────────────

    def test_superutilisateur_sans_telephone_doit_s_enroler(self):
        self.client.force_login(self.chef)
        for chemin in ('/cms/', '/cms/pages/', '/admin/', '/admin/auth/user/'):
            r = self.client.get(chemin)
            self.assertEqual(r.status_code, 302, chemin)
            self.assertTrue(r['Location'].startswith(AJOUTER), chemin)

    def _enroler(self, user, mdp, **modifs):
        self.client.force_login(user)
        self.assertEqual(self.client.get(AJOUTER).status_code, 200)
        cle = self.client.session[AjouterTelephoneView.CLE_SESSION]
        donnees = {'nom': 'téléphone du chef', 'mot_de_passe': mdp,
                   'code': str(totp(bytes.fromhex(cle))).zfill(6), 'next': '/cms/'}
        donnees.update(modifs)
        return self.client.post(AJOUTER, donnees)

    def test_enrolement_complet(self):
        r = self._enroler(self.chef, 'mdp-chef')
        self.assertContains(r, 'Codes de secours')
        self.assertEqual(TOTPDevice.objects.filter(user=self.chef, confirmed=True).count(), 1)
        self.assertEqual(StaticToken.objects.filter(device__user=self.chef).count(), 10)
        self.assertEqual(self.client.get('/cms/').status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_requete_de_fond_ne_change_pas_la_cle(self):
        # Chaque page de l'admin charge /cms/current-site-fragment/ en fond ;
        # renvoyée vers l'enrôlement, elle remplaçait la clé scannée (27/10).
        self.client.force_login(self.chef)
        self.client.get(AJOUTER)
        cle = self.client.session[AjouterTelephoneView.CLE_SESSION]
        r = self.client.get('/cms/current-site-fragment/', follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session[AjouterTelephoneView.CLE_SESSION], cle)

    def test_enrolement_code_faux_n_enregistre_rien(self):
        # TOTPDevice.verify_token enregistrait l'appareil, confirmé, sur un code faux.
        r = self._enroler(self.chef, 'mdp-chef', code='000000')
        self.assertContains(r, 'Ce code ne correspond pas')
        self.assertFalse(TOTPDevice.objects.exists())
        self.assertEqual(self.client.get('/cms/').status_code, 302)

    def test_enrolement_mauvais_mot_de_passe_n_enregistre_rien(self):
        r = self._enroler(self.chef, 'pas-le-bon')
        self.assertContains(r, "Ce n&#x27;est pas le bon mot de passe")
        self.assertFalse(TOTPDevice.objects.exists())

    # ── Codes de secours ──────────────────────────────────────────────────

    def test_code_de_secours_ne_sert_qu_une_fois(self):
        self._enroler(self.redac, 'mdp-redac')
        code = StaticToken.objects.filter(device__user=self.redac).first().token
        for attendu in (302, 200):
            self.client.logout()
            self.client.force_login(self.redac)
            self.assertEqual(self._donner_code(code.upper()).status_code, attendu)
        self.assertEqual(StaticToken.objects.filter(device__user=self.redac).count(), 9)

    def test_nouveaux_codes_invalident_les_anciens(self):
        self._enroler(self.redac, 'mdp-redac')
        anciens = set(StaticToken.objects.values_list('token', flat=True))
        r = self.client.post(reverse('cms_double_auth_codes'))
        nouveaux = set(StaticToken.objects.values_list('token', flat=True))
        self.assertEqual(len(nouveaux), 10)
        self.assertFalse(anciens & nouveaux)
        for code in nouveaux:
            self.assertContains(r, code)

    # ── Retrait ───────────────────────────────────────────────────────────

    def _chef_verifie(self):
        self._enroler(self.chef, 'mdp-chef')

    def test_superutilisateur_retire_le_telephone_d_un_redacteur(self):
        tel = telephone(self.redac)
        StaticDevice.objects.create(user=self.redac, name='secours')
        self._chef_verifie()
        page = self.client.get(reverse('cms_double_auth_compte', args=[self.redac.pk]))
        self.assertContains(page, 'téléphone de Sam')
        self.client.post(reverse('cms_double_auth_retirer', args=[tel.pk]))
        self.assertFalse(TOTPDevice.objects.filter(user=self.redac).exists())
        # Dernier téléphone : les codes de secours partent avec.
        self.assertFalse(StaticDevice.objects.filter(user=self.redac).exists())
        self.client.force_login(self.redac)
        self.assertEqual(self.client.get('/cms/').status_code, 200)

    def test_redacteur_ne_touche_pas_aux_telephones_des_autres(self):
        autre = redacteur('autre')
        tel = telephone(autre)
        self.client.force_login(self.redac)
        r = self.client.get(reverse('cms_double_auth_compte', args=[autre.pk]))
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse('cms_double_auth_retirer', args=[tel.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(TOTPDevice.objects.filter(pk=tel.pk).exists())

    def test_telephone_retire_la_session_doit_redonner_un_code(self):
        sam = telephone(self.redac, 'Sam')
        lou = telephone(self.redac, 'Lou')
        self.client.force_login(self.redac)
        self._donner_code(code_de(sam))
        self.assertEqual(self.client.get('/cms/').status_code, 200)
        sam.delete()  # retiré depuis un autre poste
        r = self.client.get('/cms/')
        self.assertRedirects(r, CODE + '?next=%2Fcms%2F', fetch_redirect_response=False)
        self.assertTrue(TOTPDevice.objects.filter(pk=lou.pk).exists())

    def test_commande_de_dernier_recours(self):
        telephone(self.chef)
        call_command('retire_double_auth', 'chef', stdout=open('/dev/null', 'w'))
        self.assertFalse(TOTPDevice.objects.filter(user=self.chef).exists())


class ReglageParDefautTest(TestCase):
    """Sans override : le réglage de test n'oblige personne."""

    def test_reglage_de_test(self):
        from django.conf import settings
        self.assertEqual(settings.DOUBLE_AUTH_OBLIGATOIRE, 'personne')

    @override_settings(DOUBLE_AUTH_OBLIGATOIRE='tous')
    def test_tous_oblige_les_redacteurs(self):
        self.client.force_login(redacteur())
        r = self.client.get('/cms/')
        self.assertTrue(r['Location'].startswith(AJOUTER))
