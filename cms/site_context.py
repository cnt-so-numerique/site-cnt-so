"""
Gestion du syndicat courant dans la session Wagtail.
Source unique de vérité : cms.SectionPage.
"""
import re

from django.db import models
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
        # Repli sur la confédération plutôt que « aucun syndicat ».
        #
        # Sans lui, un superuser ou un chef confédéral atterrissait après
        # connexion sur un état où la barre affiche « ⚠️ Aucun sélectionné » et
        # où les listes servent le contenu des quatorze syndicats mêlé. Aucun
        # bouton ne ramène à cet état une fois qu'on en est sorti : il
        # n'existait qu'au premier écran, et l'interface le signalait
        # elle-même comme une anomalie (relevé par Arnaud, 31/08/2026).
        #
        # `principal` est la convention du projet pour le site confédéral,
        # codée en dur dans les vues et les processeurs de contexte.
        # `.first()` et non `.get()` : une base sans page `principal` — les
        # jeux de tests qui ne créent que leur syndicat — retombe sur None,
        # c'est-à-dire l'ancien comportement, sans lever d'exception.
        return SectionPage.objects.filter(slug='principal').first()

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
    """Filtre par slug de syndicat (pour CmsCategory, ArticlePage, ContentPage).

    Voir `SectionPage.slugs_contenu` : les deux slugs sont acceptés.
    """
    current = get_current_site(request)
    if current:
        return qs.filter(**{f'{slug_field}__in': current.slugs_contenu})
    if _is_global_chef(request.user):
        return qs
    return qs.none()


def sites_de_redaction():
    """Les syndicats où l'on écrit — pas ceux qu'on référence.

    STAA et TAS ont leur propre site (staa-cnt-so.org, cnt-tas.org). Leur fiche
    existe chez nous pour porter l'`external_url` qui alimente le menu et le
    cartouche « réseau » : elle ne doit surtout pas être supprimée, mais elle
    n'est pas un endroit où rédiger. Le sélecteur les proposait quand même
    (Arnaud, 31/08/2026).

    Le critère est la donnée elle-même — un site qui renvoie ailleurs n'est pas
    un site qu'on alimente — et non une liste de slugs à tenir à jour.
    """
    from cms.models import SectionPage
    return (SectionPage.objects.filter(live=True)
            .filter(models.Q(external_url='') | models.Q(external_url__isnull=True))
            .order_by('title'))


def get_available_sites(request):
    """Liste des SectionPage accessibles à cet utilisateur."""
    from cms.models import SectionPage
    user = request.user
    if _is_global_chef(user):
        return sites_de_redaction()
    current = get_current_site(request)
    if current:
        return SectionPage.objects.filter(pk=current.pk)
    return SectionPage.objects.none()
