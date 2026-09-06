"""
Ramène les adresses de fichiers héritées de WordPress à des chemins relatifs.

Les corps d'articles importés de WordPress citent leurs images et leurs PDF par
une adresse absolue : `https://cnt-so.org//13/wp-content/uploads/…`,
`https://educ.cnt-so.org/wp-content/uploads/…`,
`https://testwp.cnt-so.org/auvergne/wp-content/uploads/…`. Trois hôtes, des
préfixes de sous-site variables, et parfois une double barre.

Ces adresses ont trois défauts :

1. **testwp.cnt-so.org ne sera jamais à nous.** C'est le domaine de recette de
   l'ancien hébergeur (5.196.74.69). Les 23 fichiers qu'il sert sont pourtant
   bien chez nous, dans `media/uploads/` : seule l'adresse écrite est mauvaise.
   Le jour où l'ancien serveur s'éteint, ces 23 visuels disparaissent.
2. **Elles dépendent d'un serveur tiers pendant la bascule.** Tant que le DNS
   n'a pas basculé, `cnt-so.org` désigne l'ancienne machine ; nos pages vont y
   chercher leurs images alors que les fichiers sont sous nos pieds.
3. **Elles figent un nom de domaine dans le contenu.** Un syndicat qui change de
   domaine emporte des liens qui pointent ailleurs.

Un chemin relatif `/media/uploads/…` règle les trois : il est servi par nginx
(règle `location /media/`) depuis n'importe quel domaine de la fédération.

Prudence : **une URL n'est réécrite que si le fichier existe sur le disque.**
Sans cette vérification, on transformerait une adresse qui fonctionne encore
chez l'ancien hébergeur en un lien mort chez nous. Les adresses sans fichier
correspondant sont listées et laissées telles quelles.

Usage :
    python manage.py normalise_urls_heritees --dry-run
    python manage.py normalise_urls_heritees --hote testwp.cnt-so.org
    python manage.py normalise_urls_heritees
"""

import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand

# Toute adresse absolue vers un dépôt d'envois WordPress, quel que soit l'hôte
# cnt-so.org et quels que soient les segments de sous-site qui précèdent.
MOTIF = re.compile(
    r'https?://(?P<hote>[a-z0-9.-]*cnt-so\.org)'   # l'hôte, avec ou sans sous-domaine
    r'(?P<prefixe>(?:/[^/\s"\']+)*?)'              # /13, /auvergne, // … ou rien
    r'/wp-content/uploads/'
    r'(?P<chemin>[^\s"\'<>)]+)'
)


class Command(BaseCommand):
    help = "Remplace les adresses WordPress absolues par des chemins /media/uploads/ relatifs"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Montre ce qui serait réécrit, sans rien enregistrer",
        )
        parser.add_argument(
            '--hote', default=None,
            help="Ne traiter que cet hôte (ex. testwp.cnt-so.org)",
        )

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        dry_run = options['dry_run']
        hote_filtre = options['hote']

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode essai : rien ne sera enregistré.\n"))

        racine = os.path.join(settings.MEDIA_ROOT, 'uploads')
        pages_modifiees = 0
        urls_reecrites = 0
        sans_fichier = {}
        ignorees_brouillon = []

        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.all().specific():
                brut = json.dumps(page.body.raw_data, ensure_ascii=False)

                trouvees = list(MOTIF.finditer(brut))
                if not trouvees:
                    continue

                nouveau = brut
                remplacees = 0
                for m in trouvees:
                    if hote_filtre and m.group('hote') != hote_filtre:
                        continue
                    chemin = m.group('chemin')
                    # Le chemin peut porter une ancre ou des paramètres : le
                    # fichier, lui, s'arrête avant.
                    fichier = chemin.split('?')[0].split('#')[0]
                    if not os.path.isfile(os.path.join(racine, fichier)):
                        sans_fichier.setdefault(m.group(0), 0)
                        sans_fichier[m.group(0)] += 1
                        continue
                    nouveau = nouveau.replace(m.group(0), f'/media/uploads/{chemin}')
                    remplacees += 1

                if not remplacees or nouveau == brut:
                    continue

                # Une page qui porte déjà des modifications non publiées n'est
                # pas à nous : la publier enverrait en ligne le brouillon de
                # quelqu'un d'autre. On la signale et on passe.
                if page.has_unpublished_changes:
                    ignorees_brouillon.append(page.title)
                    continue

                pages_modifiees += 1
                urls_reecrites += remplacees

                if dry_run:
                    if pages_modifiees <= 8:
                        self.stdout.write(f"  {page.title[:60]:<60} {remplacees} adresse(s)")
                    continue

                page.body = json.loads(nouveau)
                page.save()
                page.save_revision(log_action=True).publish()

        self.stdout.write("")
        self.stdout.write(f"  pages concernées : {pages_modifiees}")
        self.stdout.write(f"  adresses réécrites : {urls_reecrites}")

        if ignorees_brouillon:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(ignorees_brouillon)} page(s) ignorée(s) : brouillon non publié en cours"
            ))
            for t in ignorees_brouillon[:10]:
                self.stdout.write(f"    {t[:70]}")

        if sans_fichier:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(sans_fichier)} adresse(s) laissée(s) telles quelles : "
                f"aucun fichier correspondant sous {racine}"
            ))
            for u in list(sans_fichier)[:10]:
                self.stdout.write(f"    {u[:110]}")

        if not dry_run and pages_modifiees:
            self.stdout.write(self.style.SUCCESS("\n  Terminé."))
