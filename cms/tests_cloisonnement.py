"""Cloisonnement du back-office : personne ne travaille chez le voisin.

Ce fichier est le garde-fou du chantier. Wagtail ne passe le queryset d'un
SnippetViewSet qu'à la vue index : tous les autres écrans relisent l'objet par
sa clé primaire, et les actions en masse court-circuitent carrément les
viewsets. Les tests ci-dessous balaient **toutes** les URLs de **tous** les
snippets enregistrés, de sorte qu'un viewset ajouté demain sans déclaration de
cloisonnement fasse échouer la suite au lieu de rouvrir le trou en silence.
"""
from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from wagtail.snippets.models import get_snippet_models

from cms.cloisonnement import ViewSetCloisonne
from cms.models import Event, SectionPage
from content.models import (
    Author, Comment, ContactMessage, FormulaireContact, MenuItem,
    Newsletter, Subscriber,
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
