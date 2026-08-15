"""Répare les entrées de menu sans destination et rattache le STAA.

Constat de l'audit du 05/08/2026 : 8 entrées de menu visibles en production
mènent vers '#'. Toutes sont de type « lien vers un site CNT » ou « catégorie »
sans cible renseignée — `get_url()` retombe silencieusement sur '#'.

La commande est idempotente : relancée, elle ne fait rien de plus.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import SectionPage, CmsCategory
from content.models import MenuItem


class Command(BaseCommand):
    help = "Répare les liens de menu sans cible et crée la section STAA."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        self.n = 0
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))
        with transaction.atomic():
            self._section_staa(sec)
            self._liens_vers_sites(sec)
            self._categories_orphelines(sec)
            if sec:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f'\n{self.n} changement(s).'))

    def _agir(self, message, action, sec):
        self.n += 1
        self.stdout.write(f'  {"[simulé] " if sec else ""}{message}')
        if not sec:
            action()

    # ── Le STAA : syndicat de la confédération, hébergé sur son propre site ──

    def _section_staa(self, sec):
        self.stdout.write(self.style.MIGRATE_HEADING('STAA (artistes-auteurs)'))
        staa = SectionPage.objects.filter(slug='staa').first()
        if staa:
            self.stdout.write('  section déjà présente, rien à faire')
            return
        parent = SectionPage.objects.filter(slug='principal').first()
        if parent is None or parent.get_parent() is None:
            self.stdout.write(self.style.ERROR(
                "  section « principal » introuvable : STAA non créé"))
            return
        racine = parent.get_parent()

        def creer():
            page = racine.add_child(instance=SectionPage(
                title='STAA (Artistes-Auteurs)',
                slug='staa',
                section_type='sectoral',
                external_url='https://staa-cnt-so.org/',
            ))
            page.save_revision().publish()

        self._agir("créer la section « STAA (Artistes-Auteurs) » "
                   "→ https://staa-cnt-so.org/ (sectoriel, site autonome)",
                   creer, sec)

    # ── Les liens « vers un site CNT » restés sans cible ─────────────────────

    def _liens_vers_sites(self, sec):
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\nEntrées de menu « lien vers un site » sans cible'))
        # Le titre désigne la section visée ; on ne devine rien d'autre.
        par_titre = {
            'cnt-so national': 'principal',
            'cnt-so éducation': 'education',
            'staa (artistes-auteurs)': 'staa',
        }
        orphelins = MenuItem.objects.filter(link_type='site', target_site__isnull=True)
        if not orphelins.exists():
            self.stdout.write('  aucune, rien à faire')
            return
        for item in orphelins:
            vise = par_titre.get((item.title or '').strip().lower())
            if vise is None:
                self.stdout.write(self.style.WARNING(
                    f'  ? {item.title!r} ({item.site}) : cible non déductible, laissé tel quel'))
                continue
            cible = SectionPage.objects.filter(slug=vise).first()
            if cible is None:
                self.stdout.write(self.style.WARNING(
                    f'  ? {item.title!r} : section {vise!r} absente, laissé tel quel'))
                continue

            def rattacher(item=item, cible=cible):
                item.target_site = cible
                item.save(update_fields=['target_site'])

            self._agir(f'{item.title!r} ({item.site}) → {cible.title} '
                       f'[{cible.get_absolute_url()}]', rattacher, sec)

    # ── Les catégories rattachées à un syndicat hébergé ailleurs ─────────────

    def _categories_orphelines(self, sec):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nCatégories du STAA (son site n'est pas le nôtre)"))
        cats = CmsCategory.objects.filter(section_slug='staa')
        if not cats.exists():
            self.stdout.write('  aucune, rien à faire')
            return
        from cms.models import ArticlePage
        for c in cats:
            n = ArticlePage.objects.filter(cms_categories=c).count()
            if n:
                self.stdout.write(self.style.WARNING(
                    f'  ? {c.name!r} porte {n} article(s) : CONSERVÉE'))
                continue
            # La suppression mettrait à NULL (SET_NULL) le lien de menu qui la
            # vise : il deviendrait une impasse. On préfère le savoir.
            vises = MenuItem.objects.filter(category=c)
            if vises.exists():
                self.stdout.write(self.style.WARNING(
                    f'  ? {c.name!r} est visée par {vises.count()} entrée(s) de '
                    f'menu : CONSERVÉE (retirer d\'abord le lien)'))
                continue
            self._agir(f'supprimer la catégorie vide {c.name!r} (slug={c.slug})',
                       lambda c=c: c.delete(), sec)
