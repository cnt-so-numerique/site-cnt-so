"""Vidéos Facebook dans le bloc « Vidéo / iFrame » (EmbedBlock).

Wagtail ne connaît plus Facebook : son oEmbed exige depuis 2020 une
application Meta validée, et le finder officiel charge en plus un script
Facebook que la CSP du site refuse. Facebook offre pourtant un lecteur
intégrable sans clé ni script, `facebook.com/plugins/video.php?href=…` :
ce finder transforme un lien de vidéo publique en cette iframe, sans aucun
appel réseau pour les liens complets.

Les liens courts (`fb.watch/…`, `facebook.com/share/v/…`, `…/share/r/…`)
ne disent pas quelle vidéo ils désignent : on suit leurs redirections une
fois, à l'enregistrement, pour retrouver le lien complet.

Seules les vidéos publiques s'affichent ; celles d'un groupe fermé ou d'un
profil privé donnent un lecteur « vidéo indisponible », Facebook n'en
laissant rien voir aux visiteurs non connectés.
"""
import re
from urllib.parse import parse_qs, quote, urlsplit

import requests
from django.utils.html import format_html
from wagtail.embeds.exceptions import EmbedNotFoundException
from wagtail.embeds.finders.base import EmbedFinder

HOTE_FACEBOOK = re.compile(r'^(?:[\w-]+\.)?facebook\.com$', re.IGNORECASE)
HOTE_COURT = re.compile(r'^(?:www\.)?fb\.watch$', re.IGNORECASE)

# Chemins d'une vidéo, `/` final et paramètres de suivi (`?mibextid=…`) ignorés.
VIDEO_DE_PAGE = re.compile(r'^/[^/]+/videos/(?:[^/]+/)?(\d+)/?$')
REEL = re.compile(r'^/reels?/(\d+)/?$')
PARTAGE = re.compile(r'^/share/(?:v|r)/[\w-]+/?$')

LECTEUR = 'https://www.facebook.com/plugins/video.php'


def lien_canonique(url):
    """(lien complet de la vidéo, vertical ?) ou None si ce n'en est pas un."""
    morceaux = urlsplit(url.strip())
    if morceaux.scheme not in ('http', 'https'):
        return None
    if not HOTE_FACEBOOK.match(morceaux.hostname or ''):
        return None
    chemin, requete = morceaux.path, parse_qs(morceaux.query)

    # Toutes les formes se ramènent à `watch/?v=` : un reel est une vidéo
    # comme une autre, et le lecteur n'a pas besoin du nom de la page.
    if trouve := VIDEO_DE_PAGE.match(chemin):
        return f'https://www.facebook.com/watch/?v={trouve[1]}', False
    if trouve := REEL.match(chemin):
        return f'https://www.facebook.com/watch/?v={trouve[1]}', True
    if chemin.rstrip('/') in ('/watch', '/video.php'):
        identifiant = (requete.get('v') or requete.get('id') or [''])[0]
        if identifiant.isdigit():
            return f'https://www.facebook.com/watch/?v={identifiant}', False
    return None


def est_lien_court(url):
    morceaux = urlsplit(url.strip())
    hote = morceaux.hostname or ''
    if HOTE_COURT.match(hote):
        return True
    return bool(HOTE_FACEBOOK.match(hote) and PARTAGE.match(morceaux.path))


def deplier(url):
    """Lien complet derrière un lien court, en suivant les redirections.

    Facebook renvoie parfois un visiteur anonyme vers sa page de connexion,
    le lien de la vidéo étant alors dans le paramètre `next`.
    """
    try:
        reponse = requests.get(
            url, timeout=10, allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0'},
        )
    except requests.RequestException as e:
        raise EmbedNotFoundException(f'Lien court illisible : {e}') from e
    for etape in [*reponse.history, reponse]:
        for candidat in (etape.url, etape.headers.get('Location', '')):
            if not candidat:
                continue
            trouve = lien_canonique(candidat)
            if trouve:
                return trouve
            suivant = parse_qs(urlsplit(candidat).query).get('next', [''])[0]
            if suivant and (trouve := lien_canonique(suivant)):
                return trouve
    return None


class FacebookVideoFinder(EmbedFinder):
    def accept(self, url):
        return lien_canonique(url) is not None or est_lien_court(url)

    def find_embed(self, url, max_width=None, max_height=None):
        trouve = lien_canonique(url) or deplier(url)
        if not trouve:
            raise EmbedNotFoundException(f'Pas une vidéo Facebook : {url}')
        lien, vertical = trouve
        largeur, hauteur = (267, 476) if vertical else (560, 314)
        source = (f'{LECTEUR}?href={quote(lien, safe="")}'
                  f'&show_text=false&width={largeur}')
        html = format_html(
            '<iframe src="{}" width="{}" height="{}" title="Vidéo Facebook" '
            'style="border:none;overflow:hidden;width:100%;max-width:{}px;'
            'height:auto;aspect-ratio:{}/{}" scrolling="no" '
            'allow="autoplay; clipboard-write; encrypted-media; '
            'picture-in-picture; web-share" allowfullscreen loading="lazy">'
            '</iframe>',
            source, largeur, hauteur, largeur, largeur, hauteur,
        )
        return {
            'title': '',
            'author_name': '',
            'provider_name': 'Facebook',
            'type': 'video',
            'thumbnail_url': '',
            'width': largeur,
            'height': hauteur,
            'html': html,
        }


embed_finder_class = FacebookVideoFinder
