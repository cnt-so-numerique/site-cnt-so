"""Une seule orthographe par tag (Arnaud, 18/11/2026) — voir `cms/tags.py`."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from taggit.models import Tag, TaggedItem
from wagtail.images.tests.utils import Image, get_test_image_file

from cms.models import ArticlePage
from cms.tags import cle_tag, rapproche
from content.tests import _get_article_parent, make_article_page, make_cms_category


def _tague(titre, *noms, section='principal'):
    art = make_article_page(section_slug=section, title=titre)
    art.cms_tags.add(*noms)
    art.save()
    return art


def _noms(art):
    return sorted(ArticlePage.objects.get(pk=art.pk).cms_tags.names())


class CleTagTest(TestCase):

    def test_casse_accents_diese_espaces_et_tirets_ignores(self):
        for nom in ('grève', 'Grève', 'greve', 'grêve', '#grève', ' # GREVE '):
            self.assertEqual(cle_tag(nom), 'greve', nom)
        self.assertEqual(cle_tag('Extreme-droite'), cle_tag('extrême droite'))
        self.assertEqual(cle_tag('TPE 2024'), cle_tag('TPE2024'))
        self.assertNotEqual(cle_tag('grève'), cle_tag('grèves'))


class RapprocheTest(TestCase):

    def test_une_variante_rejoint_le_tag_existant(self):
        _tague('A', 'grève')
        self.assertEqual(rapproche(['Greve', '#grêve']), ['grève'])

    def test_un_mot_nouveau_reste_permis_sans_diese(self):
        _tague('A', 'grève')
        self.assertEqual(rapproche(['#Antifascisme', 'grève']), ['Antifascisme', 'grève'])

    def test_le_syndicat_retrouve_sa_variante(self):
        """Avant fusion, deux variantes cohabitent : chacun garde la sienne."""
        for i in range(3):
            _tague(f'Conf {i}', 'Education')
        _tague('Stucs', 'éducation', section='stucs')
        self.assertEqual(rapproche(['EDUCATION']), ['Education'])
        self.assertEqual(rapproche(['EDUCATION'], 'stucs'), ['éducation'])


class FormulaireArticleTest(TestCase):
    """La saisie dans /cms/ passe par `ArticlePageForm.clean_cms_tags`."""

    def test_la_redaction_ne_cree_pas_de_variante(self):
        _tague('Ancien', 'grève')
        cat = make_cms_category(name='Luttes', slug='luttes')
        classe = ArticlePage.get_edit_handler().get_form_class()
        form = classe(data={
            'title': 'Nouveau', 'slug': 'nouveau', 'body-count': '0',
            'cms_categories': [cat.pk], 'cms_tags': '#Grêve, Précarité',
        }, instance=ArticlePage(), parent_page=_get_article_parent())
        self.assertTrue(form.is_valid(), form.errors)
        page = form.save(commit=False)
        _get_article_parent().add_child(instance=page)
        self.assertEqual(_noms(page), ['Précarité', 'grève'])
        self.assertEqual(Tag.objects.filter(name__icontains='gr').count(), 1)


class FusionneTagsTest(TestCase):

    def _lance(self, *args):
        sortie = StringIO()
        call_command('fusionne_tags', *args, stdout=sortie)
        return sortie.getvalue()

    def test_les_variantes_sont_fusionnees_sur_la_plus_employee(self):
        a = _tague('A', 'grève')
        b = _tague('B', 'grève', 'grêve')   # porte déjà le tag gardé
        c = _tague('C', '#grève')
        image = Image.objects.create(title='affiche', file=get_test_image_file())
        image.tags.add('grêve')

        self._lance()
        self.assertEqual(list(Tag.objects.values_list('name', flat=True)), ['grève'])
        for art in (a, b, c):
            self.assertEqual(_noms(art), ['grève'])
        self.assertEqual(list(Image.objects.get(pk=image.pk).tags.names()), ['grève'])
        self.assertEqual(TaggedItem.objects.count(), 1)

    def test_les_revisions_suivent(self):
        art = _tague('A', 'grève', 'grêve')
        _tague('B', 'grève')
        art.save_revision()
        self._lance()
        garde = Tag.objects.get(name='grève')
        liens = ArticlePage.objects.get(pk=art.pk).latest_revision.content['tagged_items']
        self.assertEqual([l['tag'] for l in liens], [garde.pk])
        # Le brouillon se rouvre et se republie sans erreur.
        ArticlePage.objects.get(pk=art.pk).latest_revision.as_object().save_revision().publish()

    def test_garde_choisit_l_orthographe_et_le_diese_tombe(self):
        for i in range(3):
            _tague(f'E{i}', 'Education')
        _tague('e', 'éducation')
        _tague('t', '#Travail')
        self._lance('--garde', 'éducation')
        self.assertEqual(sorted(Tag.objects.values_list('name', flat=True)),
                         ['Travail', 'éducation'])

    def test_simulation_n_ecrit_rien(self):
        _tague('A', 'grève', 'grêve', '#Travail')
        sortie = self._lance('--dry-run')
        self.assertIn('« grêve »', sortie)
        self.assertEqual(Tag.objects.count(), 3)
