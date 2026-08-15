"""Range les articles dans les catégories de leur syndicat, et repointe les
entrées de menu visant un doublon vide.

Constat de l'audit du 05/08/2026 : 14 entrées de menu mènent à une liste vide,
sur quatre sites. Deux causes distinctes, deux remèdes.

**STUCS** est le seul syndicat dont AUCUN article ne porte de catégorie locale :
ses 31 articles portent des catégories confédérales — ce qui est voulu, c'est
ce qui les fait paraître dans les rubriques du site national. Ses 8 catégories
propres sont donc vides. On ajoute l'étiquette locale SANS retirer la
confédérale : un article peut porter les deux.

Seuls 6 articles sur 31 reçoivent une étiquette : les autres sont des
communiqués, et ranger 24 articles sur 31 dans « Communiqués » ne ferait pas
naviguer — ce serait la page Ressources complète sous un autre nom. Les
catégories qui restent vides sont conservées à la demande d'Arnaud : elles
seront alimentées plus tard.

**Le 13** a des doublons créés à l'import : le menu vise une catégorie vide
alors que la vraie, remplie, est juste à côté. On repointe l'entrée.

La commande est idempotente : relancée, elle n'ajoute rien.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, CmsCategory
from content.models import MenuItem

# Article (pk) → catégorie STUCS à ajouter. Les pk figent le classement validé
# le 05/08/2026 : un titre peut changer, la ligne visée non.
ETIQUETTES_STUCS = {
    40: ('greve', "Grève des intermittent·es sur le montage du show au 6MIC"),
    51: ('greve', "BLOQUONS TOUT ! Appel à la grève générale du 10 septembre"),
    330: ('greve', "À Disneyland Paris, ce sont les grévistes qui paradent"),
    35: ('antifascisme', "Maurras n'est pas mort — contre le spectacle Historock"),
    42: ('antifascisme', "Contre Sterin et son monde, bloquons les nuits du bien commun"),
    57: ('videos', "Le Management Culturel Prend un Coup de Chaud — vidéo du STUCS"),
}

# Site → { catégorie vide visée par le menu : catégorie remplie à viser }
REPOINTAGES = {
    '13': {
        'commerce-et-services': 'revendiquons-commerce-et-services',
        'transports': 'actualites-luttes-transports',
        'permanences-syndicales': 'infos-dates-des-permanences',
    },
}


class Command(BaseCommand):
    help = ("Étiquette les articles STUCS et repointe les entrées de menu "
            "visant un doublon vide.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        self.n = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))
        with transaction.atomic():
            self._etiqueter_stucs(sec)
            self._repointer_menus(sec)
            if sec:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f'\n{self.n} changement(s).'))

    def _agir(self, message, action, sec):
        self.n += 1
        self.stdout.write(f'  {"[simulé] " if sec else ""}{message}')
        if not sec:
            action()

    # ── STUCS : ajouter l'étiquette locale, garder la confédérale ────────────

    def _etiqueter_stucs(self, sec):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'STUCS — étiquettes locales (les confédérales sont conservées)'))
        touche = False
        for pk, (slug_cat, libelle) in ETIQUETTES_STUCS.items():
            article = ArticlePage.objects.filter(pk=pk, section_slug='stucs').first()
            if article is None:
                self.stdout.write(self.style.WARNING(
                    f'  ? article pk={pk} introuvable chez STUCS : ignoré'))
                touche = True
                continue
            cat = CmsCategory.objects.filter(slug=slug_cat, section_slug='stucs').first()
            if cat is None:
                self.stdout.write(self.style.WARNING(
                    f'  ? catégorie {slug_cat!r} absente chez STUCS : ignoré'))
                touche = True
                continue
            if article.cms_categories.filter(pk=cat.pk).exists():
                continue    # déjà fait
            # Garde-fou repris de `promote_body_images` : republier une page
            # qui a un brouillon en attente mettrait en ligne des
            # modifications non validées.
            if article.has_unpublished_changes:
                self.stdout.write(self.style.WARNING(
                    f'  ? {article.title[:40]!r} a un brouillon en attente : ignoré'))
                touche = True
                continue

            def etiqueter(article=article, cat=cat):
                # `cms_categories` est un ParentalManyToManyField : `add()` ne
                # touche que le cluster en mémoire. Sans `save()`, rien n'est
                # écrit ; sans révision publiée, la prochaine publication du
                # brouillon effacerait l'étiquette.
                article.cms_categories.add(cat)
                article.save()
                article.save_revision().publish()

            avant = [c.slug for c in article.cms_categories.all()]
            self._agir(f'{slug_cat:14} ← {libelle[:52]}\n'
                       f'                   (garde {", ".join(avant) or "aucune"})',
                       etiqueter, sec)
            touche = True
        if not touche:
            self.stdout.write('  rien à faire')

    # ── Menus visant un doublon vide ─────────────────────────────────────────

    def _repointer_menus(self, sec):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nEntrées de menu visant un doublon vide"))
        touche = False
        for slug_site, paires in REPOINTAGES.items():
            for slug_vide, slug_plein in paires.items():
                vide = CmsCategory.objects.filter(
                    slug=slug_vide, section_slug=slug_site).first()
                plein = CmsCategory.objects.filter(
                    slug=slug_plein, section_slug=slug_site).first()
                if vide is None or plein is None:
                    self.stdout.write(self.style.WARNING(
                        f'  ? {slug_site} : {slug_vide!r} ou {slug_plein!r} '
                        f'introuvable, laissé tel quel'))
                    touche = True
                    continue
                # Filet : ne jamais repointer vers une catégorie elle aussi vide.
                n = ArticlePage.objects.live().filter(
                    cms_categories=plein, section_slug=slug_site).count()
                if n == 0:
                    self.stdout.write(self.style.WARNING(
                        f'  ? {slug_plein!r} est vide elle aussi : laissé tel quel'))
                    touche = True
                    continue
                for item in MenuItem.objects.filter(category=vide, site__slug=slug_site):
                    def repointer(item=item, plein=plein):
                        item.category = plein
                        item.save(update_fields=['category'])

                    self._agir(f'{item.title!r} ({slug_site}) : {slug_vide} '
                               f'→ {slug_plein} ({n} article(s))', repointer, sec)
                    touche = True
        if not touche:
            self.stdout.write('  rien à faire')
