"""Vidéos Facebook dans le bloc « Vidéo / iFrame » (cms/embeds.py).

Aucun test ne touche le réseau : les liens complets n'en ont pas besoin, et
le dépliage des liens courts passe par un `requests.get` simulé.
"""
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import requests
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from wagtail.embeds.blocks import EmbedBlock, EmbedValue
from wagtail.embeds.exceptions import EmbedNotFoundException
from wagtail.embeds.finders import get_finders

from cms.embeds import FacebookVideoFinder, lien_canonique
from content.tests import make_article_page, make_site

WATCH = 'https://www.facebook.com/watch/?v=10153231379946729'


def href_du_lecteur(html):
    """Le lien de vidéo passé au lecteur Facebook, décodé."""
    src = html.split('src="', 1)[1].split('"', 1)[0].replace('&amp;', '&')
    morceaux = urlsplit(src)
    assert morceaux.netloc == 'www.facebook.com', src
    assert morceaux.path == '/plugins/video.php', src
    return parse_qs(morceaux.query)['href'][0]


class LiensReconnusTests(TestCase):
    def test_les_formes_completes_donnent_la_meme_video(self):
        for url in [
            'https://www.facebook.com/cntso/videos/10153231379946729/',
            'https://www.facebook.com/cntso/videos/manif-du-1er-mai/10153231379946729',
            'https://m.facebook.com/cntso/videos/10153231379946729/?mibextid=abc',
            'https://web.facebook.com/watch/?v=10153231379946729&ref=sharing',
            'https://www.facebook.com/watch?v=10153231379946729',
            'https://facebook.com/video.php?v=10153231379946729',
            'http://www.facebook.com/video.php?id=10153231379946729',
        ]:
            with self.subTest(url=url):
                self.assertEqual(lien_canonique(url), (WATCH, False))

    def test_un_reel_est_vertical(self):
        self.assertEqual(
            lien_canonique('https://www.facebook.com/reel/10153231379946729/?s=fb'),
            (WATCH, True))

    def test_ce_qui_n_est_pas_une_video_facebook_est_laisse_aux_autres(self):
        finder = FacebookVideoFinder()
        for url in [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://www.facebook.com/cntso',
            'https://www.facebook.com/cntso/posts/123',
            'https://www.facebook.com/watch/?v=abc',
            'https://facebook.com.exemple.org/x/videos/123/',
            'https://exemple.org/?u=https://www.facebook.com/watch/?v=1',
            'javascript://www.facebook.com/watch/?v=1',
        ]:
            with self.subTest(url=url):
                self.assertFalse(finder.accept(url))

    def test_les_liens_courts_sont_acceptes(self):
        finder = FacebookVideoFinder()
        for url in ['https://fb.watch/qWeRtY12/',
                    'https://www.facebook.com/share/v/1AbCdEfGh/',
                    'https://www.facebook.com/share/r/1AbCdEfGh/']:
            with self.subTest(url=url):
                self.assertTrue(finder.accept(url))

    def test_le_reglage_place_facebook_avant_oembed(self):
        finders = get_finders()
        self.assertIsInstance(finders[0], FacebookVideoFinder)
        self.assertTrue(any(f.accept('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
                            for f in finders[1:]))


class LecteurTests(TestCase):
    def test_iframe_du_lecteur_sans_cle(self):
        embed = FacebookVideoFinder().find_embed(
            'https://www.facebook.com/cntso/videos/10153231379946729/')
        self.assertEqual(href_du_lecteur(embed['html']), WATCH)
        self.assertIn('title="Vidéo Facebook"', embed['html'])
        self.assertIn('allowfullscreen', embed['html'])
        self.assertNotIn('<script', embed['html'])
        self.assertEqual((embed['width'], embed['height']), (560, 314))
        self.assertEqual(embed['provider_name'], 'Facebook')

    def test_reel_en_format_vertical(self):
        embed = FacebookVideoFinder().find_embed(
            'https://www.facebook.com/reel/10153231379946729')
        self.assertLess(embed['width'], embed['height'])

    def test_le_lien_saisi_ne_sort_pas_de_l_attribut(self):
        # Seuls les chiffres de l'identifiant passent : le reste du lien est jeté.
        embed = FacebookVideoFinder().find_embed(
            'https://www.facebook.com/x/videos/123/?a="><script>alert(1)</script>')
        self.assertNotIn('<script', embed['html'])
        self.assertEqual(href_du_lecteur(embed['html']),
                         'https://www.facebook.com/watch/?v=123')


def reponse(url, location='', history=()):
    r = mock.Mock(url=url, headers={'Location': location} if location else {})
    r.history = list(history)
    return r


class LiensCourtsTests(TestCase):
    @mock.patch('cms.embeds.requests.get')
    def test_redirection_vers_la_video(self, get):
        get.return_value = reponse(
            'https://www.facebook.com/cntso/videos/10153231379946729/',
            history=[reponse('https://fb.watch/qWeRtY12/',
                             'https://www.facebook.com/cntso/videos/10153231379946729/')])
        embed = FacebookVideoFinder().find_embed('https://fb.watch/qWeRtY12/')
        self.assertEqual(href_du_lecteur(embed['html']), WATCH)

    @mock.patch('cms.embeds.requests.get')
    def test_redirection_vers_la_connexion(self, get):
        get.return_value = reponse(
            'https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com'
            '%2Freel%2F10153231379946729%2F')
        embed = FacebookVideoFinder().find_embed(
            'https://www.facebook.com/share/r/1AbCdEfGh/')
        self.assertEqual(href_du_lecteur(embed['html']), WATCH)
        self.assertLess(embed['width'], embed['height'])

    @mock.patch('cms.embeds.requests.get')
    def test_lien_court_sans_video_refuse(self, get):
        get.return_value = reponse('https://www.facebook.com/')
        with self.assertRaises(EmbedNotFoundException):
            FacebookVideoFinder().find_embed('https://fb.watch/qWeRtY12/')

    @mock.patch('cms.embeds.requests.get',
                side_effect=requests.ConnectionError('hors ligne'))
    def test_facebook_injoignable_refuse(self, get):
        with self.assertRaises(EmbedNotFoundException):
            FacebookVideoFinder().find_embed('https://fb.watch/qWeRtY12/')


class ArticleAvecVideoFacebookTests(TestCase):
    def test_le_bloc_video_accepte_le_lien(self):
        valeur = EmbedValue('https://www.facebook.com/cntso/videos/10153231379946729/')
        EmbedBlock().clean(valeur)  # ne lève pas « Cannot find an embed »

    @mock.patch('cms.embeds.requests.get', return_value=reponse('https://www.facebook.com/'))
    def test_le_bloc_video_refuse_un_lien_court_mort(self, get):
        with self.assertRaises(ValidationError):
            EmbedBlock().clean(EmbedValue('https://fb.watch/zzz/'))

    def test_la_video_s_affiche_dans_l_article(self):
        make_site()
        article = make_article_page(
            title='Vidéo de la manif', slug='video-manif',
            body=[{'type': 'embed',
                   'value': 'https://www.facebook.com/cntso/videos/10153231379946729/'}])
        reponse_http = self.client.get(
            reverse('content:article_detail', kwargs={'slug': article.slug}))
        self.assertEqual(reponse_http.status_code, 200)
        self.assertContains(reponse_http, 'https://www.facebook.com/plugins/video.php?href=')
