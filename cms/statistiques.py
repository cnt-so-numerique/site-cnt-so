"""Statistiques de fréquentation dans /cms/, sans cookie ni bandeau.

Chaque heure, sur le serveur, GoAccess lit les journaux nginx (timer systemd
`cntso-stats`) et écrit ses totaux en JSON : aucun script dans les pages,
aucun cookie, aucune donnée confiée à un tiers, IP anonymisées.

Le rapport HTML de GoAccess, en anglais et à vingt panneaux, s'est révélé
illisible pour qui n'est pas technicien (Arnaud, 24/09/2026). Cette page n'en
garde que quatre questions, en français : combien de visiteurs, quels jours,
quels contenus, venus d'où — avec le TITRE des articles plutôt que leur
adresse. Le rapport complet reste accessible en lien, pour qui le veut.

Les fichiers vivent hors du dépôt et hors de `media/` (qui est public) :
`settings.STATS_DONNEES` et `settings.STATS_RAPPORT`.
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from content.admin_utils import WagtailChefRequiredMixin

#: Adresses qui ne sont pas des lectures : administration, fichiers, robots.
_PAS_UNE_LECTURE = re.compile(
    r'^/(cms|admin|django-admin|static|media|api|wp-|\.|favicon|robots\.txt|'
    r'sitemap|apple-touch|feed|rss|adherer)|/feed/$|\.(php|xml|txt|ico|png|jpe?g|'
    r'gif|webp|svg|css|js|woff2?|pdf)$', re.I)

_MOTEURS = ('google.', 'bing.', 'duckduckgo.', 'qwant.', 'ecosia.', 'yahoo.',
            'startpage.', 'search.brave.', 'yandex.')
_RESEAUX = ('facebook.', 'fb.', 'instagram.', 'twitter.', 'x.com', 't.co',
            'bsky.', 'linkedin.', 'lnkd.', 'mastodon', 'threads.', 'whatsapp.',
            'telegram.', 't.me', 'youtube.', 'tiktok.', 'reddit.')
_MESSAGERIES = ('mail.', 'webmail', 'outlook.', 'gmail.', 'ovh.')

_PRINCIPAUX = ('cnt-so.org', 'www.cnt-so.org', 'newsite.cnt-so.org')


def _fichier(nom_reglage):
    return Path(getattr(settings, nom_reglage))


def _lire_donnees():
    try:
        return json.loads(_fichier('STATS_DONNEES').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _nombre(entree):
    return (entree.get('visitors') or {}).get('count', 0)


def _chemin_propre(chemin):
    return chemin.split('?', 1)[0].split('#', 1)[0] or '/'


def _libelles_des_pages(chemins):
    """{chemin: libellé lisible} — un titre d'article plutôt qu'une adresse."""
    from cms.models import ArticlePage, CmsCategory, SectionPage

    morceaux = {c: [m for m in c.strip('/').split('/') if m] for c in chemins}
    slugs_articles = {m[1] for m in morceaux.values() if len(m) == 2 and m[0] == 'article'}
    slugs_rubriques = {m[1] for m in morceaux.values() if len(m) == 2 and m[0] == 'categorie'}
    slugs_uniques = {m[0] for m in morceaux.values() if len(m) == 1}
    slugs_mots_cles = {m[1] for m in morceaux.values() if len(m) == 2 and m[0] == 'tag'}

    titres = dict(ArticlePage.objects.filter(slug__in=slugs_articles | slugs_uniques)
                  .values_list('slug', 'title'))
    rubriques = dict(CmsCategory.objects.filter(slug__in=slugs_rubriques)
                     .values_list('slug', 'name'))
    from taggit.models import Tag
    mots_cles = dict(Tag.objects.filter(slug__in=slugs_mots_cles).values_list('slug', 'name'))
    syndicats = {}
    for slug, ancien, titre in SectionPage.objects.values_list('slug', 'legacy_site_slug', 'title'):
        syndicats[slug] = titre
        if ancien:
            syndicats[ancien] = titre

    fixes = {'contact': 'Contact', 'recherche': 'Recherche', 'agenda': 'Agenda',
             'mentions-legales': 'Mentions légales', 'cgu': 'CGU'}
    libelles = {}
    for chemin, m in morceaux.items():
        if not m:
            libelles[chemin] = 'Accueil'
        elif len(m) == 2 and m[0] == 'article':
            libelles[chemin] = titres.get(m[1], chemin)
        elif len(m) == 2 and m[0] == 'categorie':
            libelles[chemin] = f"Rubrique « {rubriques.get(m[1], m[1])} »"
        elif len(m) == 2 and m[0] == 'tag':
            libelles[chemin] = f"Mot-clé « {mots_cles.get(m[1], m[1])} »"
        elif len(m) == 1 and m[0] in syndicats:
            libelles[chemin] = f"Accueil — {syndicats[m[0]]}"
        elif len(m) == 1 and m[0] in titres:
            libelles[chemin] = titres[m[0]]
        elif len(m) == 1 and m[0] in fixes:
            libelles[chemin] = fixes[m[0]]
        else:
            libelles[chemin] = chemin
    return libelles


def _contenus_les_plus_lus(donnees, nombre=10):
    visiteurs = defaultdict(int)
    for entree in (donnees.get('requests') or {}).get('data', []):
        chemin = _chemin_propre(entree.get('data', ''))
        if _PAS_UNE_LECTURE.search(chemin):
            continue
        visiteurs[chemin] += _nombre(entree)
    libelles = _libelles_des_pages(visiteurs)
    par_libelle = defaultdict(int)
    for chemin, n in visiteurs.items():
        par_libelle[libelles[chemin]] += n
    classement = sorted(par_libelle.items(), key=lambda x: -x[1])[:nombre]
    maximum = classement[0][1] if classement else 1
    return [{'libelle': l, 'visiteurs': n, 'largeur': round(100 * n / maximum)}
            for l, n in classement]


def _noms_des_domaines():
    """{domaine: nom du syndicat} pour tous les domaines que sert le site."""
    from cms.models import SectionPage
    noms = dict(SectionPage.objects.exclude(custom_domain='')
                .values_list('custom_domain', 'title'))
    for principal in _PRINCIPAUX:
        noms[principal] = 'CNT-SO (confédération)'
    return noms


def _provenances(donnees):
    """D'où viennent les visiteurs, en quelques familles lisibles."""
    nos_domaines = set(_noms_des_domaines())
    familles = defaultdict(int)
    for entree in (donnees.get('referring_sites') or {}).get('data', []):
        site = (entree.get('data') or '').lower()
        if not site or site in nos_domaines:
            continue  # un clic d'une page du site à une autre
        if any(m in site for m in _MOTEURS):
            familles['Moteurs de recherche (Google…)'] += _nombre(entree)
        elif any(r in site for r in _RESEAUX):
            familles['Réseaux sociaux'] += _nombre(entree)
        elif any(r in site for r in _MESSAGERIES):
            familles['Courriels et newsletter'] += _nombre(entree)
        else:
            familles['Autres sites'] += _nombre(entree)
    # Les visites sans provenance. GoAccess 1.8 les donne (« - » du panneau
    # `referrers`) ; la 1.7 du serveur ne publie pas ce panneau : on les
    # déduit alors du total, d'où le libellé prudent.
    directs = [e for e in (donnees.get('referrers') or {}).get('data', [])
               if e.get('data') == '-']
    if directs:
        familles['Accès direct (favori, adresse tapée, appli)'] += sum(map(_nombre, directs))
    else:
        reste = (donnees.get('general') or {}).get('unique_visitors', 0) - sum(familles.values())
        if reste > 0:
            familles['Accès direct ou inconnu'] += reste
    total = sum(familles.values()) or 1
    return [{'libelle': l, 'visiteurs': n, 'part': round(100 * n / total)}
            for l, n in sorted(familles.items(), key=lambda x: -x[1]) if n]


