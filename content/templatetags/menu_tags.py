from django import template
from django.db.models import Prefetch
from content.models import MenuItem

register = template.Library()


@register.simple_tag
def get_menu(site, menu_type):
    """Retourne les items racines du menu demandé pour un site, avec leurs enfants."""
    if not site:
        return []
    sr = ('target_site', 'article', 'page', 'site', 'category')
    base = (MenuItem.objects.filter(site=site, is_active=True)
            .select_related(*sr)
            .order_by('order'))
    # base.html descend à trois niveaux (item → child → grandchild) : sans ce
    # second Prefetch, chaque enfant déclenchait une requête, plus une par
    # catégorie liée pour construire son URL.
    children_qs = base.prefetch_related(Prefetch('children', queryset=base))
    return list(
        MenuItem.objects.filter(
            site=site, menu=menu_type, is_active=True, parent__isnull=True,
        )
        .select_related(*sr)
        .prefetch_related(Prefetch('children', queryset=children_qs))
        .order_by('order')
    )


def _enfants_actifs(item):
    """Enfants affichables, lus dans le cache de préchargement de `get_menu`."""
    return [c for c in item.children.all() if c.is_active]


@register.filter
def colonnes(items):
    """Racines de pied de page qui sont de vraies colonnes (avec du contenu)."""
    return [i for i in items if _enfants_actifs(i)]


@register.filter
def liens_simples(items):
    """Racines de pied de page SANS enfant : ce sont des liens, pas des titres.

    Le gabarit rendait toute racine en titre de colonne. Quatre sous-sites
    affichaient donc « CNT-SO national », « Flux RSS », « Plan du site » et
    « Contact » en en-têtes surmontant des listes vides — soit un pied de page
    entièrement creux (audit du 05/08/2026). Ces entrées ont pourtant chacune
    une destination : ce sont des liens mal placés, pas des colonnes ratées.
    """
    return [i for i in items
            if not _enfants_actifs(i) and not i.est_impasse]
