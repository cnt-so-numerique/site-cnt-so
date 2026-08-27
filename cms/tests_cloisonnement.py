"""Cloisonnement du back-office : personne ne travaille chez le voisin.

Ce fichier est le garde-fou du chantier. Wagtail ne passe le queryset d'un
SnippetViewSet qu'à la vue index : tous les autres écrans relisent l'objet par
sa clé primaire, et les actions en masse court-circuitent carrément les
viewsets. Les tests ci-dessous balaient **toutes** les URLs de **tous** les
snippets enregistrés, de sorte qu'un viewset ajouté demain sans déclaration de
cloisonnement fasse échouer la suite au lieu de rouvrir le trou en silence.
"""
from datetime import date

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse

from wagtail.snippets.models import get_snippet_models

from cms.cloisonnement import ViewSetCloisonne
from cms.models import ArticlePage, Event, SectionPage
from content.models import (
    Author, Comment, ContactMessage, FicheSyndicat, FormulaireContact,
    MenuItem, Newsletter, Permanence, Subscriber,
)
from content.tests import (
    _ensure_section_page, make_article, make_article_page,
    make_cms_category, make_content_page,
)


# ── Fabriques : un objet par modèle de snippet, rattaché à un syndicat ────────
#
# Toute entrée manquante fait échouer `test_tout_snippet_a_une_fabrique` : c'est
# volontaire, c'est ce qui empêche d'ajouter un snippet sans le cloisonner.

def _article(section):
    return make_article_page(section_slug=section.slug,
                             title=f'Article {section.slug}',
                             slug=f'article-{section.slug}')


def _page(section):
    return make_content_page(section_slug=section.slug,
                             title=f'Page {section.slug}',
                             slug=f'page-{section.slug}')


def _categorie(section):
    return make_cms_category(name=f'Cat {section.slug}',
                             slug=f'cat-{section.slug}',
                             section_slug=section.slug)


def _evenement(section):
    return Event.objects.create(section=section, title=f'AG {section.slug}',
                                date=date(2026, 9, 1))


def _commentaire(section):
    article = make_article(section, title=f'Legacy {section.slug}',
                           slug=f'legacy-{section.slug}')
    return Comment.objects.create(article=article, author_name='Camarade',
                                  content='Bien vu.')


FABRIQUES = {
    'cms.ArticlePage': _article,
    'cms.ContentPage': _page,
    'cms.CmsCategory': _categorie,
    'cms.Event': _evenement,
    'cms.SectionPage': lambda section: section,
    'content.Comment': _commentaire,
    'content.ContactMessage': lambda s: ContactMessage.objects.create(
        site=s, name='Camarade', email='c@ex.org'),
    'content.FormulaireContact': lambda s: FormulaireContact.objects.create(site=s),
    'content.Newsletter': lambda s: Newsletter.objects.create(
        site=s, title=f'NL {s.slug}', intro='.'),
    'content.Subscriber': lambda s: Subscriber.objects.create(
        site=s, email=f'abo-{s.slug}@ex.org'),
    'content.MenuItem': lambda s: MenuItem.objects.create(
        site=s, title=f'Lien {s.slug}'),
    'content.Author': lambda s: Author.objects.create(
        site=s, username=f'auteur-{s.slug}'),
    'content.Permanence': lambda s: Permanence.objects.create(
        site=s, ville=f'Permanence {s.slug}', adresse='1 rue du Travail'),
    'content.FicheSyndicat': lambda s: FicheSyndicat.objects.create(
        site=s, titre=f'Fiche {s.slug}', url='/categorie/nettoyage/'),
}

# Paramètres d'URL autres que `pk` : on vise volontairement des identifiants
# inexistants — le refus doit venir du cloisonnement, pas d'eux.
AUTRES_PARAMS = {
    'revision_id': 999999,
    'task_state_id': 999999,
    'workflow_state_id': 999999,
    'task_id': 999999,
    'action_name': 'approve',
    'revision_id_a': 'live',
    'revision_id_b': 'latest',
}


class CloisonnementBackOfficeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.mien = _ensure_section_page(slug='cloison-a', name='Syndicat A')
        cls.voisin = _ensure_section_page(slug='cloison-b', name='Syndicat B')
        cls.objets = {
            label: {'mien': fabrique(cls.mien), 'voisin': fabrique(cls.voisin)}
            for label, fabrique in FABRIQUES.items()
        }

    def setUp(self):
        from django.contrib.auth.models import Group
        groupe, _ = Group.objects.get_or_create(name='redacteur_cloison-a')
        self.redacteur = User.objects.create_user('redac-cloison', password='pass')
        self.redacteur.groups.add(groupe)
        # TOUTES les permissions de modèle : sans ça un 403 masquerait un 404
        # manquant et le test ne prouverait plus rien.
        self.redacteur.user_permissions.set(Permission.objects.all())
        self.redacteur = User.objects.get(pk=self.redacteur.pk)
        self.client.force_login(self.redacteur)

    # ── Verrous structurels ──────────────────────────────────────────────────

    def test_tout_snippet_a_une_fabrique(self):
        manquants = sorted(m._meta.label for m in get_snippet_models()
                           if m._meta.label not in FABRIQUES)
        self.assertEqual(
            manquants, [],
            "snippet(s) sans fabrique dans ce fichier — ajoutez-la pour que le "
            "balayage de cloisonnement les couvre")

    def test_tout_viewset_declare_son_cloisonnement(self):
        nus = sorted(m._meta.label for m in get_snippet_models()
                     if not isinstance(m.snippet_viewset, ViewSetCloisonne))
        self.assertEqual(
            nus, [],
            "viewset(s) sans ViewSetCloisonne : leurs écrans seraient ouverts "
            "aux rédacteurs des autres syndicats")

    # ── Balayage des écrans qui lisent par clé primaire ──────────────────────

    def _urls_a_pk(self, viewset, objet):
        """(nom, url) pour chaque route du viewset paramétrée par `pk`."""
        for motif in viewset.get_urlpatterns():
            params = motif.pattern.regex.groupindex
            if 'pk' not in params:
                continue
            kwargs = {'pk': objet.pk}
            kwargs.update({p: AUTRES_PARAMS[p] for p in params
                           if p != 'pk' and p in AUTRES_PARAMS})
            if len(kwargs) != len(params):
                continue  # paramètre inconnu : on ne sait pas fabriquer l'URL
            yield motif.name, reverse(viewset.get_url_name(motif.name), kwargs=kwargs)

    def test_les_ecrans_refusent_un_objet_du_voisin(self):
        vus = 0
        for modele in get_snippet_models():
            viewset = modele.snippet_viewset
            voisin = self.objets[modele._meta.label]['voisin']
            for nom, url in self._urls_a_pk(viewset, voisin):
                vus += 1
                with self.subTest(modele=modele._meta.label, ecran=nom):
                    self.assertEqual(
                        self.client.get(url).status_code, 404,
                        f"{url} sert un objet du syndicat voisin")
        # Sans cette garde, un balayage qui ne trouverait aucune URL passerait.
        self.assertGreater(vus, 50, f"balayage trop maigre pour conclure : {vus} URLs")

    def test_les_ecrans_servent_bien_ses_propres_objets(self):
        """Contrôle positif : sans lui, une URL cassée passerait pour sûre."""
        vus = 0
        for modele in get_snippet_models():
            viewset = modele.snippet_viewset
            mien = self.objets[modele._meta.label]['mien']
            for motif in viewset.get_urlpatterns():
                params = motif.pattern.regex.groupindex
                if sorted(params) != ['pk']:
                    continue  # les URLs à révision/workflow visent des ids faux
                url = reverse(viewset.get_url_name(motif.name), kwargs={'pk': mien.pk})
                vus += 1
                with self.subTest(modele=modele._meta.label, ecran=motif.name):
                    self.assertNotEqual(
                        self.client.get(url).status_code, 404,
                        f"{url} refuse un objet de SON propre syndicat")
        self.assertGreater(vus, 50, f"balayage trop maigre pour conclure : {vus} URLs")

    # ── Écriture : impossible de créer chez le voisin ────────────────────────

    def test_le_champ_syndicat_est_borne_dans_le_formulaire(self):
        """Le cloisonnement en lecture n'empêche pas de CRÉER chez le voisin :
        le champ de rattachement doit être borné à son propre syndicat."""
        vus = 0
        for modele in get_snippet_models():
            viewset = modele.snippet_viewset
            champ = viewset.champ_syndicat()
            if champ is None:
                continue
            url = reverse(viewset.get_url_name('add'))
            reponse = self.client.get(url)
            if reponse.status_code != 200:
                continue
            form = reponse.context['form']
            if champ not in form.fields:
                continue
            vus += 1
            with self.subTest(modele=modele._meta.label, champ=champ):
                f = form.fields[champ]
                choix = getattr(f, 'queryset', None)
                if choix is not None:
                    interdits = [o for o in choix
                                 if self._appartient_au_voisin(o)]
                    self.assertEqual(
                        interdits, [],
                        f"le champ « {champ} » propose du contenu du voisin")
                else:
                    from django import forms as dforms
                    self.assertIsInstance(
                        f.widget, dforms.HiddenInput,
                        f"le champ « {champ} » reste libre à la saisie")
        self.assertGreater(vus, 5, f"trop peu de formulaires examinés : {vus}")

    def _appartient_au_voisin(self, objet):
        if isinstance(objet, SectionPage):
            return objet.pk == self.voisin.pk
        return getattr(objet, 'site_id', None) == self.voisin.pk

    def _newsletter_postee(self, site_pk, titre):
        return self.client.post(
            reverse(Newsletter.snippet_viewset.get_url_name('add')), {
                'site': site_pk, 'title': titre, 'intro': '.', 'status': 'draft',
                # Le sommaire est passé de « une ligne par article » à
                # « une rubrique, et ses articles dessous » (18/08/2026).
                'rubriques-TOTAL_FORMS': '0',
                'rubriques-INITIAL_FORMS': '0',
                'rubriques-MIN_NUM_FORMS': '0',
                'rubriques-MAX_NUM_FORMS': '1000',
            })

    def test_creer_pour_son_propre_syndicat_fonctionne(self):
        """Contrôle positif : le verrou ne doit pas bloquer le travail normal."""
        self._newsletter_postee(self.mien.pk, 'Ma newsletter')
        creee = Newsletter.objects.filter(title='Ma newsletter').first()
        self.assertIsNotNone(creee, "un rédacteur doit pouvoir créer chez lui")
        self.assertEqual(creee.site_id, self.mien.pk)

    def test_creer_en_forgeant_le_syndicat_du_voisin_est_refuse(self):
        """Le champ est masqué, donc forgeable dans le POST : la borne du
        queryset le rejette à la validation plutôt que de le réattribuer."""
        r = self._newsletter_postee(self.voisin.pk, 'Newsletter forgée')
        self.assertFalse(
            Newsletter.objects.filter(title='Newsletter forgée').exists(),
            "une newsletter a été créée avec le syndicat forgé")
        self.assertIn('site', r.context['form'].errors)

    def test_un_evenement_ne_peut_pas_etre_pose_dans_l_agenda_du_voisin(self):
        self.client.post(reverse(Event.snippet_viewset.get_url_name('add')), {
            'section': self.voisin.pk, 'title': 'AG forgée', 'date': '2026-09-15',
        })
        self.assertFalse(
            Event.objects.filter(title='AG forgée').exists(),
            "un événement a été posé dans l'agenda du voisin")

    def test_un_slug_de_syndicat_forge_est_reecrit_par_le_serveur(self):
        """Les rattachements par slug sont de simples chaînes : aucune borne de
        queryset ne les protège, seule la réécriture serveur le fait."""
        from cms.models import CmsCategory
        self.client.post(
            reverse(CmsCategory.snippet_viewset.get_url_name('add')),
            {'name': 'Catégorie forgée', 'slug': 'categorie-forgee',
             'section_slug': self.voisin.slug})
        creee = CmsCategory.objects.filter(slug='categorie-forgee').first()
        self.assertIsNotNone(creee, "la catégorie aurait dû être créée")
        self.assertEqual(creee.section_slug, self.mien.slug,
                         "le slug de syndicat forgé dans le POST a été accepté")

    # ── Autonomie réelle : suppression bornée au syndicat ────────────────────

    def _redacteur_aux_droits_reels(self):
        """Un compte n'ayant que les permissions de son groupe de syndicat —
        les tests ci-dessus donnent TOUT pour isoler le cloisonnement, celui-ci
        vérifie que les droits réellement accordés suffisent."""
        from django.contrib.auth.models import Group
        from django.core.management import call_command
        call_command('setup_cms_permissions', verbosity=0)
        u = User.objects.create_user('redac-droits-reels', password='pass')
        u.groups.add(Group.objects.get(name=f'redacteur_{self.mien.slug}'))
        client = self.client_class()
        client.force_login(User.objects.get(pk=u.pk))
        return client

    def test_un_redacteur_supprime_le_contenu_de_son_syndicat(self):
        client = self._redacteur_aux_droits_reels()
        mien = self.objets['cms.ArticlePage']['mien']
        url = reverse(
            ArticlePage.snippet_viewset.get_url_name('delete'), kwargs={'pk': mien.pk})
        self.assertEqual(client.get(url).status_code, 200,
                         "un rédacteur doit pouvoir supprimer chez lui")
        client.post(url)
        self.assertFalse(ArticlePage.objects.filter(pk=mien.pk).exists(),
                         "la suppression n'a pas abouti")

    def test_mais_pas_celui_du_voisin(self):
        client = self._redacteur_aux_droits_reels()
        voisin = self.objets['cms.ArticlePage']['voisin']
        url = reverse(
            ArticlePage.snippet_viewset.get_url_name('delete'), kwargs={'pk': voisin.pk})
        self.assertEqual(client.get(url).status_code, 404)
        client.post(url)
        self.assertTrue(ArticlePage.objects.filter(pk=voisin.pk).exists(),
                        "l'article du voisin a été supprimé")

    # ── Sélecteurs de contenu ────────────────────────────────────────────────

    def test_les_selecteurs_ne_montrent_pas_le_contenu_du_voisin(self):
        """Le sélecteur est un viewset distinct : le cloisonnement des écrans
        d'édition ne l'atteint pas. Sans lui, un rédacteur met l'article d'un
        autre syndicat dans sa newsletter."""
        from cms.cloisonnement import SelecteurCloisonne
        vus = 0
        for modele in get_snippet_models():
            if not isinstance(modele.snippet_viewset.chooser_viewset,
                              SelecteurCloisonne):
                continue
            voisin = self.objets[modele._meta.label]['voisin']
            mien = self.objets[modele._meta.label]['mien']
            base = modele.snippet_viewset.chooser_viewset.get_url_name('choose')
            r = self.client.get(reverse(base))
            if r.status_code != 200:
                continue
            vus += 1
            with self.subTest(modele=modele._meta.label):
                proposes = {o.pk for o in r.context['results']}
                self.assertNotIn(voisin.pk, proposes,
                                 "le sélecteur propose le contenu du voisin")
                self.assertIn(mien.pk, proposes,
                              "le sélecteur cache son propre contenu")
        self.assertGreater(vus, 3, f"trop peu de sélecteurs examinés : {vus}")

    def test_le_selecteur_de_syndicats_reste_ouvert(self):
        """Exception assumée : MenuItem.target_site sert justement à pointer
        vers les autres syndicats."""
        from cms.cloisonnement import SelecteurCloisonne
        self.assertNotIsInstance(
            SectionPage.snippet_viewset.chooser_viewset, SelecteurCloisonne,
            "cloisonner ce sélecteur casserait les liens inter-syndicats")

    # ── Actions en masse ─────────────────────────────────────────────────────

    def _url_suppression_en_masse(self, modele):
        return reverse('wagtail_bulk_action',
                       args=[modele._meta.app_label, modele._meta.model_name, 'delete'])

    def test_notre_suppression_en_masse_gagne_dans_le_registre(self):
        from wagtail.admin.views.bulk_action.registry import bulk_action_registry
        from cms.wagtail_hooks import SuppressionEnMasseCloisonnee
        for modele in get_snippet_models():
            with self.subTest(modele=modele._meta.label):
                self.assertIs(
                    bulk_action_registry.get_bulk_action_class(
                        modele._meta.app_label, modele._meta.model_name, 'delete'),
                    SuppressionEnMasseCloisonnee)

    def test_la_suppression_en_masse_ne_touche_pas_les_objets_du_voisin(self):
        for modele in get_snippet_models():
            voisin = self.objets[modele._meta.label]['voisin']
            url = self._url_suppression_en_masse(modele)
            with self.subTest(modele=modele._meta.label):
                self.client.post(f'{url}?id={voisin.pk}')
                self.assertTrue(
                    modele._default_manager.filter(pk=voisin.pk).exists(),
                    f"{modele._meta.label} du voisin détruit par la suppression en masse")

    def test_tout_selectionner_reste_borne_a_son_syndicat(self):
        """« id=all » se résolvait en model.objects.all() : un seul POST sur
        /cms/bulk/content/subscriber/delete/?id=all effaçait les abonnés de
        tous les syndicats."""
        for modele in get_snippet_models():
            voisin = self.objets[modele._meta.label]['voisin']
            url = self._url_suppression_en_masse(modele)
            with self.subTest(modele=modele._meta.label):
                self.client.post(f'{url}?id=all')
                self.assertTrue(
                    modele._default_manager.filter(pk=voisin.pk).exists(),
                    f"{modele._meta.label} du voisin détruit par « tout sélectionner »")


