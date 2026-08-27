import json

from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()

# Schémas d'URL autorisés pour les liens et médias
_SAFE_URL_SCHEMES = {'http', 'https', '/'}

# Échappement JS-safe pour insérer du JSON dans un <script> — même logique
# que django.utils.html.json_script (échappe </script>, pas de quotes HTML).
_JSON_SCRIPT_ESCAPES = {ord('>'): '\\u003E', ord('<'): '\\u003C', ord('&'): '\\u0026'}


@register.simple_tag
def absolute_url(url, base):
    """Préfixe `url` avec `base` si elle n'est pas déjà absolue (image legacy,
    article d'une section à domaine autonome — voir newsletter_views._annotate_image_urls)."""
    if not url:
        return ''
    if url.startswith('http'):
        return url
    return f'{base}{url}'


@register.simple_tag
def section_url(nom_route, site, *args, **kwargs):
    """URL d'une route de section, déjà canonique sur un domaine autonome.

    `{% url %}` produit toujours `/<slug>/…`. Quand la section a son propre
    domaine, `SectionDomainMiddleware` redirige cette forme en 301 vers l'URL
    sans préfixe : un aller-retour réseau à chaque lien (301 sur la page
    Ressources de Poitiers, audit du 01/08). On rend directement la forme
    finale. Sans domaine autonome, le chemin relatif est inchangé.
    """
    from django.urls import reverse, NoReverseMatch
    from cms.models import section_base_url

    slug = getattr(site, 'slug', '') or ''
    if not slug:
        return ''
    try:
        if kwargs:
            chemin = reverse(nom_route, kwargs={'site_slug': slug, **kwargs})
        else:
            chemin = reverse(nom_route, args=[slug, *args])
    except NoReverseMatch:
        return ''

    base = section_base_url(slug)
    if not base:
        return chemin
    prefixe = f'/{slug}'
    if chemin.startswith(f'{prefixe}/'):
        chemin = chemin[len(prefixe):]
    elif chemin == prefixe:
        chemin = '/'
    return f'{base}{chemin}'


_COULEUR_HEX = __import__('re').compile(r'^#[0-9A-Fa-f]{6}$')


@register.filter
def couleur_sure(valeur):
    """Une couleur `#RRGGBB` sûre à insérer dans un attribut `style`.

    Les rédacteurs choisissent librement leurs couleurs depuis le 15/08/2026.
    Le bloc valide la saisie, mais la valeur rendue vient de la base : une
    révision importée ou modifiée hors formulaire pourrait porter autre chose,
    et `style="color: {{ … }}"` est une injection CSS. On revalide donc au
    rendu, et on retombe sur le rouge de la charte plutôt que d'émettre une
    déclaration cassée.
    """
    from cms.models import COULEUR_CHARTE
    valeur = (valeur or '').strip()
    return valeur if _COULEUR_HEX.match(valeur) else COULEUR_CHARTE


@register.filter
def texte_lisible(couleur):
    """Noir ou blanc, celui qui se lit sur `couleur` (luminance WCAG)."""
    from cms.models import texte_lisible_sur
    return texte_lisible_sur(couleur_sure(couleur))


@register.filter
def json_ld(data):
    """Sérialise un dict en JSON sûr à insérer tel quel dans un <script type="application/ld+json">."""
    if not data:
        return ''
    return mark_safe(json.dumps(data).translate(_JSON_SCRIPT_ESCAPES))


@register.simple_tag
def article_structured_data(article, base_url, canonical_url):
    """Dict JSON-LD Article (schema.org) — à sérialiser avec le filtre `json_ld`."""
    data = {
        '@context': 'https://schema.org',
        '@type': 'NewsArticle',
        'headline': article.title,
        'description': article.meta_description or article.title,
        'datePublished': article.published_at.isoformat() if article.published_at else None,
        'author': {'@type': 'Organization', 'name': article.author_name or 'CNT-SO'},
        'publisher': {
            '@type': 'Organization',
            'name': 'CNT-SO',
            'logo': {'@type': 'ImageObject', 'url': f"{base_url}{static('image/CNT SO.jpg')}"},
        },
    }
    if canonical_url:
        data['mainEntityOfPage'] = {'@type': 'WebPage', '@id': canonical_url}
    if article.any_image_url:
        data['image'] = [absolute_url(article.any_image_url, base_url)]
    return {k: v for k, v in data.items() if v is not None}


# `_render_block` et `render_content` ont été retirés le 27/08/2026 : environ
# 150 lignes qui rendaient le contenu des articles legacy (JSON EditorJS ou
# HTML WordPress). Plus aucun gabarit ne les appelait — seuls leurs propres
# tests les atteignaient encore.
#
# `render_content` faisait `mark_safe()` sur du HTML brut. Inoffensif tant que
# personne ne peut écrire dans ces tables — les modèles legacy ne sont plus
# enregistrés dans l'admin depuis le 01/08/2026 — mais c'était une arme
# chargée posée sur l'étagère, à portée du prochain qui aurait rebranché le
# filtre. Les 1 701 articles et 63 pages legacy ont tous leur équivalent
# Wagtail (vérifié en production le 27/08 : zéro orphelin).

@register.simple_tag
def banque_images_url(site=None):
    """URL de la banque d'images valable depuis `site`, ou chaîne vide.

    Le bloc de la barre latérale fabriquait l'adresse pour le site courant, en
    supposant que chaque syndicat a sa propre catégorie « banque-dimage ». Six
    sur neuf ne l'ont pas : le bloc menait donc à un 404 sur TOUTES leurs pages
    (constaté en production le 05/08/2026).

    C'est désormais la case `banque_images_propre` de la fiche du syndicat qui
    décide, plutôt qu'une déduction. Elle ne peut pas produire de lien mort :
    cochée sans que la catégorie existe, on retombe sur celle de la
    confédération. Chaîne vide si elle n'existe nulle part : au gabarit de
    masquer le bloc.

    Le repli n'a pas besoin d'être rendu absolu ici : depuis
    `url_site_principal`, l'adresse d'un contenu confédéral porte son hôte, où
    qu'elle soit rendue. C'est bien le point de cette règle — ne pas avoir à
    s'en souvenir à chaque endroit.
    """
    from cms.models import CmsCategory

    if site is not None and getattr(site, 'banque_images_propre', False):
        propre = CmsCategory.objects.filter(
            slug='banque-dimage', section_slug__in=site.slugs_contenu).first()
        if propre is not None:
            return propre.get_absolute_url()

    confederale = CmsCategory.objects.filter(
        slug='banque-dimage', section_slug='principal').first()
    return confederale.get_absolute_url() if confederale is not None else ''
