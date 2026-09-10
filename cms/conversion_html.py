"""Transforme le HTML hérité de WordPress en blocs que l'on peut modifier.

L'import créait un unique bloc « HTML brut (import legacy) » par article. Ce
bloc est **masqué du menu de l'éditeur** (`CorpsBlock.BLOCS_MASQUES`) et
s'ouvre sur une zone de code source : un rédacteur ne peut ni corriger une
faute, ni déplacer une image, ni voir son texte mis en forme. Les articles
repris le 06/09/2026 étaient tous dans ce cas.

Deux règles de prudence, apprises des reprises précédentes :

1. **On ne convertit que ce que l'on sait représenter.** Un morceau qui
   contient un tableau, une vidéo embarquée ou une balise qu'on ne reconnaît
   pas reste dans un bloc HTML brut. Mieux vaut un fragment non modifiable
   qu'un contenu abîmé — un tableau déplié en paragraphes ne se répare pas.
2. **Rien n'est produit sans que Wagtail ait confirmé pouvoir le rouvrir.**
   C'est exactement le défaut du 15/08/2026 : 261 articles s'affichaient
   parfaitement en public et renvoyaient une erreur 500 dès qu'un rédacteur
   cliquait sur « Modifier ». Chaque bloc de texte riche est donc repassé par
   le convertisseur de l'éditeur avant d'être accepté.

Une image jamais retrouvée dans la médiathèque n'est jamais supprimée : elle
retombe dans un bloc HTML brut, avec sa balise d'origine.

Deux exceptions, et deux seulement, sont retirées sans état d'âme :

- l'**aperçu PDF du bloc fichier WordPress** (`<object class="wp-block-file__embed">`),
  masqué d'office et piloté par un moteur JavaScript que nous n'embarquons pas.
  Le bloc fichier de WordPress porte toujours, à côté, le lien de
  téléchargement — que l'import convertit déjà en bloc « fichier ». L'aperçu
  est donc un doublon inerte, présent dans 17 articles sur 20 mesurés le
  10/09/2026 ; le garder condamnait tout l'article à rester en HTML brut ;
- les balises `<script>` et `<style>` héritées : depuis le durcissement du
  09/09/2026, la politique de sécurité du site interdit les scripts tiers.
  Celui qu'on a mesuré (embed.bsky.app) ne s'exécute donc déjà plus. Le
  contenu de repli — la citation du message — reste, lui, en place.
"""

import uuid
from functools import lru_cache

from bs4 import BeautifulSoup, NavigableString, Tag

# Les seules balises que le texte riche sait porter, déduites de
# RICHTEXT_FEATURES (cms/models.py). Tout le reste est déplié ou écarté.
BALISES_TEXTE = {
    'p', 'h2', 'h3', 'h4', 'h5',
    'ul', 'ol', 'li',
    'a', 'strong', 'em', 's',
    'blockquote', 'hr', 'br',
}

# Équivalences : le titre de niveau 1 est déjà celui de la page, le souligné a
# été retiré des fonctionnalités le 15/08/2026 (il se confond avec un lien).
RENOMMAGES = {
    'h1': 'h2', 'h6': 'h5',
    'b': 'strong', 'i': 'em',
    'strike': 's', 'del': 's',
}

# Emballages sans valeur sémantique : on les déplie pour retrouver le texte.
CONTENEURS = {
    'div', 'span', 'section', 'article', 'main', 'header', 'footer',
    'aside', 'center', 'font', 'figure', 'figcaption', 'small', 'u',
    'pre', 'code', 'time', 'label',
}

# Ce que le texte riche ne saura pas rendre : le morceau reste en HTML brut.
INCOMPATIBLES = {
    'table', 'iframe', 'script', 'style', 'form', 'video', 'audio',
    'object', 'embed', 'svg', 'canvas', 'input', 'select', 'button',
}


@lru_cache(maxsize=1)
def _convertisseur():
    """Le convertisseur de l'éditeur, coûteux à construire : on le garde."""
    from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
    from cms.models import RICHTEXT_FEATURES
    return ContentstateConverter(RICHTEXT_FEATURES)


