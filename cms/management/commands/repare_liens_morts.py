"""
Répare, dans les articles, les liens internes qui ne mènent plus nulle part.

Le site a changé trois fois de moteur — SPIP, WordPress, Wagtail — et chaque
reprise a gardé les liens écrits à la main dans les textes. Recensés le
14/09/2026 : 94 adresses `*.cnt-so.org` répondaient 404, dans une centaine de
pages. Voir `tasks/chantier-liens-morts.md`.

**Seuls les liens qui répondent réellement en erreur sont traités** : chaque
adresse est demandée au site en ligne au moment où la commande tourne. Un lien
qui marche — y compris grâce à une redirection — n'est jamais réécrit.

Ce qu'on sait réparer, et seulement quand la cible est unique :

- **adresse SPIP** `www.cnt-so.org/COVID-19-Autotests-gratuits-pour` : SPIP
  tronquait le titre, WordPress en a fait le slug complet — on cherche l'article
  dont le slug *commence* par ces mots, publié avant l'article qui le cite (à
  six mois près, voir `DELAI_REDATATION`). Un titre que SPIP a dû numéroter
  (`Nettoyage-grilles-des-salaires653`) avait des homonymes : jamais relié ;
- **adresse WordPress** `cnt-so.org/<slug>/`, `cnt-so.org/<syndicat>/<slug>/`,
  `educ.cnt-so.org/<slug>/` : l'article ou la page de même slug ;
- **catégorie WordPress** `…/category/…/<slug>/` : la catégorie de même slug du
  même syndicat ;
- **fichier SPIP** `…/IMG/pdf/<nom>` : le même nom parmi les documents rapatriés
  de l'ancien serveur, versé en médiathèque ;
- **adresse électronique collée à l'adresse de la page**
  `…/brevets-sur-les-vaccins/contact@exemple.org` : un lien `mailto:`.

Quand plusieurs articles conviennent, on ne tranche que s'ils portent le même
slug — c'est alors le même texte publié par deux syndicats : on prend celui du
syndicat qui cite, sinon celui de la confédération. Tout le reste est listé.

Avec `--delier`, les liens qu'on ne sait pas réparer sont **retirés** : le texte
reste, le lien disparaît. Le lecteur ne tombe plus sur une erreur 404, mais
l'adresse d'origine n'est plus visible — elle reste dans l'historique des
révisions de la page. À demander explicitement, jamais par défaut.

Usage :
    python manage.py repare_liens_morts                     # simulation
    python manage.py repare_liens_morts --rapport liens.csv
    python manage.py repare_liens_morts --appliquer
"""

import csv
import html
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import timedelta
from urllib.parse import unquote, urlsplit

from django.core.management.base import BaseCommand

from cms.conversion_html import racine_legacy
from cms.management.commands.repare_liens_fichiers import Inventaire, cle, document_pour

# Dans le JSON du corps, chaque guillemet est échappé : `href=\"…\"`.
LIEN = re.compile(r'href=\\"(https?://(?:[a-z0-9-]+\.)?cnt-so\.org(?:/[^"\\\s]*)?)\\"', re.IGNORECASE)

# SPIP distinguait deux titres identiques par un numéro collé au dernier mot :
# `Elections-professionnelles-TPE973`.
SUFFIXE_SPIP = re.compile(r'(?<=[A-Za-z])\d+[a-z]?$')

# En dessous, un début de titre désigne trop d'articles pour être sûr.
PREFIXE_MINIMUM = 12

# L'import SPIP → WordPress a redaté des articles : « Élection TPE-TPA 2021 :
# profession de foi » porte le 10/02/2021, mais il est cité dès le 14/11/2020.
# Sans tolérance, le lien de l'exemple même qui a ouvert ce chantier restait mort ;
# six mois laissent encore dehors les faux amis d'une autre année.
DELAI_REDATATION = timedelta(days=183)

COURRIEL = re.compile(r'^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$')


def delie(brut, adresse):
    """Retire le lien vers cette adresse, en gardant le texte qu'il portait.

    Le texte peut porter de la mise en forme (`<strong>`) : on garde l'intérieur
    de la balise tel quel.
    """
    motif = re.compile(r'<a\s[^>]*href=\\"' + re.escape(adresse) + r'\\"[^>]*>(.*?)</a>')
    return motif.subn(lambda m: m.group(1), brut)


def statut_http(adresse):
    """Le code rendu par le site en ligne, redirections suivies ; None si injoignable."""
    adresse = re.sub(r'^http://', 'https://', adresse)
    requete = urllib.request.Request(adresse, headers={'User-Agent': 'repare-liens-morts'})
    try:
        return urllib.request.urlopen(requete, timeout=20).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


