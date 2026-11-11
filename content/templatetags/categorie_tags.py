"""Libellé d'une catégorie dans les étiquettes d'articles.

Au 13, sept rubriques s'appellent « Actualités - luttes » ou presque — une par
secteur (BTP, Nettoyage, Transports…) — et autant « Vos droits » ou
« Revendiquons ! ». Avec le seul nom, un rédacteur les a crues toutes
identiques (11/11/2026). Le secteur (le parent) n'est ajouté qu'à ces
homonymes : l'ajouter partout afficherait « Syndicalisme » sur 21 étiquettes de
la conf, ou des restes WordPress comme « - CNT-Solidarité Ouvrière ».
"""
import re
import unicodedata

from django import template

from cms.models import CmsCategory

register = template.Library()

MOTS_VIDES = {'et', 'de', 'du', 'des', 'la', 'le', 'les', 'l', 'd'}


def forme_reduite(nom):
    """« Actualité et luttes » et « Actualités - luttes » → « actualite lutte »."""
    sans_accents = unicodedata.normalize('NFKD', nom).encode('ascii', 'ignore').decode()
    mots = re.findall(r'[a-z0-9]+', sans_accents.lower())
    return ' '.join(m.rstrip('s') for m in mots if m not in MOTS_VIDES)


def _homonymes(request, section_slug):
    """Formes réduites portées par plusieurs catégories du syndicat.

    Une requête par syndicat et par page : le résultat est gardé sur la requête.
    """
    memo = getattr(request, '_homonymes_categories', None) if request else None
    if memo is None:
        memo = {}
        if request is not None:
            request._homonymes_categories = memo
    if section_slug not in memo:
        vues, doubles = set(), set()
        for nom in CmsCategory.objects.filter(
                section_slug=section_slug).values_list('name', flat=True):
            forme = forme_reduite(nom)
            (doubles if forme in vues else vues).add(forme)
        memo[section_slug] = doubles
    return memo[section_slug]


def libelle(categorie, request=None):
    # Le parent n'est chargé (une requête) que pour un homonyme.
    if (not categorie.parent_id or forme_reduite(categorie.name)
            not in _homonymes(request, categorie.section_slug)):
        return categorie.name
    parent = categorie.parent.name.lstrip('- ').strip()
    if parent == categorie.name:
        return categorie.name
    return f'{parent} › {categorie.name}'


@register.simple_tag(takes_context=True)
def libelle_categorie(context, categorie):
    return libelle(categorie, context.get('request'))
