"""
Rend leurs fichiers aux articles dont les liens de téléchargement ont été perdus.

Le premier import WordPress → EditorJS ne gardait que le texte des liens : un
paragraphe `<p><a href="…/cnt_so_tpe_2021_btp_25022021-2.pdf">cnt_so_tpe_2021_btp</a></p>`
est devenu `<p>cnt_so_tpe_2021_btp</p>`. Les reprises suivantes ont recopié ce
texte nu. Mesuré en production le 14/09/2026 : **205 articles, 256 liens**.

Les fichiers, eux, existent : les 1 302 documents de l'ancien serveur ont été
rapatriés le 14/09/2026 dans `legacy/wp-content/uploads/` (voir
`tasks/chantier-fichiers-perdus.md`). Chaque nom nu retrouvé devient un bloc
« Fichier à télécharger » — un document de la médiathèque, rangé dans la
collection du syndicat.

On ne relie que ce qui est **sûr** :

1. **miroir** — le lien d'origine est lu dans le miroir statique de l'ancien
   site principal (`archive-wp/cnt-so.org/<slug>/index.html`) : le texte du
   lien y est associé à son adresse exacte ;
2. **exact** — un seul fichier de l'ancien serveur porte ce nom (à la casse et
   à la ponctuation près), ou plusieurs copies au contenu identique ;
   et ce fichier n'a pas été envoyé *après* l'article.

Tout le reste est laissé tel quel et listé pour relecture humaine. Rapprocher
par début de nom se trompe : `tract_1er_mai.pdf` désignait le tract de 2021,
pas `Tract-1er-mai-2025.pdf` (mesuré le 14/09/2026).

Usage :
    python manage.py repare_liens_fichiers                      # simulation
    python manage.py repare_liens_fichiers --rapport liens.csv
    python manage.py repare_liens_fichiers --appliquer
"""

import csv
import hashlib
import json
import os
import re
import unicodedata
import uuid
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from cms.conversion_html import collection_du_syndicat, racine_legacy, texte_riche_ouvrable

EXTENSIONS_DOCUMENT = (
    'pdf', 'odt', 'ods', 'odp', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'mp3', 'mp4', 'ogg', 'wav', 'm4a', 'epub', 'rtf', 'txt',
)
EXTENSIONS_IMAGE = ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg')

# Un paragraphe dont tout le texte est un nom de fichier : pas d'espace, au
# moins un « _ » — c'est la signature des noms WordPress, et ce qui écarte les
# paragraphes d'un seul mot.
NOM_NU = re.compile(r'<p>\s*([A-Za-z0-9][A-Za-z0-9._\-]*_[A-Za-z0-9._\-]+)\s*</p>')

LIEN_DOCUMENT = re.compile(
    r'<a\s[^>]*href="([^"]+\.(?:' + '|'.join(EXTENSIONS_DOCUMENT) + r'))"[^>]*>([^<]*)</a>',
    re.IGNORECASE,
)

DATE_DOSSIER = re.compile(r'(?:^|/)(\d{4})/(\d{2})/[^/]+$')


def cle(nom):
    """Le nom sans extension, sans accents, casse ni ponctuation."""
    base = os.path.basename(nom)
    souche, ext = os.path.splitext(base)
    if ext.lstrip('.').lower() not in EXTENSIONS_DOCUMENT + EXTENSIONS_IMAGE:
        souche = base
    souche = unicodedata.normalize('NFKD', souche).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', souche.lower())


def empreinte(chemin):
    h = hashlib.sha1()
    with open(chemin, 'rb') as f:
        for morceau in iter(lambda: f.read(1 << 20), b''):
            h.update(morceau)
    return h.hexdigest()


class Inventaire:
    """Les documents rapatriés de l'ancien serveur, indexés par nom."""

    def __init__(self, racine):
        self.racine = racine
        self.par_cle = defaultdict(list)
        self._empreintes = {}
        for dossier, _, fichiers in os.walk(racine):
            for nom in fichiers:
                if nom.rsplit('.', 1)[-1].lower() in EXTENSIONS_DOCUMENT:
                    self.par_cle[cle(nom)].append(os.path.join(dossier, nom))
        for chemins in self.par_cle.values():
            chemins.sort()

    def __len__(self):
        return sum(len(c) for c in self.par_cle.values())

    def empreinte(self, chemin):
        if chemin not in self._empreintes:
            self._empreintes[chemin] = empreinte(chemin)
        return self._empreintes[chemin]

    def depuis_adresse(self, adresse):
        """Le fichier rapatrié qui correspond à une adresse WordPress."""
        if 'wp-content/uploads/' not in adresse:
            return None
        rel = adresse.split('wp-content/uploads/', 1)[1].split('?')[0].split('#')[0]
        chemin = os.path.join(self.racine, rel)
        return chemin if os.path.isfile(chemin) else None