class Index:
    """Les pages en ligne et les catégories, pour retrouver une cible."""

    def __init__(self):
        from cms.models import ArticlePage, CmsCategory, ContentPage, SectionPage

        self.pages = []
        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.live():
                self.pages.append({
                    'page': page, 'cle': cle(page.slug), 'slug': page.slug,
                    'section': page.section_slug,
                    'date': getattr(page, 'publication_date', None),
                })
        self.par_cle = defaultdict(list)
        for p in self.pages:
            self.par_cle[p['cle']].append(p)

        self.sections = {}
        self.domaines = {}
        for s in SectionPage.objects.all():
            self.sections[s.slug] = s
            if s.legacy_site_slug:
                self.sections.setdefault(s.legacy_site_slug, s)
            if s.custom_domain:
                self.domaines[s.custom_domain.lower()] = s
        # Titres SPIP qui ont eu des homonymes : renseigné par la commande.
        self.titres_en_double = set()
        self.categories = defaultdict(list)
        for c in CmsCategory.objects.all():
            self.categories[c.slug].append(c)


def titre_spip(segment):
    """Le titre d'une adresse SPIP, sans son numéro de dédoublonnage."""
    return cle(SUFFIXE_SPIP.sub('', segment.rstrip('.')))


def choisir(candidats, section_preferee):
    """Un seul candidat, ou le même slug publié par plusieurs syndicats."""
    if not candidats:
        return None
    if len({c['page'].pk for c in candidats}) == 1:
        return candidats[0]['page']
    if len({c['slug'] for c in candidats}) > 1:
        return None
    for section in (section_preferee, 'principal'):
        retenus = [c for c in candidats if c['section'] == section]
        if len(retenus) == 1:
            return retenus[0]['page']
    return None


def resoudre(adresse, citant, index, inventaire):
    """Retourne (famille, nouvelle adresse ou None, détail pour le rapport).

    `nouvelle adresse` peut être un chemin de fichier à verser : on la rend
    alors sous la forme ('fichier', chemin).
    """
    morceaux = urlsplit(html.unescape(adresse))
    hote = morceaux.hostname or ''
    segments = [unquote(s) for s in morceaux.path.split('/') if s]
    section_citant = getattr(citant, 'section_slug', None)
    date_citant = getattr(citant, 'publication_date', None)

    if segments and COURRIEL.match(segments[-1]):
        return 'courriel', f'mailto:{segments[-1]}', ''

    if 'IMG' in segments[:-1] and segments[-1]:
        fichiers = inventaire.par_cle.get(cle(segments[-1]), [])
        if fichiers and len({inventaire.empreinte(f) for f in fichiers}) == 1:
            return 'fichier_spip', ('fichier', fichiers[0]), os.path.relpath(fichiers[0], inventaire.racine)
        return 'fichier_spip', None, f'{len(fichiers)} fichier(s) de ce nom'

    if 'category' in segments:
        section = index.sections.get(segments[0]) if segments[0] != 'category' else None
        slugs = section.slugs_contenu if section else ['principal']
        trouvees = [c for c in index.categories.get(segments[-1], []) if c.section_slug in slugs]
        if len(trouvees) == 1:
            return 'categorie', trouvees[0].get_absolute_url(), ''
        return 'categorie', None, f'{len(trouvees)} catégorie(s)'

    if 'spip.php' in segments or not segments:
        return 'irreparable', None, ''

    # Le syndicat désigné par l'adresse : un préfixe de chemin ou un domaine.
    section_adresse = index.domaines.get(hote)
    if len(segments) == 2 and segments[0] in index.sections:
        section_adresse = index.sections[segments[0]]
        segments = segments[1:]
    if len(segments) != 1:
        return 'irreparable', None, ''
    segment = segments[0].rstrip('.')
    preferee = section_adresse.slug if section_adresse else section_citant

    def plausibles(candidats):
        return [c for c in candidats
                if c['page'].pk != getattr(citant, 'pk', None)
                and not (c['date'] and date_citant and c['date'] > date_citant + DELAI_REDATATION)]

    # Un titre SPIP garde ses majuscules ; un slug WordPress n'en a jamais.
    spip = any(ch.isupper() for ch in segment)
    famille = 'spip' if spip else 'wordpress'
    if spip and titre_spip(segment) in index.titres_en_double:
        return famille, None, 'titre SPIP en double'

    exacts = plausibles(index.par_cle.get(cle(segment), []))
    if exacts:
        page = choisir(exacts, preferee)
        return (famille, page.get_absolute_url() if page else None,
                ' | '.join(sorted({c['slug'] for c in exacts}))[:300])

    if spip:
        debut = titre_spip(segment)
        if len(debut) < PREFIXE_MINIMUM:
            return 'spip', None, 'titre trop court'
        candidats = plausibles([p for p in index.pages if p['cle'].startswith(debut)])
        page = choisir(candidats, preferee)
        return ('spip', page.get_absolute_url() if page else None,
                ' | '.join(sorted({c['slug'] for c in candidats}))[:300])

    return 'wordpress', None, ''


