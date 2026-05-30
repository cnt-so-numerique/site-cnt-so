"""
Gestion du syndicat courant dans la session Wagtail.
Source unique de vérité : cms.SectionPage.
"""
from django.db.models import Q


SESSION_KEY = 'cms_current_site_id'
_LEGACY_KEY = 'redac_current_site_id'  # rétrocompatibilité session


def get_current_site(request):
    """Retourne le SectionPage courant pour cet utilisateur/session."""
    from cms.models import SectionPage
    user = request.user
    if not user.is_authenticated:
        return None

    if user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists():
        site_id = request.session.get(SESSION_KEY) or request.session.get(_LEGACY_KEY)
        if site_id:
            try:
                return SectionPage.objects.get(pk=site_id)
            except SectionPage.DoesNotExist:
                pass
        return None

    # Rédacteur : site fixé via Author.site (FK SectionPage depuis Phase 2)
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
    user = request.user
    if user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists():
        return qs  # chef sans site sélectionné → tout voir
    try:
        sp = user.author_profile.site
        if sp:
            return qs.filter(**{site_field: sp})
    except Exception:
        pass
    return qs.none()


def scope_qs_slug(qs, request, slug_field='section_slug'):
    """Filtre par slug de syndicat (pour CmsCategory, ArticlePage, ContentPage)."""
    current = get_current_site(request)
    if current:
        slug = current.legacy_site_slug or current.slug
        return qs.filter(**{slug_field: slug})
    user = request.user
    if user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists():
        return qs
    try:
        sp = user.author_profile.site
        if sp:
            slug = sp.legacy_site_slug or sp.slug
            return qs.filter(**{slug_field: slug})
    except Exception:
        pass
    return qs.none()


def get_available_sites(request):
    """Liste des SectionPage accessibles à cet utilisateur."""
    from cms.models import SectionPage
    user = request.user
    if user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists():
        return SectionPage.objects.filter(live=True).order_by('title')
    try:
        sp = user.author_profile.site
        return SectionPage.objects.filter(pk=sp.pk) if sp else SectionPage.objects.none()
    except Exception:
        return SectionPage.objects.none()
