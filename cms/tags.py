"""Une seule orthographe par tag.

Les tags (taggit) sont communs à tous les syndicats et chaque rédacteur en crée
en tapant un mot : on obtenait `grève`, `grêve` et `#grève`, `Education` et
`éducation`, `TPE 2024` et `TPE2024`… (Arnaud, 18/11/2026). Chaque syndicat
garde le droit de créer les siens ; on empêche seulement les variantes d'un
tag qui existe déjà.

Deux tags sont des variantes l'un de l'autre quand ils ont la même `cle_tag` :
casse, accents, `#`, espaces et ponctuation ignorés.
"""

import re
import unicodedata

from django.db.models import Count, Q


def cle_tag(nom):
    """« #Grêve », « grève » et « greve » donnent tous « greve »."""
    sans_accents = unicodedata.normalize('NFKD', nom.casefold())
    sans_accents = ''.join(c for c in sans_accents if not unicodedata.combining(c))
    return re.sub(r'[\W_]+', '', sans_accents)


def nom_propre(nom):
    """Le nom tel qu'un rédacteur l'a tapé, sans `#` ni espaces superflus."""
    return re.sub(r'\s+', ' ', nom.strip().lstrip('#').strip())


def tags_par_cle(section_slug=None):
    """{clé: [Tag, …]}, les plus employés d'abord.

    Avec `section_slug`, les tags déjà employés par ce syndicat passent devant :
    entre deux variantes, il retrouve la sienne.
    """
    from taggit.models import Tag
    tags = Tag.objects.annotate(
        n=Count('cms_cmsarticletag_items', distinct=True),
        n_section=Count('cms_cmsarticletag_items', distinct=True, filter=Q(
            cms_cmsarticletag_items__content_object__section_slug=section_slug or '')),
    ).order_by('-n_section', '-n', 'name')
    groupes = {}
    for tag in tags:
        groupes.setdefault(cle_tag(tag.name), []).append(tag)
    return groupes


def rapproche(noms, section_slug=None):
    """Remplace chaque nom saisi par le tag existant qui lui répond.

    Un nom sans équivalent est gardé (débarrassé de `#`) : c'est un nouveau
    tag, que le syndicat a le droit de créer. Deux saisies qui se répondent
    (« grève » et « Greve ») n'en font qu'une.
    """
    groupes = None
    vus, resultat = set(), []
    for nom in noms:
        nom = nom_propre(nom)
        cle = cle_tag(nom)
        if not cle or cle in vus:
            continue
        vus.add(cle)
        if groupes is None:
            groupes = tags_par_cle(section_slug)
        existants = groupes.get(cle)
        resultat.append(existants[0].name if existants else nom)
    return resultat
