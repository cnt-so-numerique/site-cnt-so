"""
Gestion du syndicat courant dans la session Wagtail.
Source unique de vérité : cms.SectionPage.
"""
import re

from django.db.models import Q


SESSION_KEY = 'cms_current_site_id'
_LEGACY_KEY = 'redac_current_site_id'  # rétrocompatibilité session

# Groupes par section créés par setup_cms_permissions.py :
# redacteur_<slug> (add/change) et chef_<slug> (add/change/publish).
# redacteur_en_chef est le chef confédéral — il matcherait le pattern avec un
# slug fantôme "en_chef", d'où l'exclusion explicite.
_SECTION_GROUP_RE = re.compile(r'^(?:redacteur|chef)_(.+)$')


def _is_global_chef(user):
    """Superuser ou chef confédéral (groupe redacteur_en_chef) — les seuls
    rôles multi-sites, avec sélecteur de syndicat en session."""
    return user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()


def get_group_scoped_site(user):
    """Résout le SectionPage d'un utilisateur via ses groupes par section
    (redacteur_<slug> / chef_<slug>). None si aucun groupe ne matche."""
    from cms.models import SectionPage
    for name in user.groups.values_list('name', flat=True):
        if name == 'redacteur_en_chef':
            continue
        m = _SECTION_GROUP_RE.match(name)
        if not m:
            continue
        slug = m.group(1)
        # Les groupes sont nommés d'après legacy_site_slug or slug
        # (setup_cms_permissions.py) — on accepte les deux.
        section = SectionPage.objects.filter(
            Q(slug=slug) | Q(legacy_site_slug=slug)
        ).first()
        if section:
            return section
    return None


def get_current_site(request):
    """Retourne le SectionPage courant pour cet utilisateur/session."""
    from cms.models import SectionPage
    user = request.user
    if not user.is_authenticated:
        return None

    if _is_global_chef(user):
        site_id = request.session.get(SESSION_KEY) or request.session.get(_LEGACY_KEY)
        if site_id:
            try:
                return SectionPage.objects.get(pk=site_id)
            except SectionPage.DoesNotExist:
                pass
        return None

    # Rédacteur/chef de section : groupe par section d'abord (prioritaire),
    # sinon site fixé via Author.site (FK SectionPage depuis Phase 2).
    section = get_group_scoped_site(user)
    if section:
        return section
    try:
        return user.author_profile.site
    except Exception:
        return None


def set_current_site(request, site_id):
    """Stocke le SectionPage.pk courant en session."""
    request.session[SESSION_KEY] = site_id
    request.session[_LEGACY_KEY] = site_id


def scope_qs(qs, request, site_field='site'):
    """
    Filtre un queryset par le syndicat courant.
    site_field : nom du champ FK vers SectionPage.
    Pour les champs slug, utiliser scope_qs_slug().
    """
    current = get_current_site(request)
    if current:
        return qs.filter(**{site_field: current})
    if _is_global_chef(request.user):
        return qs  # chef sans site sélectionné → tout voir
    return qs.none()


def scope_qs_slug(qs, request, slug_field='section_slug'):
    """Filtre par slug de syndicat (pour CmsCategory, ArticlePage, ContentPage)."""
    current = get_current_site(request)
    if current:
        slug = current.legacy_site_slug or current.slug
        return qs.filter(**{slug_field: slug})
    if _is_global_chef(request.user):
        return qs
    return qs.none()


def get_available_sites(request):
    """Liste des SectionPage accessibles à cet utilisateur."""
    from cms.models import SectionPage
    user = request.user
    if _is_global_chef(user):
        return SectionPage.objects.filter(live=True).order_by('title')
    current = get_current_site(request)
    if current:
        return SectionPage.objects.filter(pk=current.pk)
    return SectionPage.objects.none()
