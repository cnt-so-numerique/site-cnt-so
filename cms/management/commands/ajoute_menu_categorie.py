"""Ajoute au menu une catégorie qui n'y figure pas.

Le pendant de `fix_menus_morts` : celui-là traque les entrées qui ne mènent
nulle part, celle-ci les catégories qui existent, sont remplies, et qu'aucun
lien de navigation ne dessert. On n'y arrive alors qu'en cliquant l'étiquette
sous un article — autant dire jamais.

Constat du 15/08/2026 : « Travailleur-euses de la terre » (2 articles, les deux
numéros des *Croquants*) n'était atteignable par aucun menu, alors que ses
branches sœurs — Commerce, Industrie, Nettoyage… — figurent toutes sous
« Syndicats ».

La commande est idempotente : relancée, elle n'ajoute rien. Elle refuse de
deviner (site, rubrique ou catégorie introuvable : elle le dit et passe).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, CmsCategory, SectionPage
from content.models import MenuItem

# Une ligne par entrée à créer. `ordre` est un souhait : si la place est déjà
# prise chez les frères, l'entrée va à la fin plutôt que d'en bousculer une.
ENTREES = [
    {
        'site': 'principal',
        'rubrique': 'Syndicats',
        'categorie': 'travailleur-euses-de-la-terre',
        'libelle': 'Travailleurs et Travailleuses de la Terre',
        'ordre': 13,
    },
]


class Command(BaseCommand):
    help = "Ajoute au menu les catégories qui n'y figurent pas."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        self.n = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))
        with transaction.atomic():
            for entree in ENTREES:
                self._traiter(entree, sec)
            if sec:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f'\n{self.n} entrée(s) créée(s).'))

    def _refus(self, message):
        self.stdout.write(self.style.WARNING(f'  ? {message}'))

    def _traiter(self, entree, sec):
        libelle = entree['libelle']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{libelle} → {entree['site']} / {entree['rubrique']}"))

        site = SectionPage.objects.filter(slug=entree['site']).first()
        if site is None:
            return self._refus(f"site {entree['site']!r} introuvable : ignoré")

        rubrique = MenuItem.objects.filter(
            site=site, title=entree['rubrique'],
            parent__isnull=True, menu='main').first()
        if rubrique is None:
            return self._refus(
                f"rubrique {entree['rubrique']!r} absente du menu principal "
                f"de {site.slug} : ignoré")

        # `slugs_contenu` : un syndicat à slug hérité range ses contenus sous
        # l'un OU l'autre. Ne jamais filtrer sur le seul `slug` Wagtail.
        cat = CmsCategory.objects.filter(
            slug=entree['categorie'],
            section_slug__in=site.slugs_contenu).first()
        if cat is None:
            return self._refus(
                f"catégorie {entree['categorie']!r} absente de {site.slug} : ignoré")

        if MenuItem.objects.filter(site=site, parent=rubrique, category=cat).exists():
            return self.stdout.write('  déjà présente')

        freres = MenuItem.objects.filter(parent=rubrique)
        pris = set(freres.values_list('order', flat=True))
        ordre = entree['ordre']
        if ordre in pris:
            ordre = (max(pris) + 1) if pris else 0

        item = MenuItem(site=site, parent=rubrique, menu=rubrique.menu,
                        link_type='category', title=libelle, category=cat,
                        order=ordre, is_active=True)
        # `full_clean` fait passer par `MenuItem.clean`, qui refuse un lien
        # sans cible — le filet posé après les 8 impasses de l'audit.
        item.full_clean(exclude=['url'])

        n = ArticlePage.objects.live().filter(cms_categories=cat).count()
        self.n += 1
        self.stdout.write(
            f"  {'[simulé] ' if sec else ''}créée en position {ordre} "
            f"→ {cat.get_absolute_url()} ({n} article(s))")
        if n == 0:
            self._refus('la catégorie est vide : le lien mènera à une liste vide')
        if not sec:
            item.save()
