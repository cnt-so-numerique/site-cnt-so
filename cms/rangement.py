"""Outils communs aux commandes qui rangent des articles dans des rubriques.

Deux commandes en ont besoin — `range_categories_education` et
`cree_rubriques_luttes_education` —, et ce sont deux pièges appris sur les
données réelles plutôt que des utilitaires de confort. Les dupliquer, c'était
prendre le risque de n'en corriger qu'un.
"""


def mots(texte):
    """La suite des mots, débarrassée de la typographie.

    Les titres venus de WordPress portent des espaces insécables (U+00A0)
    devant les deux-points et les points d'exclamation — douze des titres de
    l'Éducation en ont. Un fragment de titre tapé avec une espace ordinaire ne
    correspondait alors plus, et le garde-fou refusait de ranger un article
    pourtant parfaitement identifié (relevé en production le 12/09/2026).

    Comparer les mots ne l'affaiblit pas : il est là pour repérer un `pk`
    réattribué à un AUTRE article, pas pour arbitrer une espace.
    """
    return ' '.join(texte.split())


def aligne_revision(page):
    """Persiste les rubriques de la page ET les reporte dans sa révision.

    Deux raisons, chacune vérifiée :

    - `ParentalManyToManyField` ne persiste qu'au `save()` : sans lui, `set()`
      et `add()` ne quittent jamais la mémoire ;
    - sans le report dans la révision, le rédacteur qui rouvre l'article voit
      l'ancien cochage et le réécrit à son premier enregistrement — le
      rangement serait défait par la première personne qui y touche.
    """
    page.save()
    revision = page.latest_revision
    if revision is None:
        return
    contenu = revision.content
    if not isinstance(contenu, dict) or 'cms_categories' not in contenu:
        return
    contenu['cms_categories'] = [c.pk for c in page.cms_categories.all()]
    revision.content = contenu
    revision.save(update_fields=['content'])
