"""Carte interne des implantations (/cms/implantations/).

Ce qui compte : seules les personnes du groupe « Carte des implantations »
(et les superusers) y accèdent — pas les chefs d'office — ; seul un superuser
peut donner ce groupe ; et un texte piégé saisi dans une implantation n'est
jamais interprété comme du HTML.
"""
import json
import re

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from cms import double_auth
from cms.implantations import cle, libelles
from cms.models import Implantation
from content.admin_forms import SyndicatUserEditForm
from content.apps import GROUPE_CARTE
from content.tests import _setup_editorial_groups, make_chef, make_redacteur, make_site, make_superuser

CARTE = '/cms/implantations/'
PIEGE = '<img src=x onerror="alert(1)">'


def membre_carte(username='cartographe'):
    user = make_redacteur(username=username)
    user.groups.add(Group.objects.get(name=GROUPE_CARTE))
    return User.objects.get(pk=user.pk)


def implantation(syndicat, **kwargs):
    valeurs = {'nom': 'Entrepôt de Brétigny', 'latitude': 48.6, 'longitude': 2.3}
    valeurs.update(kwargs)
    return Implantation.objects.create(syndicat=syndicat, **valeurs)


def donnees_de(reponse):
    return json.loads(re.search(
        r'<script id="implantations-donnees" type="application/json">(.*?)</script>',
        reponse.content.decode(), re.S).group(1))


class Base(TestCase):

    def setUp(self):
        _setup_editorial_groups()
        self.stucs = make_site(slug='stucs', name='STUCS', site_type='sectoral')
        self.ese = make_site(slug='ese', name='ESE', site_type='sectoral')
        self.amazon_stucs = implantation(self.stucs, entreprise='Amazon', type_implantation='Section syndicale',
                                         contact_nom='Camille', telephone='06 12 34 56 78',
                                         texte_libre='Réunion le jeudi')
        self.amazon_ese = implantation(self.ese, nom='Amazon Saran', entreprise=' amazon ',
                                       type_implantation='section syndicale')
        self.local = implantation(self.ese, nom='Local de Lyon', adresse='Lyon')


class AccesTest(Base):

    def test_anonyme_renvoye_a_la_connexion(self):
        reponse = self.client.get(CARTE)
        self.assertEqual(reponse.status_code, 302)
        self.assertIn('/cms/login/', reponse['Location'])

    def test_redacteur_sans_le_groupe_refuse(self):
        self.client.force_login(make_redacteur())
        for url in (CARTE, f'{CARTE}ajouter/', f'{CARTE}{self.local.pk}/', f'{CARTE}{self.local.pk}/supprimer/'):
            reponse = self.client.get(url)
            self.assertEqual(reponse.status_code, 302, url)
            self.assertNotContains(reponse, 'Camille', status_code=302)

    def test_chef_sans_le_groupe_refuse(self):
        """Être rédacteur en chef ne suffit pas : la carte est donnée à quelques personnes."""
        self.client.force_login(make_chef())
        self.assertEqual(self.client.get(CARTE).status_code, 302)
        self.client.post(f'{CARTE}{self.local.pk}/supprimer/')
        self.assertTrue(Implantation.objects.filter(pk=self.local.pk).exists())

    def test_membre_du_groupe_voit_la_carte(self):
        self.client.force_login(membre_carte())
        reponse = self.client.get(CARTE)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual({p['nom'] for p in donnees_de(reponse)},
                         {'Entrepôt de Brétigny', 'Amazon Saran', 'Local de Lyon'})

    def test_superuser_voit_la_carte(self):
        self.client.force_login(make_superuser())
        self.assertEqual(self.client.get(CARTE).status_code, 200)

    def test_menu_seulement_avec_la_permission(self):
        self.client.force_login(make_chef())
        self.assertNotContains(self.client.get('/cms/'), CARTE)
        self.client.force_login(membre_carte())
        self.assertContains(self.client.get('/cms/'), CARTE)


class CarteTest(Base):

    def setUp(self):
        super().setUp()
        self.client.force_login(membre_carte())

    def test_un_filtre_par_syndicat(self):
        contenu = self.client.get(CARTE).content.decode()
        for site in (self.stucs, self.ese):
            self.assertRegex(contenu, rf'name="syndicat" value="{site.pk}"')

    def test_entreprises_regroupees_sans_tenir_compte_de_la_casse(self):
        reponse = self.client.get(CARTE)
        self.assertEqual([(e['nom'], e['nombre']) for e in reponse.context['entreprises']], [('Amazon', 2)])
        self.assertEqual(sum(1 for p in donnees_de(reponse) if p['entreprise'] == 'amazon'), 2)
        self.assertEqual([t['nombre'] for t in reponse.context['types']], [2])
        self.assertEqual(reponse.context['sans_type'], 1)

    def test_contact_et_texte_libre_dans_la_bulle(self):
        point = next(p for p in donnees_de(self.client.get(CARTE)) if p['id'] == self.amazon_stucs.pk)
        self.assertEqual((point['contact'], point['telephone'], point['notes']),
                         ('Camille', '06 12 34 56 78', 'Réunion le jeudi'))

    def test_texte_piege_jamais_interprete(self):
        implantation(self.stucs, nom=PIEGE, texte_libre=PIEGE, entreprise=PIEGE, type_implantation=PIEGE)
        reponse = self.client.get(CARTE)
        self.assertNotContains(reponse, '<img src=x')
        # …mais il est bien là, intact, pour être affiché en texte.
        self.assertIn(PIEGE, [p['nom'] for p in donnees_de(reponse)])

    def test_carte_vide(self):
        Implantation.objects.all().delete()
        self.assertContains(self.client.get(CARTE), 'Aucune implantation')


