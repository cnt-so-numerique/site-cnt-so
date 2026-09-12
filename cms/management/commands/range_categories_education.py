"""Range les articles du syndicat Éducation dans les rubriques que son menu nomme déjà.

Relevé sur les données de PRODUCTION le 12/09/2026. Trois constats, trois
remèdes — et rien d'inventé : la taxonomie appliquée ici est celle que le
syndicat a lui-même écrite dans son menu.

1. **« Premiere Page » n'existe que pour WordPress.** 91 des 102 articles la
   portent. Elle n'apparaît nulle part dans le code — ni vue, ni gabarit, ni
   flux (vérifié) : la « une » du syndicat vient de `_vitrine()`, pas d'elle.
   Elle n'a donc qu'un effet, et il est négatif : `article_detail.html` affiche
   TOUTES les catégories d'un article, si bien que « Premiere Page » est
   imprimé sous 91 articles à la lecture. On la retire des articles.

   On ne la SUPPRIME pas : « une catégorie vide n'est pas un déchet » (Arnaud,
   31/08/2026). Vidée, elle disparaît d'elle-même de la page Ressources, qui ne
   liste que les catégories ayant au moins un article publié.

   Garde-fou : le formulaire d'article exige au moins une catégorie. Si retirer
   « Premiere Page » laissait un article nu, on lui met « Actualités - Luttes »
   à la place — jamais zéro.

2. **Vingt rubriques thématiques ne contenaient qu'un article chacune.** D'où
   un menu qui pointe onze fois un article unique au lieu d'une liste. On y
   range les articles dont le TITRE le dit sans ambiguïté, et seulement
   ceux-là : 23 articles sur les 83 qui ne portaient que du générique.

   Les 60 autres restent dans « Actualités - Luttes ». Ce n'est pas un renoncement :
   ce sont des appels à la grève, des communiqués de rentrée, des textes
   féministes ou antimilitaristes. Les ranger de force dans « Primaire » ou
   « Supérieur » serait faux. Quatre thèmes reviennent pourtant assez pour
   mériter une rubrique — militarisation/SNU (8), austérité/budget (8),
   féminisme (6), antifascisme (4) — mais créer une rubrique est une décision
   du syndicat, pas la mienne. Cette commande n'en crée aucune.

3. **Onze entrées de menu mènent à un article unique** au lieu d'une rubrique.
   On ne repointe que celles dont la rubrique atteint `SEUIL_REPOINTAGE`
   articles après l'étape 2 — sinon on remplacerait un article par une liste
   d'un seul article, ce qui serait pire. Le seuil décide, pas moi.

   Et on repointe en posant la **clé** de la rubrique (`link_type='category'`),
   pas une adresse tapée. Les treize entrées du menu Éducation sont aujourd'hui
   des URL en dur ; or `MenuItem.get_url()` sait résoudre une clé de rubrique
   par `CmsCategory.get_absolute_url()`, qui rend d'elle-même la bonne adresse
   sur le domaine autonome (`https://educ.cnt-so.org/categorie/…`) et survit à
   un changement de slug. Une adresse tapée ne survit ni à l'un ni à l'autre.

Usage :
    python manage.py range_categories_education              # constat seul
    python manage.py range_categories_education --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.rangement import aligne_revision, mots

SECTION = 'education'
GENERIQUE = 'actualites-luttes'
RESIDU_WORDPRESS = 'premiere-page'

# En dessous de ce nombre d'articles, une rubrique ne mérite pas encore qu'on
# lui envoie une entrée de menu : la liste ferait plus pauvre que l'article.
SEUIL_REPOINTAGE = 3

# (pk, fragment du titre, rubriques à ajouter)
#
# Le fragment n'est pas décoratif : il interdit d'écrire dans un article dont
# le pk aurait été réattribué. Sans lui, un import futur pourrait faire ranger
# n'importe quoi n'importe où, en silence.
#
# Classement relu titre par titre. Écartés volontairement : « De la maternelle
# à l'université » (figure de style dans un appel à la grève, pas un article
# sur le supérieur), « Soutien aux luttes étudiantes au Bangladesh »
# (solidarité internationale), « Salaires… grève le 1er octobre » (appel à la
# grève), et les cinq « école du tri social + plan d'urgence » (budgétaires).
CLASSEMENT = [
    # ── Voie professionnelle ─────────────────────────────────────────────────
    (1805, 'casse du lycée pro public', ['voie-pro']),
    (1810, 'Correction dématérialisée du BAC PRO', ['voie-pro']),
    (1818, 'élèves de lycée professionnel', ['voie-pro']),
    (1867, 'Le lycée professionnel encore et toujours', ['voie-pro']),
    (1869, 'terminale bac pro', ['voie-pro']),
    (1872, 'La voie pro dans le viseur', ['voie-pro']),
    (1884, 'contre la voie pro', ['voie-pro']),
    (1885, 'casse des lycées pro', ['voie-pro']),
    # ── Supérieur ────────────────────────────────────────────────────────────
    (1808, 'recherche publiques', ['superieur']),
    (1844, 'Université de Paul Valéry', ['superieur']),
    (1859, 'La sélection à l', ['superieur']),
    # ── Vie scolaire – AESH ──────────────────────────────────────────────────
    (1797, 'AESH : continuons la lutte', ['vie-sco-aesh']),
    (1798, 'Vie scolaire : pour dire stop au mépris', ['vie-sco-aesh']),
    (1811, 'AESH en grève le 16 décembre', ['vie-sco-aesh']),
    (1828, 'des missions différentes mais les mêmes galères', ['vie-sco-aesh', 'aed-ash']),
    (1874, 'AESH : face au mépris', ['vie-sco-aesh']),
    (1879, 'des annonces inquiétantes', ['vie-sco-aesh']),
    # ── Secondaire / 2nd degré ───────────────────────────────────────────────
    (1801, 'DHG au rabais', ['secondaire']),
    (1887, 'Remplacements courtes durées', ['2nd-degre']),
    # ── Pédagogie ────────────────────────────────────────────────────────────
    (1833, 'Choc des savoirs, Acte 2', ['pedagogie']),
    (1849, 'Groupes de', ['pedagogie']),
    (1865, 'École d', ['pedagogie']),
    (1873, 'Auto-évaluation, piège', ['pedagogie']),
]

# Entrée de menu (pk, titre attendu) → rubrique qu'elle devrait lister.
# Le repointage n'a lieu que si la rubrique atteint SEUIL_REPOINTAGE.
MENU_VERS_RUBRIQUE = [
    (415, 'Pédagogie', 'pedagogie'),
    (416, 'Primaire', 'primaire'),
    (417, 'Secondaire', 'secondaire'),
    (418, 'Supérieur', 'superieur'),
    (419, 'Voie professionnelle', 'voie-pro'),
    (420, 'Personnels médico-sociaux', 'pers-medicaux-sociaux'),
    (421, 'Vie scolaire – AESH', 'vie-sco-aesh'),
    (423, '1er degré', '1er-degre'),
    (424, '2nd degré', '2nd-degre'),
    (425, 'AED – AESH', 'aed-ash'),
]


class Command(BaseCommand):
    help = ("Retire le résidu WordPress « Premiere Page », range 23 articles de "
            "l'Éducation dans les rubriques que son menu nomme, et repointe les "
            "entrées de menu dont la rubrique est désormais fournie")

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit en base. Sans ce drapeau, la commande n'affiche que ce "
                 "qu'elle ferait.")

    def handle(self, *args, **options):
        self.appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Rangement des rubriques de l'Éducation — "
            + ("ÉCRITURE EN BASE" if self.appliquer
               else "constat seul (--appliquer pour écrire)")))

        # Les trois étapes écrivent POUR DE VRAI, y compris en constat seul : ce
        # qui distingue le constat, c'est le `rollback` de la fin.
        #
        # Sans cela le constat mentait. `ParentalManyToManyField.add()` ne
        # travaille qu'en mémoire jusqu'au `save()` : en sautant l'écriture,
        # l'étape 3 comptait les articles dans une base où l'étape 2 n'avait
        # rien rangé, et annonçait « rubrique trop maigre » pour les dix
        # entrées — l'inverse de ce que `--appliquer` allait faire.
        with transaction.atomic():
            self._retire_le_residu_wordpress()
            self._range_les_articles()
            self._repointe_le_menu()
            if not self.appliquer:
                transaction.set_rollback(True)

    # ── Outils communs ───────────────────────────────────────────────────────

    def _rubriques(self):
        from cms.models import CmsCategory
        return {c.slug: c for c in CmsCategory.objects.filter(section_slug=SECTION)}

    def _enregistre(self, page):
        # Le détail — persistance du M2M puis report dans la révision — vit
        # dans `cms/rangement.py`, partagé avec la commande sœur.
        aligne_revision(page)

    # ── 1. le résidu WordPress ───────────────────────────────────────────────

    def _retire_le_residu_wordpress(self):
        from cms.models import ArticlePage

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n1. Retrait de « Premiere Page » (résidu WordPress)'))
        rubriques = self._rubriques()
        residu = rubriques.get(RESIDU_WORDPRESS)
        if residu is None:
            self.stdout.write('   rubrique absente — rien à faire')
            return
        generique = rubriques.get(GENERIQUE)

        nettoyes, rhabilles = 0, 0
        for page in ArticlePage.objects.filter(
                section_slug=SECTION, cms_categories=residu).prefetch_related('cms_categories'):
            gardees = [c for c in page.cms_categories.all() if c.pk != residu.pk]
            if not gardees:
                # Le formulaire d'article exige au moins une rubrique : laisser
                # l'article nu le rendrait impossible à réenregistrer.
                if generique is None:
                    self.stdout.write(self.style.WARNING(
                        f'   pk={page.pk} serait laissé sans rubrique — ignoré'))
                    continue
                gardees = [generique]
                rhabilles += 1
            page.cms_categories.set(gardees)
            self._enregistre(page)
            nettoyes += 1

        self.stdout.write(
            f'   {nettoyes} article(s) débarrassé(s) de « Premiere Page »')
        if rhabilles:
            self.stdout.write(
                f'   dont {rhabilles} rhabillé(s) en « Actualités - Luttes » '
                f'(ils ne portaient que ça)')

    # ── 2. le classement ─────────────────────────────────────────────────────

    def _range_les_articles(self):
        from cms.models import ArticlePage

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n2. Classement des articles dans les rubriques du menu'))
        rubriques = self._rubriques()
        ranges, ignores = 0, []

        for pk, fragment, slugs in CLASSEMENT:
            page = ArticlePage.objects.filter(pk=pk, section_slug=SECTION).first()
            if page is None:
                ignores.append(f'pk={pk} introuvable dans {SECTION}')
                continue
            if mots(fragment) not in mots(page.title):
                ignores.append(
                    f'pk={pk} ne contient pas « {fragment} » — non touché')
                continue
            a_ajouter = []
            for slug in slugs:
                rubrique = rubriques.get(slug)
                if rubrique is None:
                    ignores.append(f'rubrique « {slug} » absente')
                elif rubrique.pk not in {c.pk for c in page.cms_categories.all()}:
                    a_ajouter.append(rubrique)
            if not a_ajouter:
                continue
            self.stdout.write(
                f'   + {", ".join(c.name for c in a_ajouter):<28} {page.title[:58]}')
            page.cms_categories.add(*a_ajouter)
            self._enregistre(page)
            ranges += 1

        self.stdout.write(f'   {ranges} article(s) rangé(s)')
        for motif in ignores:
            self.stdout.write(self.style.WARNING(f'   ignoré : {motif}'))

    # ── 3. le menu ───────────────────────────────────────────────────────────

    def _repointe_le_menu(self):
        from cms.models import ArticlePage
        from content.models import MenuItem

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n3. Entrées de menu qui menaient à un article unique'))
        rubriques = self._rubriques()
        repointes, trop_maigres = 0, []

        for pk, titre, slug in MENU_VERS_RUBRIQUE:
            entree = MenuItem.objects.filter(pk=pk).first()
            rubrique = rubriques.get(slug)
            if entree is None or rubrique is None:
                continue
            # pk réattribué ou entrée déjà retouchée à la main : on s'abstient.
            if entree.title != titre:
                self.stdout.write(self.style.WARNING(
                    f'   pk={pk} s\'appelle « {entree.title} » — non touchée'))
                continue
            combien = ArticlePage.objects.filter(
                section_slug=SECTION, cms_categories=rubrique, live=True).count()
            if entree.link_type == 'category' and entree.category_id == rubrique.pk:
                continue
            if combien < SEUIL_REPOINTAGE:
                trop_maigres.append(f'{titre} ({combien} article·s)')
                continue
            self.stdout.write(
                f'   {titre:<26} → rubrique « {rubrique.name} »  ({combien} articles)')
            entree.link_type = 'category'
            entree.category = rubrique
            # L'ancienne adresse tapée n'a plus cours : la laisser ferait croire
            # à une cible alors que `get_url()` ne la regarde plus.
            entree.url = ''
            entree.save(update_fields=['link_type', 'category', 'url'])
            repointes += 1

        self.stdout.write(f'   {repointes} entrée(s) repointée(s)')
        if trop_maigres:
            self.stdout.write(
                '   laissées sur leur article, rubrique trop maigre : '
                + ', '.join(trop_maigres))