class PagesDuSyndicatCloisonneTest(TestCase):
    """L'écran « Pages du syndicat » part du syndicat courant, pas de la session.

    Il a été ajouté le 18/08/2026 sans test de cloisonnement : c'est le seul
    écran de ce fichier à ne pas passer par un SnippetViewSet, donc le seul que
    le balayage ne couvre pas. Or il expose des liens d'édition — la fiche du
    syndicat, la configuration du formulaire de contact — et il choisit sa
    cible lui-même.

    Le garde-fou est dans `get_current_site` : pour un rédacteur rattaché à un
    groupe de syndicat, il renvoie SON syndicat et ignore la session. Ce test
    le prouve en forgeant une session pointant sur le voisin.
    """

    def setUp(self):
        from django.contrib.auth.models import Group
        self.mien = _ensure_section_page(slug='pages-a', name='Syndicat Pages A')
        self.voisin = _ensure_section_page(slug='pages-b', name='Syndicat Pages B')
        groupe, _ = Group.objects.get_or_create(name='redacteur_pages-a')
        redacteur = User.objects.create_user('redac-pages', password='pass')
        redacteur.groups.add(groupe)
        redacteur.user_permissions.set(Permission.objects.all())
        self.client.force_login(User.objects.get(pk=redacteur.pk))

    def _page(self):
        return self.client.get('/cms/pages-du-syndicat/')

    def test_le_redacteur_voit_son_syndicat(self):
        r = self._page()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.mien.title)

    def test_une_session_forgee_ne_lui_ouvre_pas_le_voisin(self):
        session = self.client.session
        session['cms_current_site_id'] = self.voisin.pk
        session.save()
        r = self._page()
        self.assertContains(r, self.mien.title)
        self.assertNotContains(r, self.voisin.title)
        self.assertNotContains(
            r, f'/cms/snippets/cms/sectionpage/edit/{self.voisin.pk}/',
            msg_prefix="lien d'édition vers la fiche du voisin")

    def test_un_visiteur_non_connecte_est_ecarte(self):
        self.client.logout()
        r = self._page()
        self.assertIn(r.status_code, (302, 403))


