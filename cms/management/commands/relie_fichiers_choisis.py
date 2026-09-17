"""
Relie les fichiers que `repare_liens_fichiers` n'a pas osé rapprocher seul.

Cette commande-là ne devine rien : elle applique des correspondances
**décidées par un humain**, une par ligne d'un fichier CSV — le nom nu resté
dans l'article, et le fichier de l'ancien serveur qui lui revient.

C'est le complément de `repare_liens_fichiers`, qui ne relie que le certain et
laisse le reste dans son rapport. Sur les 31 cas laissés le 14/09/2026, huit
avaient un fichier au nom presque identique (un suffixe ajouté par WordPress :
`…-4.pdf`, `…_rectifiee.pdf`, `…_v4.pdf`) : c'est ce qu'Arnaud a validé le
17/09/2026.

La correspondance porte sur le **nom**, pas sur un article : le même tract est
parfois cité par la copie d'un autre syndicat, et elle doit aussi retrouver son
fichier.

Format du CSV (les colonnes en trop sont ignorées) :

    nom;fichier
    Tract_DGH;sites/2/2014/02/tract_dgh_au_20_fevrier.pdf

`fichier` est un chemin **relatif à `legacy/wp-content/uploads/`**. Un fichier
absent arrête la commande : mieux vaut ne rien faire que relier à un vide.

Usage :
    python manage.py relie_fichiers_choisis --csv choix.csv            # simulation
    python manage.py relie_fichiers_choisis --csv choix.csv --appliquer
"""

import csv
import json
import os
import uuid
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from cms.conversion_html import racine_legacy, texte_riche_ouvrable
from cms.management.commands.repare_liens_fichiers import (
    NOM_NU, decoupe, document_pour,
)


def lit_correspondances(chemin, racine):
    """(nom nu → chemin absolu du fichier), ou une erreur si l'un manque."""
    with open(chemin, encoding='utf-8-sig', newline='') as f:
        echantillon = f.read(4096)
        f.seek(0)
        separateur = ';' if echantillon.count(';') > echantillon.count(',') else ','
        lignes = list(csv.DictReader(f, delimiter=separateur))

    correspondances = {}
    for ligne in lignes:
        nom = (ligne.get('nom') or '').strip()
        rel = (ligne.get('fichier') or '').strip()
        if not nom or not rel:
            continue
        fichier = os.path.join(racine, rel)
        if not os.path.isfile(fichier):
            raise CommandError(f"fichier introuvable pour « {nom} » : {fichier}")
        correspondances[nom] = fichier
    if not correspondances:
        raise CommandError(f"aucune correspondance lisible dans {chemin} "
                           "(colonnes attendues : nom, fichier)")
    return correspondances


class Command(BaseCommand):
    help = "Relie des fichiers à des noms nus, d'après des correspondances validées à la main"

    def add_arguments(self, parser):
        parser.add_argument('--csv', required=True, help="Fichier des correspondances (nom;fichier)")
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Enregistre et publie. Sans cette option, rien n'est écrit.",
        )

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        appliquer = options['appliquer']
        racine = os.path.join(racine_legacy(), 'wp-content', 'uploads')
        correspondances = lit_correspondances(options['csv'], racine)

        if not appliquer:
            self.stdout.write(self.style.WARNING("Simulation : rien ne sera enregistré.\n"))
        self.stdout.write(f"  {len(correspondances)} correspondance(s) lue(s)\n")

        stats = Counter()
        documents = {}
        pages_modifiees = 0
        vus = Counter()

        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.all():
                brut = list(page.body.raw_data)
                if not any(b['type'] == 'rich_text' and NOM_NU.search(b['value']) for b in brut):
                    continue
                brouillon = page.has_unpublished_changes
                nouveau, relies = [], 0

                for bloc in brut:
                    if bloc['type'] != 'rich_text':
                        nouveau.append(bloc)
                        continue
                    remplacements = []
                    for m in NOM_NU.finditer(bloc['value']):
                        fichier = correspondances.get(m.group(1))
                        if fichier is None:
                            continue
                        vus[m.group(1)] += 1
                        if brouillon:
                            stats['brouillon'] += 1
                            continue
                        document = document_pour(fichier, page.section_slug,
                                                 appliquer, documents, stats)
                        remplacements.append((m, {
                            'type': 'file',
                            'value': {'document': document.pk if document else None,
                                      'title': m.group(1)},
                            'id': str(uuid.uuid4()),
                        }))
                    if not remplacements:
                        nouveau.append(bloc)
                        continue
                    morceaux = decoupe(bloc['value'], remplacements)
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
                stats['relies'] += relies
                self.stdout.write(f"    {page.pk:>5}  {page.title[:58]:<58} {relies} lien(s)")
                if not appliquer:
                    continue
                page.body = json.loads(json.dumps(nouveau))
                revision = page.save_revision(log_action=True)
                # Une page hors ligne reste hors ligne.
                if page.live:
                    revision.publish()

        self.stdout.write("")
        self.stdout.write(f"  pages {'modifiées' if appliquer else 'à modifier'} : {pages_modifiees}")
        self.stdout.write(f"  liens reliés : {stats['relies']}")
        if stats['documents_crees'] or stats['documents_reutilises']:
            self.stdout.write(f"  documents {'versés' if appliquer else 'à verser'} : "
                              f"{stats['documents_crees']}, réutilisés : {stats['documents_reutilises']}")
        if stats['brouillon']:
            self.stdout.write(self.style.WARNING(
                f"  {stats['brouillon']} lien(s) ignoré(s) : brouillon en cours"))
        if stats['texte_non_ouvrable']:
            self.stdout.write(self.style.WARNING(
                f"  {stats['texte_non_ouvrable']} lien(s) ignoré(s) : texte non rouvrable"))

        jamais_vus = [nom for nom in correspondances if not vus[nom]]
        if jamais_vus:
            self.stdout.write(self.style.WARNING(
                f"  {len(jamais_vus)} nom(s) jamais rencontré(s) dans les articles :"))
            for nom in jamais_vus:
                self.stdout.write(f"    {nom}")
