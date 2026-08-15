"""Donne un extrait aux articles qui n'en ont pas.

Constat du 15/08/2026 : **1677 articles sur 1785** n'avaient pas d'extrait. Il
sert le texte des cartes dans les listes, les métadonnées de référencement et
le corps des newsletters — sans lui, une carte s'affiche sans un mot de
présentation.

Arnaud a demandé de l'appliquer aussi aux articles déjà en ligne. C'est le seul
changement de la journée qui **modifie du contenu public existant**, d'où trois
précautions :

- on n'écrase jamais un extrait saisi à la main ;
- on n'écrit que sur `excerpt`, sans créer de révision ni republier ;
- on épargne les pages ayant un brouillon en attente, comme
  `promote_body_images` et `repare_richtext_illisible`.

Le texte est repris du début de l'article, blocs `html` hérités de WordPress
compris — sans quoi les 1060 articles importés resteraient sans extrait.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, extrait_depuis_corps


class Command(BaseCommand):
    help = "Renseigne l'extrait des articles qui n'en ont pas."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")
        parser.add_argument('--limit', type=int, default=None,
                            help="S'arrêter après N articles.")
        parser.add_argument('--section', default=None,
                            help="Ne traiter qu'un syndicat (slug Wagtail).")

    def handle(self, *args, **options):
        sec = options['dry_run']
        limite, section = options['limit'], options['section']
        self.n = self.vides = self.brouillons = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))

        qs = ArticlePage.objects.filter(excerpt='')
        if section:
            qs = qs.filter(section_slug=section)

        with transaction.atomic():
            for article in qs.iterator():
                if limite is not None and self.n >= limite:
                    break
                self._traiter(article, sec)
            if sec:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'\n{self.n} extrait(s) posé(s), {self.vides} sans texte '
            f'exploitable, {self.brouillons} avec brouillon en attente.'))

    def _traiter(self, article, sec):
        if article.has_unpublished_changes:
            self.brouillons += 1
            return

        extrait = extrait_depuis_corps(article.body)
        if not extrait:
            # Article fait d'images seules, ou corps vide : rien à reprendre.
            # On le compte plutôt que de le taire, c'est une donnée utile.
            self.vides += 1
            return

        self.n += 1
        self.stdout.write(
            f"  {'[simulé] ' if sec else ''}{article.title[:44]:46} "
            f'→ {extrait[:60]}…')
        if not sec:
            # `excerpt` seul : pas de révision, pas de republication. Le corps
            # de l'article n'est pas touché.
            ArticlePage.objects.filter(pk=article.pk).update(excerpt=extrait)