class ApiAdminPagesCloisonneeTest(TestCase):
    """L'API interne de Wagtail échappait au balayage de ce fichier.

    Tout ce qui précède porte sur les SnippetViewSets, parce que le
    cloisonnement est posé dans `ViewSet.construct_view`. Or Wagtail monte
    aussi `/cms/api/main/pages/`, qui ne passe par aucun viewset.

    Reproduit le 26/08/2026 sous Wagtail 7.4.2, avec les seules permissions
    que `setup_cms_permissions` accorde à un rédacteur — donc des droits
    d'arbre bornés à son syndicat :

        listing → 200, toutes les pages de tous les syndicats
        page du voisin par sa clé → 200, contenu complet

    C'est `CVE-2026-55468` : « l'API Pages interne renvoie des champs de page
    sans contrôle d'accès ». Corrigé par la 7.4.3, où le listing se limite au
    périmètre du compte et l'accès direct rend un 404.

    Ce test existe pour que la fuite ne revienne pas par une rétrogradation de
    version ou une régression amont — c'est le seul écran du back-office que
    rien d'autre ne surveille.
    """

    def setUp(self):
        from django.core.management import call_command
        from io import StringIO
        self.mien = _ensure_section_page(slug='api-a', name='Syndicat API A')
        self.voisin = _ensure_section_page(slug='api-b', name='Syndicat API B')
        self.chez_moi = make_article_page(section_slug='api-a', title='Chez moi',
                                          slug='api-chez-moi')
        self.chez_le_voisin = make_article_page(
            section_slug='api-b', title='Secret du voisin', slug='api-secret')
        call_command('setup_cms_permissions', verbosity=0, stdout=StringIO())
        redacteur = User.objects.create_user('redac-api', password='pass')
        redacteur.groups.add(Group.objects.get(name='redacteur_api-a'))
        self.client.force_login(User.objects.get(pk=redacteur.pk))

    def _titres_du_listing(self):
        import json
        reponse = self.client.get('/cms/api/main/pages/')
        self.assertEqual(reponse.status_code, 200)
        return [item['title'] for item in json.loads(reponse.content)['items']]

    def test_le_listing_ne_montre_pas_le_syndicat_voisin(self):
        titres = self._titres_du_listing()
        self.assertNotIn('Syndicat API B', titres)
        self.assertNotIn('Secret du voisin', titres)

    def test_la_page_du_voisin_nest_pas_lisible_par_sa_cle(self):
        reponse = self.client.get(f'/cms/api/main/pages/{self.chez_le_voisin.pk}/')
        self.assertEqual(
            reponse.status_code, 404,
            "l'API interne sert la page d'un autre syndicat — vérifier la "
            "version de Wagtail (CVE-2026-55468, corrigée en 7.4.3)")