def texte_riche_ouvrable(html):
    """Vrai si l'éditeur sait rouvrir ce texte riche sans casser."""
    try:
        _convertisseur().from_database_format(html)
        return True
    except Exception:
        return False


def _image_par_source(src):
    """Retrouve l'image de la médiathèque derrière une adresse /media/….

    L'import réécrit les images WordPress en `/media/<nom du fichier Wagtail>`
    (`_download_inline_images`), donc la correspondance est exacte. Une adresse
    qui pointe ailleurs — un domaine tiers, un fichier jamais rapatrié — ne
    donne rien, et l'appelant la laissera en HTML brut plutôt que de la perdre.
    """
    from wagtail.images import get_image_model

    if not src:
        return None
    chemin = src.split('?', 1)[0].split('#', 1)[0]
    for prefixe in ('/media/', 'media/'):
        if chemin.startswith(prefixe):
            chemin = chemin[len(prefixe):]
            break
    else:
        return None
    return get_image_model().objects.filter(file=chemin).first()


def _bloc(type_, valeur):
    return {'type': type_, 'value': valeur, 'id': str(uuid.uuid4())}


def _retire_widgets_inertes(soup):
    """Retire les greffons WordPress qui ne peuvent plus rien faire ici.

    Retourne le nombre d'éléments retirés. Voir l'en-tête du module : c'est la
    seule suppression que ce fichier s'autorise, et elle est motivée.
    """
    retires = 0
    for objet in soup.find_all('object'):
        classes = objet.get('class') or []
        if 'wp-block-file__embed' in classes:
            objet.decompose()
            retires += 1
    for balise in soup.find_all(['script', 'style', 'noscript']):
        balise.decompose()
        retires += 1
    return retires


def _deplie_conteneurs(soup):
    """Retire les emballages, en gardant la légende des figures."""
    # La légende d'une figure devient celle du bloc image : on la note sur la
    # balise avant de déplier, sans quoi elle finirait en paragraphe orphelin.
    for figure in soup.find_all('figure'):
        legende = figure.find('figcaption')
        image = figure.find('img')
        if legende and image:
            image['data-legende'] = legende.get_text(' ', strip=True)
            legende.decompose()

    # Un conteneur peut en cacher un autre : on recommence jusqu'au point fixe.
    for _ in range(10):
        cibles = [t for t in soup.find_all(True) if t.name in CONTENEURS]
        if not cibles:
            break
        for tag in cibles:
            tag.unwrap()


def _nettoie(fragment):
    """Ramène un fragment aux seules balises du texte riche."""
    soup = BeautifulSoup(fragment, 'html.parser')

    for tag in soup.find_all(True):
        if tag.name in RENOMMAGES:
            tag.name = RENOMMAGES[tag.name]

    for tag in soup.find_all(True):
        if tag.name not in BALISES_TEXTE:
            tag.unwrap()
            continue
        # Les attributs hérités (classes WordPress, styles en ligne, id) n'ont
        # aucun sens ici et l'éditeur les jetterait de toute façon.
        garde = {}
        if tag.name == 'a' and tag.get('href'):
            garde['href'] = tag['href']
        tag.attrs = garde

    # Un paragraphe vide laissé par un dépliage n'apporte qu'un blanc.
    for tag in soup.find_all(['p', 'li', 'h2', 'h3', 'h4', 'h5']):
        if not tag.get_text(strip=True) and not tag.find(['br', 'hr', 'a']):
            tag.decompose()

    # Le texte nu au premier niveau doit être emballé : l'éditeur ne sait pas
    # placer un texte hors bloc.
    for enfant in list(soup.children):
        if isinstance(enfant, NavigableString) and enfant.strip():
            p = soup.new_tag('p')
            enfant.wrap(p)

    # Pas de normalisation des `<br>` orphelins ici : l'analyseur de bs4 les
    # referme en `<br/>` de lui-même (vérifié par mutation le 10/09/2026, le
    # test passait sans la garde). Ce qui protège vraiment le rédacteur, c'est
    # la validation par le convertisseur de l'éditeur, plus bas.
    return str(soup).strip()


