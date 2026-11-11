"""Étiquettes de catégorie : le secteur départage les homonymes (11/11/2026)."""
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from content.templatetags.categorie_tags import forme_reduite, libelle
from content.tests import make_article_page, make_cms_category, make_site


class FormeReduiteTest(TestCase):
    def test_variantes_dun_meme_nom(self):
        self.assertEqual(forme_reduite('Actualités - luttes'), 'actualite lutte')
        self.assertEqual(forme_reduite('Actualité et luttes'), 'actualite lutte')

    def test_les_annees_distinguent(self):
        self.assertNotEqual(forme_reduite('Élections TPE 2016'),
                            forme_reduite('Élections TPE 2021'))


class LibelleCategorieTest(TestCase):
    def setUp(self):
        self.btp = make_cms_category(name='BTP', slug='btp', section_slug='13')
        self.nett = make_cms_category(name='Nettoyage', slug='nettoyage', section_slug='13')
        self.actu_btp = make_cms_category(name='Actualités - luttes', slug='actu-btp',
                                          section_slug='13', parent=self.btp)
        self.actu_nett = make_cms_category(name='Actualité et luttes', slug='actu-nett',
                                           section_slug='13', parent=self.nett)

    def test_homonyme_prefixe_du_secteur(self):
        self.assertEqual(libelle(self.actu_btp), 'BTP › Actualités - luttes')
        self.assertEqual(libelle(self.actu_nett), 'Nettoyage › Actualité et luttes')

    def test_nom_unique_inchange_meme_avec_parent(self):
        """« Syndicalisme » ne doit pas coiffer 21 étiquettes de la conf."""
        synd = make_cms_category(name='Syndicalisme', slug='syndicalisme')
        greve = make_cms_category(name='Grève', slug='greve', parent=synd)
        self.assertEqual(libelle(greve), 'Grève')

    def test_homonyme_dun_autre_syndicat_ne_compte_pas(self):
        autre = make_cms_category(name='Actualités - luttes', slug='actu',
                                  section_slug='education', parent=self.btp)
        self.assertEqual(libelle(autre), 'Actualités - luttes')

    def test_reste_wordpress_nettoye(self):
        reste = make_cms_category(name='- CNT-Solidarité Ouvrière', slug='cnt-so',
                                  section_slug='13')
        make_cms_category(name='Vos droits', slug='vd1', section_slug='13', parent=reste)
        vd2 = make_cms_category(name='Vos droits', slug='vd2', section_slug='13',
                                parent=reste)
        self.assertEqual(libelle(vd2), 'CNT-Solidarité Ouvrière › Vos droits')

    def test_une_requete_par_syndicat_et_par_page(self):
        request = RequestFactory().get('/')
        gabarit = Template('{% load categorie_tags %}'
                           '{% libelle_categorie a %}|{% libelle_categorie b %}')
        libelle(self.actu_btp, request)  # mémo rempli
        a, b = (type(self.actu_btp).objects.select_related('parent')
                .get(pk=c.pk) for c in (self.actu_btp, self.actu_nett))
        with self.assertNumQueries(0):
            rendu = gabarit.render(Context({'a': a, 'b': b, 'request': request}))
        self.assertEqual(rendu, 'BTP › Actualités - luttes|Nettoyage › Actualité et luttes')


class EtiquettesSurLaPageTest(TestCase):
    """Rendu réel : l'étiquette d'une carte d'article porte le secteur."""

    def test_accueil_dun_syndicat(self):
        make_site()
        make_site('13', wp_blog_id=2, site_type='regional', name='Treize')
        btp = make_cms_category(name='BTP', slug='btp', section_slug='13')
        nett = make_cms_category(name='Nettoyage', slug='nettoyage', section_slug='13')
        actu = make_cms_category(name='Actualités - luttes', slug='actu-btp',
                                 section_slug='13', parent=btp)
        make_cms_category(name='Actualités - luttes', slug='actu-nett',
                          section_slug='13', parent=nett)
        make_article_page(section_slug='13', title='Grève au chantier', categories=[actu])
        html = self.client.get(
            reverse('content:site_home', kwargs={'site_slug': '13'})).content.decode()
        self.assertIn('Grève au chantier', html)
        self.assertIn('BTP › Actualités - luttes', html)
