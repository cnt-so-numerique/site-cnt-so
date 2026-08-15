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

# La rubrique des branches professionnelles s'appelle « Secteurs » en
# production ; la base de développement l'a encore sous son ancien nom
# « Syndicats ». D'où plusieurs noms acceptés, le premier trouvé gagne : la
# commande doit tourner des deux côtés, et survivre à un renommage sans qu'on
# ait à la modifier. Le premier `--dry-run` en prod a buté là-dessus.
RUBRIQUE_SECTEURS = ('Secteurs', 'Syndicats')

# Une ligne par entrée à créer. `ordre` est un souhait : si la place est déjà
# prise chez les frères, l'entrée va à la fin plutôt que d'en bousculer une.
ENTREES = [
    {
        'site': 'principal',
        'rubrique': RUBRIQUE_SECTEURS,
        'categorie': 'travailleur-euses-de-la-terre',
        'libelle': 'Travailleurs et Travailleuses de la Terre',
        'ordre': 13,
    },
    # Les trois autres branches que rien ne desservait (relevé du 15/08/2026).
    # La coquille d'import est dans le slug seul — `animation-education-
    # popuplaire` — et on ne le renomme pas : c'est l'adresse publique de ses
    # 6 articles. Le nom de la catégorie, lui, est correct en production.
    {
        'site': 'principal',
        'rubrique': RUBRIQUE_SECTEURS,
        'categorie': 'animation-education-popuplaire',
        'libelle': 'Animation & Éducation populaire',
        'ordre': 17,
    },
    {
        'site': 'principal',
        'rubrique': RUBRIQUE_SECTEURS,
        'categorie': 'institutions-financieres-et-assurances',
        'libelle': 'Institutions financières & Assurances',
        'ordre': 18,
    },
    {
        'site': 'principal',
        'rubrique': RUBRIQUE_SECTEURS,
        'categorie': 'interim',
        'libelle': 'Intérim',
        'ordre': 19,
    },
]


# Doublons vides à supprimer, confirmés à la main. La commande vérifie
# elle-même que la catégorie est bien inerte : au moindre article, sous-
# catégorie ou entrée de menu accrochée, elle refuse et le dit.
#
# Table vide, et c'est un résultat, pas un oubli. Le seul candidat —
# « Syndicat national des transports et de l'aménagement du territoire »,
# 0 article — a été retiré le 15/08/2026 : ses 0 article ne faisaient pas de
# lui un doublon de « Transport – Logistique » mais son PARENT. Le contrôle
# d'inertie l'a arrêté sur les données réelles. `parent` étant en SET_NULL, la
# suppression n'aurait rien levé : elle aurait détaché la fille de la
# hiérarchie Syndicalisme, sans un mot.
DOUBLONS = []


class Command(BaseCommand):
    help = ("Ajoute au menu les catégories qui n'y figurent pas, et supprime "
            "les doublons vides confirmés.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        self.n = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))
        self.supprimees = 0
        with transaction.atomic():
            for entree in ENTREES:
                self._traiter(entree, sec)
            for doublon in DOUBLONS:
                self._supprimer(doublon, sec)
            if sec:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            f'\n{self.n} entrée(s) créée(s), '
            f'{self.supprimees} doublon(s) supprimé(s).'))

    def _refus(self, message):
        self.stdout.write(self.style.WARNING(f'  ? {message}'))

    def _traiter(self, entree, sec):
        libelle = entree['libelle']
        self.stdout.write(self.style.MIGRATE_HEADING(f"{libelle} → {entree['site']}"))

        site = SectionPage.objects.filter(slug=entree['site']).first()
        if site is None:
            return self._refus(f"site {entree['site']!r} introuvable : ignoré")

        noms = entree['rubrique']
        if isinstance(noms, str):
            noms = (noms,)
        rubrique = None
        for nom in noms:                 # premier trouvé, dans l'ordre donné
            rubrique = MenuItem.objects.filter(
                site=site, title=nom, parent__isnull=True, menu='main').first()
            if rubrique is not None:
                break
        if rubrique is None:
            return self._refus(
                f"aucune rubrique {' / '.join(map(repr, noms))} dans le menu "
                f"principal de {site.slug} : ignoré")

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

    # ── Doublons vides ───────────────────────────────────────────────────────

    def _supprimer(self, doublon, sec):
        """Supprime une catégorie confirmée doublon, à condition qu'elle soit
        réellement inerte.

        Les trois contrôles ne sont pas décoratifs : `MenuItem.category` est en
        `on_delete=SET_NULL`, donc supprimer une catégorie encore visée par un
        menu ne lève rien — elle vide le lien en silence, exactement la panne
        que `fix_menus_morts` a passé un mois à réparer. Et `cms_categories`
        étant un M2M, un article étiqueté ne bloque pas non plus la suppression :
        il perdrait juste son rangement.
        """
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Doublon de « {doublon['doublon_de']} » : {doublon['categorie']}"))

        site = SectionPage.objects.filter(slug=doublon['site']).first()
        if site is None:
            return self._refus(f"site {doublon['site']!r} introuvable : ignoré")

        cat = CmsCategory.objects.filter(
            slug=doublon['categorie'],
            section_slug__in=site.slugs_contenu).first()
        if cat is None:
            return self.stdout.write('  déjà supprimée')

        # `live()` ne suffirait pas : un brouillon ou une page dépubliée compte
        # tout autant, on ne veut pas détacher un contenu qui reviendra.
        articles = ArticlePage.objects.filter(cms_categories=cat).count()
        menus = MenuItem.objects.filter(category=cat).count()
        enfants = CmsCategory.objects.filter(parent=cat).count()
        obstacles = []
        if articles:
            obstacles.append(f'{articles} article(s)')
        if menus:
            obstacles.append(f'{menus} entrée(s) de menu')
        if enfants:
            obstacles.append(f'{enfants} sous-catégorie(s)')
        if obstacles:
            return self._refus('pas inerte (' + ', '.join(obstacles)
                               + ') : conservée, à trancher à la main')

        self.supprimees += 1
        self.stdout.write(f"  {'[simulé] ' if sec else ''}supprimée "
                          f"(0 article, 0 menu, 0 sous-catégorie)")
        if not sec:
            cat.delete()