class SaisieTest(Base):

    def setUp(self):
        super().setUp()
        self.user = membre_carte()
        self.client.force_login(self.user)

    def donnees(self, **kwargs):
        valeurs = {'syndicat': self.stucs.pk, 'nom': 'Adhérente à Montreuil', 'type_implantation': '',
                   'entreprise': '', 'adresse': 'Montreuil', 'latitude': '48.86', 'longitude': '2.44',
                   'contact_nom': '', 'telephone': '', 'email': '', 'texte_libre': 'Texte libre'}
        valeurs.update(kwargs)
        return valeurs

    def test_ajout_avec_une_simple_ville(self):
        reponse = self.client.post(f'{CARTE}ajouter/', self.donnees())
        self.assertRedirects(reponse, CARTE)
        nouvelle = Implantation.objects.get(nom='Adhérente à Montreuil')
        self.assertEqual((nouvelle.adresse, nouvelle.modifie_par), ('Montreuil', self.user))

    def test_suggestions_du_formulaire(self):
        contexte = self.client.get(f'{CARTE}ajouter/').context
        self.assertEqual(contexte['entreprises_connues'], ['Amazon'])
        self.assertIn('Local syndical', contexte['types_connus'])

    def test_position_obligatoire_et_bornee(self):
        reponse = self.client.post(f'{CARTE}ajouter/', self.donnees(latitude='', longitude='200'))
        self.assertEqual(reponse.status_code, 200)
        self.assertFormError(reponse.context['form'], 'latitude',
                             "Placez le point : cherchez l'adresse ou cliquez sur la carte.")
        self.assertFormError(reponse.context['form'], 'longitude', 'Longitude hors limites (entre -180 et 180).')
        self.assertFalse(Implantation.objects.filter(nom='Adhérente à Montreuil').exists())

    def test_modification(self):
        self.client.post(f'{CARTE}{self.local.pk}/', self.donnees(nom='Local de Villeurbanne', syndicat=self.ese.pk))
        self.local.refresh_from_db()
        self.assertEqual(self.local.nom, 'Local de Villeurbanne')

    def test_suppression_seulement_apres_confirmation(self):
        self.assertContains(self.client.get(f'{CARTE}{self.local.pk}/supprimer/'), 'Oui, supprimer')
        self.assertTrue(Implantation.objects.filter(pk=self.local.pk).exists())
        self.assertRedirects(self.client.post(f'{CARTE}{self.local.pk}/supprimer/'), CARTE)
        self.assertFalse(Implantation.objects.filter(pk=self.local.pk).exists())


class GroupeTest(TestCase):

    def setUp(self):
        _setup_editorial_groups()

    def test_groupe_cree_avec_sa_permission(self):
        groupe = Group.objects.get(name=GROUPE_CARTE)
        self.assertEqual(sorted(p.codename for p in groupe.permissions.all()),
                         ['acceder_carte_implantations', 'access_admin'])

    def _groupes_proposes(self, editeur, compte):
        form = SyndicatUserEditForm(instance=compte, request_user=editeur)
        return set(form.fields['groups'].queryset.values_list('name', flat=True))

    def test_seul_un_superuser_peut_donner_le_groupe(self):
        compte = make_redacteur(username='camille')
        self.assertNotIn(GROUPE_CARTE, self._groupes_proposes(make_chef(), compte))
        self.assertIn(GROUPE_CARTE, self._groupes_proposes(make_superuser(), compte))

    def test_un_chef_qui_edite_un_membre_ne_lui_retire_pas_la_carte(self):
        membre = membre_carte()
        chef = make_chef()
        data = {'username': membre.username, 'first_name': 'Sam', 'last_name': 'Membre',
                'email': 'sam@example.org', 'is_active': 'on'}
        form = SyndicatUserEditForm(data, instance=membre, request_user=chef)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(membre.groups.filter(name=GROUPE_CARTE).exists())

    def test_un_chef_ne_peut_pas_ajouter_le_groupe_en_forcant_le_formulaire(self):
        compte = make_redacteur(username='camille')
        data = {'username': 'camille', 'first_name': 'C', 'last_name': 'D', 'email': 'c@example.org',
                'is_active': 'on', 'groups': [Group.objects.get(name=GROUPE_CARTE).pk]}
        form = SyndicatUserEditForm(data, instance=compte, request_user=make_chef())
        self.assertFalse(form.is_valid())
        self.assertFalse(compte.groups.filter(name=GROUPE_CARTE).exists())

    @override_settings(DOUBLE_AUTH_OBLIGATOIRE='chefs')
    def test_double_auth_obligatoire_pour_le_groupe(self):
        self.assertFalse(double_auth.est_obligatoire(make_redacteur()))
        self.assertTrue(double_auth.est_obligatoire(membre_carte()))


class RegroupementTest(TestCase):

    def test_cle_et_libelle(self):
        self.assertEqual(cle('  Amazon   France '), 'amazon france')
        self.assertEqual(libelles(['amazon', 'Amazon', 'Amazon', '']), {'amazon': 'Amazon'})