def _par_site(donnees):
    noms = _noms_des_domaines()
    sites = defaultdict(int)
    for entree in (donnees.get('vhosts') or {}).get('data', []):
        domaine = entree.get('data', '')
        if domaine in noms:  # écarte les robots qui visent l'adresse IP
            sites[noms[domaine]] += _nombre(entree)
    maximum = max(sites.values(), default=0) or 1
    return [{'libelle': l, 'visiteurs': n, 'largeur': round(100 * n / maximum)}
            for l, n in sorted(sites.items(), key=lambda x: -x[1])]


def _jours(donnees):
    jours = []
    for entree in (donnees.get('visitors') or {}).get('data', []):
        try:
            jour = datetime.strptime(entree.get('data', ''), '%Y%m%d').date()
        except ValueError:
            continue
        jours.append({'jour': jour, 'visiteurs': _nombre(entree)})
    jours.sort(key=lambda j: j['jour'])
    maximum = max((j['visiteurs'] for j in jours), default=0) or 1
    for j in jours:
        j['hauteur'] = max(2, round(100 * j['visiteurs'] / maximum))
    return jours


def resume(donnees):
    """Ce que la page affiche, calculé depuis le JSON de GoAccess."""
    jours = _jours(donnees)
    total = (donnees.get('general') or {}).get('unique_visitors', 0)
    return {
        'visiteurs': total,
        'moyenne': round(total / len(jours)) if jours else 0,
        'nb_jours': len(jours),
        'jours': jours,
        'contenus': _contenus_les_plus_lus(donnees),
        'provenances': _provenances(donnees),
        'sites': _par_site(donnees),
    }


class StatistiquesView(WagtailChefRequiredMixin, View):
    """La page d'admin : quatre réponses simples, ou l'explication de leur absence."""

    def get(self, request):
        donnees = _lire_donnees()
        return render(request, 'cms/statistiques.html', {
            'stats': resume(donnees) if donnees else None,
            'rapport_complet': _fichier('STATS_RAPPORT').is_file(),
        })


class RapportStatistiquesView(WagtailChefRequiredMixin, View):
    """Le rapport GoAccess complet (en anglais), pour qui veut le détail.

    Servi par Django et non par nginx : l'accès reste soumis à la connexion
    et au rôle, comme le reste de /cms/.

    Mis en bac à sable (`sandbox allow-scripts`) : le rapport recopie des
    chaînes choisies par les visiteurs (adresses, navigateurs, provenances),
    et GoAccess a déjà connu des failles XSS. Sans bac à sable, un rapport
    piégé tournerait sur l'origine de /cms/, avec la session d'un chef. Ici il
    s'exécute dans une origine opaque, sans cookie ni accès à l'admin.
    """

    def get(self, request):
        try:
            contenu = _fichier('STATS_RAPPORT').read_bytes()
        except OSError:
            return HttpResponse('Rapport indisponible.', status=404,
                                content_type='text/plain; charset=utf-8')
        reponse = HttpResponse(contenu, content_type='text/html; charset=utf-8')
        reponse['Content-Security-Policy'] = 'sandbox allow-scripts'
        return reponse
