"""Crée les quatre rubriques de lutte de l'Éducation et y range les articles.

Suite du rangement du 12/09/2026 (`range_categories_education`). Celui-ci avait
classé 23 articles dans les rubriques que le menu nommait déjà, et laissé
**60 articles** dans le seul fil « Actualités - Luttes » — à raison : ce sont
des appels à la grève et des communiqués, que ranger dans « Primaire » aurait
été faux.

Mais quatre thèmes y revenaient assez pour mériter leur rubrique. Créer une
rubrique étant une décision du syndicat, elle a été demandée puis accordée par
Arnaud le 12/09/2026 : « crée les 4 et mets-les bien dans le menu ».

Relecture titre par titre des 60, et pas un filtrage par mots-clés — celui-ci
m'avait donné quatre articles « antifascistes » en ramassant « réactionnaire »
et « répression antisyndicale », qui n'en sont pas.

    Austérité et budget              15 articles
    Militarisation – SNU              7
    Féminisme                         6
    Antifascisme et antiracisme       3

**Pourquoi « et antiracisme ».** L'antifascisme strict n'avait qu'UN article
incontestable. Deux autres — la loi Darmanin, la marche du 23 septembre — sont
de la même famille de luttes sans être du fascisme. Élargir le nom à ce que la
rubrique contient vraiment vaut mieux que bourrer un nom étroit avec des
articles qui n'en relèvent pas : le lecteur qui clique doit trouver ce que
l'étiquette annonce.

Un article peut porter deux rubriques : « Contre l'austérité et la
militarisation » est rangé dans les deux, parce qu'il parle des deux.

La commande **supprime aussi « Premiere Page »**, le résidu WordPress vidé le
12/09 — à condition de la trouver inerte, les trois contrôles étant refaits
ici : `MenuItem.category` est en `SET_NULL` et `cms_categories` est un M2M,
donc une suppression hâtive ne lèverait aucune erreur, elle viderait un lien ou
détacherait des articles en silence.

Le menu, lui, n'est pas de son ressort : `ajoute_menu_categorie` sait déjà
poser une entrée vers une rubrique, et c'est elle qui place les quatre sous
« Actualités – luttes ».

Usage :
    python manage.py cree_rubriques_luttes_education              # constat seul
    python manage.py cree_rubriques_luttes_education --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.rangement import aligne_revision, mots

SECTION = 'education'
RESIDU_WORDPRESS = 'premiere-page'

# (slug, nom affiché). Le slug est l'adresse publique : il se choisit une fois.
RUBRIQUES = [
    ('austerite-budget', 'Austérité et budget'),
    ('militarisation-snu', 'Militarisation – SNU'),
    ('feminisme', 'Féminisme'),
    ('antifascisme-antiracisme', 'Antifascisme et antiracisme'),
]

# (pk, fragment du titre, rubriques). Le fragment interdit d'écrire dans un
# article dont le `pk` aurait été réattribué par un import : sans lui, un
# réimport ferait ranger n'importe quoi n'importe où, en silence.
CLASSEMENT = [
    # ── Austérité et budget ──────────────────────────────────────────────────
    (1799, 'notre lutte est internationale', ['austerite-budget', 'militarisation-snu']),
    (1802, 'Budget austéritaire', ['austerite-budget']),
    (1814, '2 octobre : bloquons', ['austerite-budget']),
    (1815, 'préparons la grève du 18 septembre', ['austerite-budget']),
    (1819, 'Grève le 13 mai', ['austerite-budget']),
    (1820, 'politiques austéritaires', ['austerite-budget']),
    (1834, 'Budget 2025', ['austerite-budget']),
    (1835, 'veut la mort des services publics', ['austerite-budget']),
    (1846, 'Pour la défense de nos biens communs', ['austerite-budget']),
    (1847, 'amplifions le mouvement', ['austerite-budget']),
    (1848, 'plus autoritaire que jamais', ['austerite-budget']),
    (1850, 'Imposons le choc de la lutte', ['austerite-budget']),
    (1852, 'Encore et toujours', ['austerite-budget']),
    (1857, 'construisons un mouvement de grève massif', ['austerite-budget']),
    (1893, 'faire valser', ['austerite-budget']),
    # ── Militarisation – SNU ─────────────────────────────────────────────────
    (1800, 'embrigadement de la jeunesse', ['militarisation-snu']),
    (1807, 'Non à la marche à la guerre', ['militarisation-snu']),
    (1862, 'obsession du réarmement', ['militarisation-snu']),
    (1875, 'Sur le temps scolaire comme en dehors', ['militarisation-snu']),
    (1890, 'SNU sur le temps scolaire', ['militarisation-snu']),
    (1891, 'Communiqué du collectif Non au SNU', ['militarisation-snu']),
    # ── Féminisme ────────────────────────────────────────────────────────────
    (1803, '8 mars : journée internationale', ['feminisme']),
    (1813, 'ÉLIMINATION DE LA VIOLENCE', ['feminisme']),
    (1822, 'soyons massivement en grève féministe', ['feminisme']),
    (1823, '8 mars 2025 : grève féministe', ['feminisme']),
    (1832, 'contre les violences faites aux femmes', ['feminisme']),
    (1853, 'soyons toutes et tous en grève féministe', ['feminisme']),
    # ── Antifascisme et antiracisme ──────────────────────────────────────────
    (1843, 'Contre le fascisme', ['antifascisme-antiracisme']),
    (1858, 'contre la loi Darmanin', ['antifascisme-antiracisme']),
    (1876, 'Pas de justice, pas de paix', ['antifascisme-antiracisme']),
]


class Command(BaseCommand):
    help = ("Crée les quatre rubriques de lutte de l'Éducation, y range les "
            "articles, et supprime le résidu WordPress « Premiere Page »")

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit en base. Sans ce drapeau, la commande n'affiche que ce "
                 "qu'elle ferait.")

    def handle(self, *args, **options):
        self.appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Rubriques de lutte de l'Éducation — "
            + ("ÉCRITURE EN BASE" if self.appliquer
               else "constat seul (--appliquer pour écrire)")))

        # Les trois étapes écrivent POUR DE VRAI, y compris en constat : c'est
        # le `rollback` de la fin qui rend le constat blanc. Sans cela l'étape 2
        # ne verrait pas les rubriques créées par l'étape 1 — la leçon du
        # constat menteur du 12/09.
        with transaction.atomic():
            rubriques = self._cree_les_rubriques()
            self._range_les_articles(rubriques)
            self._supprime_le_residu()
            if not self.appliquer:
                transaction.set_rollback(True)

    # ── 1. les rubriques ─────────────────────────────────────────────────────

    def _cree_les_rubriques(self):
        from cms.models import CmsCategory

        self.stdout.write(self.style.MIGRATE_HEADING('\n1. Rubriques'))
        rubriques, crees = {}, 0
        for slug, nom in RUBRIQUES:
            rubrique = CmsCategory.objects.filter(
                section_slug=SECTION, slug=slug).first()
            if rubrique is None:
                rubrique = CmsCategory(section_slug=SECTION, slug=slug, name=nom)
                rubrique.save()
                crees += 1
                self.stdout.write(f'   créée   « {nom} »  ({slug})')
            else:
                self.stdout.write(f'   existe  « {rubrique.name} »  ({slug})')
            rubriques[slug] = rubrique
        self.stdout.write(f'   {crees} rubrique(s) créée(s)')
        return rubriques

    # ── 2. le classement ─────────────────────────────────────────────────────

    def _range_les_articles(self, rubriques):
        from cms.models import ArticlePage

        self.stdout.write(self.style.MIGRATE_HEADING('\n2. Classement'))
        ranges, ignores = 0, []
        comptes = {slug: 0 for slug, _ in RUBRIQUES}

        for pk, fragment, slugs in CLASSEMENT:
            page = ArticlePage.objects.filter(pk=pk, section_slug=SECTION).first()
            if page is None:
                ignores.append(f'pk={pk} introuvable dans {SECTION}')
                continue
            if mots(fragment) not in mots(page.title):
                ignores.append(
                    f'pk={pk} ne contient pas « {fragment} » — non touché')
                continue
            deja = {c.pk for c in page.cms_categories.all()}
            a_ajouter = [rubriques[s] for s in slugs
                         if s in rubriques and rubriques[s].pk not in deja]
            for s in slugs:
                comptes[s] = comptes.get(s, 0) + 1
            if not a_ajouter:
                continue
            page.cms_categories.add(*a_ajouter)
            aligne_revision(page)
            ranges += 1

        for slug, nom in RUBRIQUES:
            self.stdout.write(f'   {nom:<30} {comptes.get(slug, 0):>3} article(s)')
        self.stdout.write(f'   {ranges} article(s) rangé(s)')
        for motif in ignores:
            self.stdout.write(self.style.WARNING(f'   ignoré : {motif}'))

    # ── 3. le résidu WordPress ───────────────────────────────────────────────

    def _supprime_le_residu(self):
        from cms.models import ArticlePage, CmsCategory
        from content.models import MenuItem

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n3. Suppression de « Premiere Page »'))
        rubrique = CmsCategory.objects.filter(
            section_slug=SECTION, slug=RESIDU_WORDPRESS).first()
        if rubrique is None:
            self.stdout.write('   déjà supprimée')
            return

        # Aucun de ces trois liens ne lèverait d'erreur à la suppression :
        # `MenuItem.category` est en SET_NULL (le lien se viderait en silence)
        # et `cms_categories` est un M2M (les articles perdraient leur
        # rangement). Ils se vérifient donc AVANT, pas après.
        articles = ArticlePage.objects.filter(cms_categories=rubrique).count()
        menus = MenuItem.objects.filter(category=rubrique).count()
        enfants = CmsCategory.objects.filter(parent=rubrique).count()
        obstacles = []
        if articles:
            obstacles.append(f'{articles} article(s)')
        if menus:
            obstacles.append(f'{menus} entrée(s) de menu')
        if enfants:
            obstacles.append(f'{enfants} sous-rubrique(s)')
        if obstacles:
            self.stdout.write(self.style.WARNING(
                '   pas inerte (' + ', '.join(obstacles)
                + ') : conservée, à trancher à la main'))
            return

        rubrique.delete()
        self.stdout.write(
            '   supprimée (0 article, 0 entrée de menu, 0 sous-rubrique)')