def _bloc_image(balise, resoud_image):
    """Un bloc image si l'on retrouve le fichier, sinon None."""
    image = resoud_image(balise.get('src', ''))
    if image is None:
        return None
    legende = balise.get('data-legende') or balise.get('alt') or ''
    return _bloc('image', {
        'image': image.pk,
        'caption': legende.strip()[:255],
        'alignment': 'center',
        # Pleine largeur de la colonne : c'est ainsi que le HTML brut les
        # affichait, un rédacteur qui veut plus petit le règle en deux clics.
        'largeur': '100',
    })


def html_vers_blocs(html, resoud_image=None):
    """Convertit du HTML WordPress en une liste de blocs de `body`.

    Retourne `(blocs, stats)`. `stats` compte ce qui a été produit et, surtout,
    ce qui **n'a pas pu** l'être : `html_conserve` (morceaux laissés en HTML
    brut) et `images_perdues` (fichiers introuvables en médiathèque). Un appelant
    honnête affiche ces deux nombres.
    """
    resoud_image = resoud_image or _image_par_source
    stats = {'rich_text': 0, 'image': 0, 'html_conserve': 0,
             'images_perdues': 0, 'widgets_retires': 0}
    if not html or not html.strip():
        return [], stats

    soup = BeautifulSoup(html, 'html.parser')
    stats['widgets_retires'] = _retire_widgets_inertes(soup)
    _deplie_conteneurs(soup)

    blocs = []
    tampon = []

    def vide_tampon():
        fragment = ''.join(str(n) for n in tampon).strip()
        tampon.clear()
        if not fragment:
            return
        # Un tableau, une vidéo : on préfère garder le HTML tel quel.
        if BeautifulSoup(fragment, 'html.parser').find(list(INCOMPATIBLES)):
            blocs.append(_bloc('html', fragment))
            stats['html_conserve'] += 1
            return
        propre = _nettoie(fragment)
        if not BeautifulSoup(propre, 'html.parser').get_text(strip=True) \
                and '<hr' not in propre:
            return
        if texte_riche_ouvrable(propre):
            blocs.append(_bloc('rich_text', propre))
            stats['rich_text'] += 1
        else:
            # Jamais de bloc que l'éditeur ne saurait rouvrir : on rend la main
            # au HTML brut, qui s'affiche correctement en public.
            blocs.append(_bloc('html', fragment))
            stats['html_conserve'] += 1

    def sort_image(balise):
        bloc = _bloc_image(balise, resoud_image)
        if bloc is not None:
            blocs.append(bloc)
            stats['image'] += 1
        else:
            # Fichier introuvable : la balise d'origine est préservée telle
            # quelle, un lien qui marche encore ne doit pas devenir un trou.
            blocs.append(_bloc('html', str(balise)))
            stats['images_perdues'] += 1
            stats['html_conserve'] += 1

    for noeud in list(soup.children):
        if isinstance(noeud, NavigableString):
            tampon.append(noeud)
            continue
        if not isinstance(noeud, Tag):
            continue
        if noeud.name == 'img':
            vide_tampon()
            sort_image(noeud)
            continue
        images = noeud.find_all('img')
        # `find` ne regarde que les descendants : le nœud lui-même peut être
        # le tableau.
        if images and (noeud.name in INCOMPATIBLES
                       or noeud.find(list(INCOMPATIBLES))):
            # Ce morceau finira en HTML brut (tableau, vidéo) : ses images
            # doivent y rester. Les en sortir les ferait paraître deux fois,
            # une dans le HTML conservé et une en bloc image.
            tampon.append(noeud)
            continue
        if images:
            # Une image dans un paragraphe : on la sort du flux de texte, le
            # bloc image de Wagtail ne peut pas vivre à l'intérieur d'un texte.
            for balise in images:
                balise.extract()
            tampon.append(noeud)
            vide_tampon()
            for balise in images:
                sort_image(balise)
            continue
        tampon.append(noeud)

    vide_tampon()
    return blocs, stats