def envoye_apres(chemin, date_article):
    """Vrai si le dossier WordPress du fichier est postérieur à l'article.

    WordPress range un envoi sous `AAAA/MM/` le mois où il est reçu : un fichier
    rangé après le mois de l'article ne peut pas être celui qu'il citait.
    """
    if date_article is None:
        return False
    m = DATE_DOSSIER.search(chemin.replace(os.sep, '/'))
    if not m:
        return False
    return (int(m.group(1)), int(m.group(2))) > (date_article.year, date_article.month)


def liens_du_miroir(racine_miroir, slug):
    """Texte du lien → adresse, lu dans la page d'origine de l'ancien site principal."""
    if not racine_miroir:
        return {}
    page = os.path.join(racine_miroir, slug, 'index.html')
    if not os.path.isfile(page):
        return {}
    with open(page, encoding='utf-8', errors='replace') as f:
        html = f.read()
    liens = {}
    for adresse, texte in LIEN_DOCUMENT.findall(html):
        liens.setdefault(cle(texte), adresse)
    return liens


def resoudre(nom, inventaire, liens_miroir, date_article):
    """Retourne (statut, fichier ou None, candidats)."""
    k = cle(nom)
    adresse = liens_miroir.get(k)
    if adresse:
        fichier = inventaire.depuis_adresse(adresse)
        if fichier:
            return 'miroir', fichier, [fichier]

    candidats = inventaire.par_cle.get(k, [])
    if not candidats:
        return 'introuvable', None, []
    plausibles = [c for c in candidats if not envoye_apres(c, date_article)]
    if not plausibles:
        return 'douteux', None, candidats
    if len({inventaire.empreinte(c) for c in plausibles}) == 1:
        return 'exact', plausibles[0], candidats
    return 'douteux', None, candidats


def decoupe(valeur, remplacements):
    """Coupe un texte riche autour des noms nus remplacés par des blocs fichier.

    `remplacements` : liste de (match, bloc_fichier) dans l'ordre du texte.
    """
    blocs, debut = [], 0
    for m, bloc in remplacements:
        avant = valeur[debut:m.start()]
        if avant.strip():
            blocs.append({'type': 'rich_text', 'value': avant, 'id': str(uuid.uuid4())})
        blocs.append(bloc)
        debut = m.end()
    reste = valeur[debut:]
    if reste.strip():
        blocs.append({'type': 'rich_text', 'value': reste, 'id': str(uuid.uuid4())})
    return blocs



def document_pour(fichier, section_slug, appliquer, cache, stats):
    """Le document de la médiathèque pour ce fichier, créé au besoin.

    Retrouvé par empreinte : un PDF déjà versé n'est jamais dupliqué. En
    simulation, rien n'est créé et la fonction rend None.
    """
    from django.core.files import File
    from wagtail.documents import get_document_model

    Document = get_document_model()
    h = empreinte(fichier)
    if h in cache:
        return cache[h]
    document = Document.objects.filter(file_hash=h).first()
    if document is not None:
        stats['documents_reutilises'] += 1
    else:
        stats['documents_crees'] += 1
        if appliquer:
            document = Document(
                title=os.path.splitext(os.path.basename(fichier))[0][:255],
                collection=collection_du_syndicat(section_slug),
                file_hash=h,
            )
            with open(fichier, 'rb') as f:
                document.file = File(f, name=os.path.basename(fichier))
                document.save()
    cache[h] = document
    return document


