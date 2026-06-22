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
    children_qs = (MenuItem.objects.filter(site=site, is_active=True)
                   .select_related(*sr)
                   .order_by('order'))
    return list(
        MenuItem.objects.filter(
            site=site, menu=menu_type, is_active=True, parent__isnull=True,
        )
        .select_related(*sr)
        .prefetch_related(Prefetch('children', queryset=children_qs))
        .order_by('order')
    )
