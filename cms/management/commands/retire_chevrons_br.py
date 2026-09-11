"""Retire les « > » semés après chaque saut de ligne par la réparation du 15/08.

Arnaud, 11/09/2026 : « je vois des > partout ». `repare_richtext_illisible`
voulait fermer les `<br>` laissés par l'import en `<br/>` ; son expression ne
remplaçait que les trois caractères `<br` et laissait le `>` d'origine :
`<br>` devenait `<br/>>`, et le lecteur voyait un « > » en tête de chaque
ligne. Son test vérifiait que le texte restait présent, jamais qu'il restait
exact — `Avant<br/>>Après` contient bien « Avant » et « Après ».

Mesuré en production le 11/09/2026 : **1 486 occurrences sur 261 pages**, une
seule forme, `<br/>>`. Elle n'est jamais légitime : Wagtail stocke un « > » de
texte en `&gt;` ; un `>` nu juste après une balise ne peut venir que de ce
défaut. La réparation remplace donc cette forme exacte, rien d'autre.

    python manage.py retire_chevrons_br --dry-run
    python manage.py retire_chevrons_br

La dernière révision est corrigée aussi quand elle porte le défaut (deux pages
en production) : sans quoi une publication depuis l'éditeur le réintroduirait.
Idempotente. Une page à brouillon en attente est laissée de côté : la corriger
publierait le travail non validé de quelqu'un d'autre.
"""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, ContentPage

DEFAUT = '<br/>>'
CORRIGE = '<br/>'
# Seconde forme, relevée une seule fois (page 1107) : un paragraphe réduit au
# seul « > ». Même raisonnement — un « > » tapé serait stocké `&gt;` —, et le
# paragraphe, vide une fois le chevron ôté, disparaît avec lui.
PARAGRAPHE_CHEVRON = '<p>></p>'


def repare(texte):
    """(texte réparé, nombre de « > » retirés)."""
    n = texte.count(DEFAUT) + texte.count(PARAGRAPHE_CHEVRON)
    return texte.replace(DEFAUT, CORRIGE).replace(PARAGRAPHE_CHEVRON, ''), n


class Command(BaseCommand):
    help = "Retire les « > » parasites laissés après les sauts de ligne (<br/>>)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        pages = occurrences = revisions = ignorees = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))

        with transaction.atomic():
            for modele in (ArticlePage, ContentPage):
                for page in modele.objects.all():
                    # `raw_data` est une vue sur une page relue en base : list()
                    # avant json.dumps (cf. normalise_urls_heritees, 11/09).
                    brut = json.dumps(list(page.body.raw_data), ensure_ascii=False)
                    repare_, n = repare(brut)
                    if not n:
                        continue
                    if page.has_unpublished_changes:
                        ignorees += 1
                        self.stdout.write(self.style.WARNING(
                            f'  ? {page.title[:50]!r} a un brouillon en attente : ignorée'))
                        continue
                    pages += 1
                    occurrences += n
                    if pages <= 10:
                        self.stdout.write(f"  {'[simulé] ' if sec else ''}"
                                          f"{page.title[:55]:57} {n} « > »")
                    if sec:
                        continue
                    page.body = json.loads(repare_)
                    # `body` seul : le contenu public est corrigé, rien n'est
                    # republié, aucune date de publication ne bouge.
                    page.save(update_fields=['body'])
                    revisions += self._corrige_revision(page)
            if sec:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'\n{pages} page(s), {occurrences} « > » retiré(s)'
            + ('' if sec else f', {revisions} révision(s) alignée(s)')
            + f', {ignorees} ignorée(s).'))
        if not pages and not ignorees:
            self.stdout.write('  rien à faire')

    def _corrige_revision(self, page):
        revision = page.latest_revision
        if revision is None or not isinstance(revision.content, dict):
            return 0
        contenu = revision.content
        corps = contenu.get('body')
        texte = corps if isinstance(corps, str) else json.dumps(corps, ensure_ascii=False)
        texte, n = repare(texte)
        if not n:
            return 0
        contenu['body'] = texte if isinstance(corps, str) else json.loads(texte)
        revision.content = contenu
        revision.save(update_fields=['content'])
        return 1