class Command(BaseCommand):
    help = "Répare les liens internes des articles qui répondent en erreur"

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Enregistre et publie. Sans cette option, rien n'est écrit.",
        )
        parser.add_argument(
            '--delier', action='store_true',
            help="Retire les liens qu'on ne sait pas réparer, en gardant leur texte",
        )
        parser.add_argument('--rapport', default=None, help="Fichier CSV : un lien par ligne")

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        appliquer = options['appliquer']
        delier = options['delier']
        if delier:
            self.stdout.write(self.style.WARNING(
                "Les liens non réparables seront retirés (leur texte reste).\n"))
        if not appliquer:
            self.stdout.write(self.style.WARNING("Simulation : rien ne sera enregistré.\n"))

        # 1. Les liens internes de chaque page.
        pages = []
        adresses = set()
        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.all():
                brut = json.dumps(list(page.body.raw_data), ensure_ascii=False)
                trouvees = [a for a in LIEN.findall(brut)
                            if 'wp-content/' not in a and '/media/' not in a]
                if trouvees:
                    pages.append((page, brut, trouvees))
                    adresses.update(trouvees)

        # 2. Lesquels répondent réellement en erreur.
        statuts = {a: statut_http(html.unescape(a)) for a in sorted(adresses)}
        morts = {a for a, s in statuts.items() if s is not None and s >= 400}
        injoignables = sum(1 for s in statuts.values() if s is None)
        self.stdout.write(f"  liens internes distincts : {len(adresses)}, en erreur : {len(morts)}"
                          + (f", injoignables (ignorés) : {injoignables}" if injoignables else ""))

        index = Index()
        for adresse in morts:
            dernier = unquote(urlsplit(html.unescape(adresse)).path.rstrip('/').rsplit('/', 1)[-1]).rstrip('.')
            if any(ch.isupper() for ch in dernier) and SUFFIXE_SPIP.search(dernier):
                index.titres_en_double.add(titre_spip(dernier))
        inventaire = Inventaire(os.path.join(racine_legacy(), 'wp-content', 'uploads'))
        stats = Counter()
        documents = {}
        lignes = []
        pages_modifiees = 0

        # 3. Réparer page par page.
        for page, brut, trouvees in pages:
            nouveau = brut
            repares = 0
            brouillon = page.has_unpublished_changes
            for adresse in dict.fromkeys(a for a in trouvees if a in morts):
                famille, cible, detail = resoudre(adresse, page, index, inventaire)
                if isinstance(cible, tuple):
                    document = document_pour(cible[1], page.section_slug, appliquer, documents, stats)
                    cible = document.url if document else '/documents/(à verser)'
                statut = 'repare' if cible else 'laisse'
                # Une page qui porte un brouillon non publié n'est pas à nous.
                # Le rapport doit le dire : sans ce `or delier`, un lien laissé
                # pour cette raison se lisait « laissé », comme un lien qu'on
                # n'a pas su traiter (relevé le 17/09/2026 sur la page 113).
                if brouillon and (cible or delier):
                    statut = 'brouillon'
                elif not cible and delier:
                    nouveau, retires = delie(nouveau, adresse)
                    if retires:
                        statut = 'delie'
                        repares += retires
                stats[f'{famille}:{statut}'] += 1
                lignes.append({
                    'page': page.pk, 'titre': page.title, 'adresse_page': page.url or '',
                    'lien': html.unescape(adresse), 'code': statuts[adresse],
                    'famille': famille, 'statut': statut, 'cible': cible or '', 'detail': detail,
                })
                if statut == 'repare':
                    nouveau = nouveau.replace(f'href=\\"{adresse}\\"', f'href=\\"{cible}\\"')
                    repares += 1

            if not repares:
                continue
            pages_modifiees += 1
            if not appliquer:
                continue
            page.body = json.loads(nouveau)
            revision = page.save_revision(log_action=True)
            # Une page hors ligne reste hors ligne : on ne publie que ce qui l'était.
            if page.live:
                revision.publish()

        self.stdout.write(f"  pages {'modifiées' if appliquer else 'à modifier'} : {pages_modifiees}\n")
        familles = ('spip', 'wordpress', 'categorie', 'fichier_spip', 'courriel', 'irreparable')
        self.stdout.write(f"    {'famille':<14}{'réparés':>9}{'déliés':>9}{'laissés':>9}{'brouillon':>11}")
        for f in familles:
            if any(stats[f'{f}:{s}'] for s in ('repare', 'delie', 'laisse', 'brouillon')):
                self.stdout.write(f"    {f:<14}{stats[f + ':repare']:>9}{stats[f + ':delie']:>9}"
                                  f"{stats[f + ':laisse']:>9}{stats[f + ':brouillon']:>11}")
        if stats['documents_crees'] or stats['documents_reutilises']:
            self.stdout.write(f"    documents {'versés' if appliquer else 'à verser'} : "
                              f"{stats['documents_crees']}, réutilisés : {stats['documents_reutilises']}")

        if options['rapport']:
            champs = ['page', 'titre', 'adresse_page', 'lien', 'code', 'famille', 'statut', 'cible', 'detail']
            with open(options['rapport'], 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=champs)
                w.writeheader()
                w.writerows(lignes)
            self.stdout.write(f"\n  rapport : {options['rapport']} ({len(lignes)} lignes)")
