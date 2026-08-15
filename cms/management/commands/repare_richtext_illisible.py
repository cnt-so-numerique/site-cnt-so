"""Répare le texte riche qu'un rédacteur ne peut pas ouvrir.

Constat du 15/08/2026 : **261 articles sur 1803 renvoyaient une erreur 500**
quand un rédacteur cliquait dessus pour les modifier. Le site public les
affichait parfaitement — le défaut ne vivait que dans le back-office, ce qui
explique qu'il ait tenu jusqu'ici sans être signalé.

Cause : l'import WordPress a laissé des `<br>` non fermés dans le texte riche.
L'analyseur de Wagtail qui convertit le HTML stocké vers l'éditeur Draftail
empile chaque balise ouvrante et attend sa fermeture ; il tombe alors sur
« Unmatched tags: expected br, got p » et la vue d'édition casse.

Le remède est la normalisation `<br>` → `<br/>`, vérifiée suffisante sur les
261 cas (aucun ne résiste). On ne touche qu'aux blocs `rich_text` dont la
conversion échoue réellement : un article lisible n'est jamais réécrit.

La commande est idempotente et refuse d'agir sur une page qui a un brouillon en
attente — republier mettrait en ligne des modifications non validées (même
garde-fou que `promote_body_images`).
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, ContentPage, RICHTEXT_FEATURES

# `<br>` non suivi de `/` ni d'une lettre — pour ne pas toucher `<br/>` déjà
# correct, ni un hypothétique `<break>`.
BALISE_BR_NUE = re.compile(r'<br(?![/a-zA-Z])')


class Command(BaseCommand):
    help = ("Répare les blocs de texte riche que l'éditeur ne sait pas ouvrir "
            "(erreur 500 à la modification).")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")
        parser.add_argument('--limit', type=int, default=None,
                            help="S'arrêter après N pages réparées.")

    def handle(self, *args, **options):
        from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
        self.conv = ContentstateConverter(RICHTEXT_FEATURES)
        sec = options['dry_run']
        limite = options['limit']
        self.n = self.ignores = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))
        with transaction.atomic():
            for modele in (ArticlePage, ContentPage):
                self._traiter_modele(modele, sec, limite)
            if sec:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            f'\n{self.n} page(s) réparée(s), {self.ignores} ignorée(s).'))

    def _lisible(self, page):
        """Vrai si tous les blocs de texte riche s'ouvrent dans l'éditeur."""
        try:
            for bloc in page.body:
                if bloc.block_type == 'rich_text':
                    self.conv.from_database_format(str(bloc.value))
            return True
        except Exception:
            return False

    def _traiter_modele(self, modele, sec, limite):
        self.stdout.write(self.style.MIGRATE_HEADING(modele.__name__))
        touche = False
        for page in modele.objects.all():
            if limite is not None and self.n >= limite:
                break
            if self._lisible(page):
                continue
            touche = True
            if page.has_unpublished_changes:
                self.ignores += 1
                self.stdout.write(self.style.WARNING(
                    f'  ? {page.title[:45]!r} a un brouillon en attente : ignoré'))
                continue

            corrige = 0
            for bloc in page.body:
                if bloc.block_type != 'rich_text':
                    continue
                avant = str(bloc.value)
                apres = BALISE_BR_NUE.sub('<br/>', avant)
                if apres != avant:
                    # RichText est immuable côté valeur : on réaffecte.
                    from wagtail.rich_text import RichText
                    bloc.value = RichText(apres)
                    corrige += 1

            if not corrige:
                # Illisible pour une autre raison que les `<br>` : ne pas
                # bricoler à l'aveugle, le signaler pour examen.
                self.ignores += 1
                self.stdout.write(self.style.WARNING(
                    f'  ? {page.title[:45]!r} illisible mais aucun <br> nu : '
                    f'à examiner à la main'))
                continue

            if not self._lisible(page):
                self.ignores += 1
                self.stdout.write(self.style.WARNING(
                    f'  ? {page.title[:45]!r} toujours illisible après '
                    f'correction : laissé tel quel'))
                continue

            self.n += 1
            self.stdout.write(
                f"  {'[simulé] ' if sec else ''}{page.title[:52]:54} "
                f'({corrige} bloc(s))')
            if not sec:
                # `body` seul : pas de nouvelle révision ni de republication.
                # Le contenu public est identique — `<br>` et `<br/>` rendent
                # le même saut de ligne — c'est l'éditeur qu'on débloque.
                page.save(update_fields=['body'])
        if not touche:
            self.stdout.write('  rien à faire')