class VersionDeWagtailSansFailleConnueTest(TestCase):
    """Wagtail 7.4.2 laissait un rédacteur lire les pages du voisin.

    Le test ci-dessus attrape la fuite elle-même ; celui-ci dit pourquoi, pour
    que personne ne rétrograde sans comprendre ce qu'il rouvre.
    """

    def test_la_version_installee_corrige_la_fuite_de_lapi(self):
        import wagtail
        version = tuple(int(n) for n in wagtail.__version__.split('.')[:3])
        self.assertGreaterEqual(
            version, (7, 4, 3),
            f"Wagtail {wagtail.__version__} : l'API interne /cms/api/main/pages/ "
            "renvoie les pages de tous les syndicats (CVE-2026-55468).")


class BalayageInterfaceInterneTest(TestCase):
    """Parcourt TOUTE l'interface /cms/, pas seulement les snippets.

    Le reste de ce fichier balaie les SnippetViewSets. Restaient hors champ les
    écrans propres à Wagtail — explorateur de pages, images, documents, comptes,
    groupes, collections — et les écrans maison. Soit environ 200 URL qu'aucun
    test n'ouvrait, dans l'interface où quatorze syndicats travaillent côte à
    côte.

    Balayage du 27/08/2026 : aucune erreur serveur, et le périmètre d'un
    rédacteur est bien borné. Ce test fige les deux.
    """

    #: L'URL de test d'erreur de Wagtail, qui lève une exception exprès.
    IGNOREES = ('/cms/failwhale/',)

    def setUp(self):
        from django.core.management import call_command
        from io import StringIO
        self.mien = _ensure_section_page(slug='balayage-a', name='Syndicat Balayage A')
        self.voisin = _ensure_section_page(slug='balayage-b', name='Syndicat Balayage B')
        self.chez_le_voisin = make_article_page(
            section_slug='balayage-b', title='Article du voisin',
            slug='balayage-voisin')
        make_article_page(section_slug='balayage-a', title='Le mien',
                          slug='balayage-mien')
        call_command('setup_cms_permissions', verbosity=0, stdout=StringIO())
        self.redacteur = User.objects.create_user('balayage-redac', password='pass')
        self.redacteur.groups.add(Group.objects.get(name='redacteur_balayage-a'))
        self.client.force_login(User.objects.get(pk=self.redacteur.pk))

    def _urls_sans_argument(self):
        """Les URL d'administration qu'on peut ouvrir sans clé primaire."""
        from django.urls import get_resolver
        trouvees = []

        def marche(motifs, prefixe=''):
            for m in motifs:
                if hasattr(m, 'url_patterns'):
                    marche(m.url_patterns, prefixe + str(m.pattern))
                else:
                    chemin = prefixe + str(m.pattern)
                    if (chemin.startswith('cms/') and '<' not in chemin
                            and '(?P' not in chemin and '^' not in chemin
                            and not chemin.endswith('$')):
                        trouvees.append('/' + chemin)

        marche(get_resolver().url_patterns)
        return sorted(set(trouvees) - set(self.IGNOREES))

    def test_aucun_ecran_ne_rend_une_erreur_serveur(self):
        """Un 500 dans /cms/ arrête net le travail d'un syndicat."""
        casses = []
        for url in self._urls_sans_argument():
            try:
                code = self.client.get(url).status_code
            except Exception as e:
                casses.append(f'{url} → {type(e).__name__}: {e}')
                continue
            if code >= 500:
                casses.append(f'{url} → {code}')
        self.assertEqual(casses, [], f"écran(s) en erreur : {casses}")

    def test_les_ecrans_reserves_restent_fermes(self):
        """Un rédacteur n'administre ni les comptes, ni les groupes, ni les
        syndicats. Le refus sort en 302 vers /cms/ et non en 403 : une
        `PermissionDenied` levée dans une vue de `register_admin_urls` est
        convertie en redirection par Wagtail."""
        for url in ('/cms/syndicats/', '/cms/users/', '/cms/groups/',
                    '/cms/collections/', '/cms/workflows/list/'):
            with self.subTest(url=url):
                code = self.client.get(url, follow=False).status_code
                self.assertNotEqual(code, 200, f"{url} est ouvert au rédacteur")

    def test_les_pages_du_voisin_restent_hors_datteinte(self):
        """L'explorateur de Wagtail ne passe par aucun viewset : le
        cloisonnement des snippets ne l'atteint pas."""
        pk = self.chez_le_voisin.pk
        for chemin in (f'/cms/pages/{pk}/', f'/cms/pages/{pk}/edit/',
                       f'/cms/pages/{pk}/delete/'):
            with self.subTest(chemin=chemin):
                self.assertNotEqual(
                    self.client.get(chemin, follow=False).status_code, 200,
                    f"{chemin} est ouvert au rédacteur du syndicat voisin")

    def test_la_bibliotheque_dimages_est_bornee_a_sa_collection(self):
        """Les collections de médias sont provisionnées par syndicat : la
        bibliothèque ne doit montrer que la sienne."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wagtail.images.models import Image
        from wagtail.models import Collection
        png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00'
               b'\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\n'
               b'IDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00'
               b'\x00IEND\xaeB`\x82')
        collection = (Collection.objects.filter(name=self.voisin.title).first()
                      or Collection.get_first_root_node())
        chez_le_voisin = Image.objects.create(
            title='Photo du voisin', collection=collection,
            file=SimpleUploadedFile('voisin.png', png, 'image/png'))

        listing = self.client.get('/cms/images/')
        self.assertNotContains(listing, 'Photo du voisin')
        self.assertNotEqual(
            self.client.get(f'/cms/images/{chez_le_voisin.pk}/',
                            follow=False).status_code, 200,
            "l'image du syndicat voisin est modifiable")
