"""Rend modifiables les articles importés de WordPress.

Constat du 10/09/2026 : l'import range tout le contenu d'un article dans un
unique bloc « HTML brut (import legacy) ». Ce bloc est masqué du menu de
l'éditeur : le rédacteur qui ouvre un de ces articles tombe sur une zone de
code source. Il ne peut pas corriger une faute sans lire du HTML, ni déplacer
une image, ni insérer un encadré. C'est le cas des 51 articles repris le
06/09/2026, et de tout ce que l'import produira ensuite.

    python manage.py convertit_html_modifiable --dry-run          # inventaire
    python manage.py convertit_html_modifiable --section education
    python manage.py convertit_html_modifiable --limit 5          # prudence

La commande est idempotente : un article déjà converti n'a plus de bloc HTML à
traiter. Elle refuse d'agir sur une page qui a un brouillon en attente — la
republier mettrait en ligne des modifications non validées (même garde-fou que
`promote_body_images` et `repare_richtext_illisible`).

Ce qu'elle ne convertit pas, elle le dit : les morceaux gardés en HTML brut
(tableaux, vidéos) et les images introuvables en médiathèque sont comptés à la
fin. Aucun contenu n'est supprimé, jamais.
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from cms.conversion_html import html_vers_blocs
from cms.models import ArticlePage, ContentPage


class Command(BaseCommand):
    help = ("Convertit les blocs « HTML brut » hérités de WordPress en texte "
            "riche et en blocs image, pour que les rédacteurs puissent les "
            "modifier.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")
        parser.add_argument('--section', default=None,
                            help="Ne traiter qu'un syndicat (slug de section).")
        parser.add_argument('--slug', default=None,
                            help="Ne traiter qu'une page, par son slug.")
        parser.add_argument('--limit', type=int, default=None,
                            help="S'arrêter après N pages converties.")
        parser.add_argument('--publie-apres', default=None, metavar='AAAA-MM-JJ',
                            help="Ne traiter que les articles publiés après "
                                 "cette date — de quoi ne reprendre que le "
                                 "dernier lot importé sans toucher au fonds.")

    def handle(self, *args, **options):
        self.sec = options['dry_run']
        limite = options['limit']
        self.pages = 0
        self.ignorees = 0
        self.totaux = {'rich_text': 0, 'image': 0, 'html_conserve': 0,
                       'images_perdues': 0, 'widgets_retires': 0}

        if self.sec:
            self.stdout.write(self.style.WARNING(
                'MODE SIMULATION — aucune écriture\n'))

        with transaction.atomic():
            for modele in (ArticlePage, ContentPage):
                self._traite(modele, options, limite)
            if self.sec:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'\n{self.pages} page(s) convertie(s), {self.ignorees} ignorée(s).'))
        self.stdout.write(
            f"  {self.totaux['rich_text']} bloc(s) de texte modifiable, "
            f"{self.totaux['image']} bloc(s) image")
        if self.totaux['html_conserve']:
            self.stdout.write(self.style.WARNING(
                f"  {self.totaux['html_conserve']} morceau(x) gardé(s) en HTML "
                f"brut (tableau, vidéo ou balise non convertible)"))
        if self.totaux['widgets_retires']:
            self.stdout.write(
                f"  {self.totaux['widgets_retires']} greffon(s) WordPress inerte(s) "
                f"retiré(s) (aperçu PDF en doublon, script tiers bloqué par la "
                f"politique de sécurité)")
        if self.totaux['images_perdues']:
            self.stdout.write(self.style.WARNING(
                f"  {self.totaux['images_perdues']} image(s) introuvable(s) en "
                f"médiathèque, balise d'origine conservée"))

    def _traite(self, modele, options, limite):
        self.stdout.write(self.style.MIGRATE_HEADING(modele.__name__))
        qs = modele.objects.all()
        if options['publie_apres']:
            if not hasattr(modele, 'publication_date'):
                # Les pages statiques n'ont pas de date de publication : les
                # inclure dans un filtre de date reviendrait à toutes les
                # prendre, exactement ce que le filtre cherche à éviter.
                self.stdout.write('  ignoré (pas de date de publication)')
                return
            qs = qs.filter(publication_date__date__gte=options['publie_apres'])
        if options['section']:
            qs = qs.filter(section_slug=options['section'])
        if options['slug']:
            qs = qs.filter(slug=options['slug'])

        touche = False
        for page in qs.iterator():
            if limite is not None and self.pages >= limite:
                break
            if not any(b['type'] == 'html' for b in page.body.raw_data):
                continue
            touche = True

            if page.has_unpublished_changes:
                self.ignorees += 1
                self.stdout.write(self.style.WARNING(
                    f'  ? {page.title[:45]!r} a un brouillon en attente : ignoré'))
                continue

            nouveaux, stats = self._convertit(page)
            if nouveaux is None:
                self.ignorees += 1
                continue

            self.pages += 1
            for cle in self.totaux:
                self.totaux[cle] += stats[cle]
            self.stdout.write(
                f"  {'[simulé] ' if self.sec else ''}{page.title[:50]:52} "
                f"→ {stats['rich_text']} texte, {stats['image']} image"
                + (f", {stats['html_conserve']} HTML gardé"
                   if stats['html_conserve'] else ''))

            if not self.sec:
                page.body = json.dumps(nouveaux)
                # `body` seul : ni nouvelle révision, ni republication. Le
                # rendu public est le même HTML, c'est l'éditeur qu'on ouvre.
                page.save(update_fields=['body'])
                self._aligne_revision(page, nouveaux)

        if not touche:
            self.stdout.write('  rien à faire')

    def _convertit(self, page):
        """Nouveau `body`, ou (None, None) si la conversion n'apporte rien."""
        nouveaux = []
        stats = {'rich_text': 0, 'image': 0, 'html_conserve': 0,
                 'images_perdues': 0, 'widgets_retires': 0}
        change = False

        for bloc in page.body.raw_data:
            if bloc['type'] != 'html':
                nouveaux.append(bloc)
                continue
            produits, part = html_vers_blocs(bloc['value'])
            if not produits:
                # Rien de convertible : on garde le bloc d'origine intact.
                nouveaux.append(bloc)
                continue
            # Un seul bloc HTML rendu à l'identique : rien n'a été gagné.
            if len(produits) == 1 and produits[0]['type'] == 'html':
                nouveaux.append(bloc)
                stats['html_conserve'] += 1
                continue
            nouveaux.extend(produits)
            for cle in stats:
                stats[cle] += part[cle]
            change = True

        if not change:
            self.stdout.write(self.style.WARNING(
                f'  ? {page.title[:45]!r} : rien de convertible '
                f'(tableau ou HTML non reconnu), laissé tel quel'))
            return None, None
        return nouveaux, stats

    def _aligne_revision(self, page, nouveaux):
        """Si une révision existe, elle doit porter le même corps.

        L'éditeur ouvre la dernière révision quand il y en a une : corriger le
        seul objet vivant laisserait le rédacteur devant l'ancien bloc HTML, et
        sa republication écraserait la conversion.
        """
        revision = page.latest_revision
        if revision is None:
            return
        contenu = revision.content
        if isinstance(contenu, dict) and 'body' in contenu:
            contenu['body'] = json.dumps(nouveaux)
            revision.content = contenu
            revision.save(update_fields=['content'])