class Command(BaseCommand):
    help = "Remplace les noms de fichiers nus des articles par des blocs « Fichier à télécharger »"

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Enregistre et publie. Sans cette option, rien n'est écrit.",
        )
        parser.add_argument(
            '--miroir', default=os.path.join(str(settings.BASE_DIR), 'archive-wp', 'cnt-so.org'),
            help="Miroir statique de l'ancien site principal",
        )
        parser.add_argument('--rapport', default=None, help="Fichier CSV : un nom nu par ligne")

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        appliquer = options['appliquer']
        miroir = options['miroir'] if os.path.isdir(options['miroir']) else None
        racine = os.path.join(racine_legacy(), 'wp-content', 'uploads')
        inventaire = Inventaire(racine)

        if not appliquer:
            self.stdout.write(self.style.WARNING("Simulation : rien ne sera enregistré.\n"))
        self.stdout.write(f"  documents rapatriés : {len(inventaire)} sous {racine}")
        self.stdout.write(f"  miroir de l'ancien site : {miroir or 'absent'}\n")

        stats = Counter()
        lignes = []
        documents = {}
        pages_modifiees = 0

        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.all():
                brut = list(page.body.raw_data)
                if not any(b['type'] == 'rich_text' and NOM_NU.search(b['value']) for b in brut):
                    continue

                date_article = getattr(page, 'publication_date', None)
                liens = (liens_du_miroir(miroir, page.slug)
                         if page.section_slug == 'principal' else {})
                brouillon = page.has_unpublished_changes
                nouveau, relies = [], 0

                for bloc in brut:
                    if bloc['type'] != 'rich_text':
                        nouveau.append(bloc)
                        continue
                    remplacements = []
                    for m in NOM_NU.finditer(bloc['value']):
                        nom = m.group(1)
                        if nom.rsplit('.', 1)[-1].lower() in EXTENSIONS_IMAGE:
                            continue
                        statut, fichier, candidats = resoudre(nom, inventaire, liens, date_article)
                        if fichier and brouillon:
                            statut = 'brouillon'
                        stats[statut] += 1
                        lignes.append({
                            'page': page.pk, 'titre': page.title, 'adresse': page.url or '',
                            'nom': nom, 'statut': statut,
                            'fichier': os.path.relpath(fichier, racine) if fichier else '',
                            'candidats': ' | '.join(os.path.relpath(c, racine) for c in candidats[:5]),
                        })
                        if statut not in ('miroir', 'exact'):
                            continue
                        document = document_pour(fichier, page.section_slug, appliquer, documents, stats)
                        remplacements.append((m, {
                            'type': 'file',
                            'value': {'document': document.pk if document else None, 'title': nom},
                            'id': str(uuid.uuid4()),
                        }))
                    if not remplacements:
                        nouveau.append(bloc)
                        continue
                    morceaux = decoupe(bloc['value'], remplacements)
                    # Même garde que la conversion : un texte que l'éditeur ne
                    # sait pas rouvrir ferait une erreur 500 à « Modifier ».
                    if not all(texte_riche_ouvrable(b['value'])
                               for b in morceaux if b['type'] == 'rich_text'):
                        stats['texte_non_ouvrable'] += len(remplacements)
                        nouveau.append(bloc)
                        continue
                    nouveau.extend(morceaux)
                    relies += len(remplacements)

                if not relies:
                    continue
                pages_modifiees += 1
                if not appliquer:
                    continue
                page.body = json.loads(json.dumps(nouveau))
                revision = page.save_revision(log_action=True)
                # Une page hors ligne reste hors ligne : on ne publie que ce qui l'était.
                if page.live:
                    revision.publish()

        self.stdout.write(f"  pages {'modifiées' if appliquer else 'à modifier'} : {pages_modifiees}")
        libelles = {
            'miroir': "reliés d'après le miroir",
            'exact': "reliés par nom exact",
            'douteux': "douteux, laissés tels quels",
            'introuvable': "introuvables",
            'brouillon': "ignorés : brouillon en cours",
            'texte_non_ouvrable': "ignorés : texte non rouvrable",
            'documents_reutilises': "documents déjà en médiathèque",
            'documents_crees': "documents versés" if appliquer else "documents à verser",
        }
        for statut, libelle in libelles.items():
            if stats[statut]:
                self.stdout.write(f"    {stats[statut]:>4}  {libelle}")

        if options['rapport']:
            with open(options['rapport'], 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=list(lignes[0]) if lignes else ['page'])
                w.writeheader()
                w.writerows(lignes)
            self.stdout.write(f"\n  rapport : {options['rapport']} ({len(lignes)} lignes)")
