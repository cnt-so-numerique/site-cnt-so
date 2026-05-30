"""
Relie les ArticlePage (cms) aux CmsCategory et aux tags taggit
en utilisant les liens legacy (legacy_article_id, legacy_id).

Usage :
    python manage.py migrate_categories_tags
    python manage.py migrate_categories_tags --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Migre catégories et tags depuis content.Article → cms.ArticlePage"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        if dry:
            self.stdout.write("Mode dry-run — aucune écriture.")

        self._migrate_categories(dry)
        self._migrate_tags(dry)

    # ── Catégories ────────────────────────────────────────────────────────────

    def _migrate_categories(self, dry):
        from cms.models import ArticlePage, CmsCategory
        from content.models import Article as LegacyArticle

        # Construire les index en mémoire
        legacy_article_map = {
            a.pk: a for a in LegacyArticle.objects.prefetch_related('categories').all()
        }
        cms_cat_by_legacy_id = {
            c.legacy_id: c for c in CmsCategory.objects.exclude(legacy_id=None)
        }

        ArticleCategoryThrough = ArticlePage.cms_categories.through

        total = created = skipped = 0
        pages_to_process = ArticlePage.objects.exclude(legacy_article_id=None).iterator(chunk_size=200)

        # Existing M2M to avoid duplicates
        existing = set(
            ArticleCategoryThrough.objects.values_list('articlepage_id', 'cmscategory_id')
        )

        bulk = []
        for page in pages_to_process:
            legacy = legacy_article_map.get(page.legacy_article_id)
            if not legacy:
                continue
            for legacy_cat in legacy.categories.all():
                cms_cat = cms_cat_by_legacy_id.get(legacy_cat.pk)
                if not cms_cat:
                    continue
                key = (page.pk, cms_cat.pk)
                if key in existing:
                    skipped += 1
                    continue
                total += 1
                existing.add(key)
                bulk.append(ArticleCategoryThrough(articlepage=page, cmscategory=cms_cat))
                if len(bulk) >= 500 and not dry:
                    ArticleCategoryThrough.objects.bulk_create(bulk, ignore_conflicts=True)
                    created += len(bulk)
                    bulk = []

        if bulk and not dry:
            ArticleCategoryThrough.objects.bulk_create(bulk, ignore_conflicts=True)
            created += len(bulk)
        elif dry:
            created = total

        self.stdout.write(self.style.SUCCESS(
            f"Catégories : {created} liens créés, {skipped} déjà existants"
        ))

    # ── Tags ──────────────────────────────────────────────────────────────────

    def _migrate_tags(self, dry):
        from cms.models import ArticlePage, CmsArticleTag
        from content.models import Article as LegacyArticle, Tag as LegacyTag
        from taggit.models import Tag as TaggitTag

        # 1. Créer les taggit.Tag depuis content.Tag
        legacy_tags = list(LegacyTag.objects.all())
        taggit_by_slug = {t.slug: t for t in TaggitTag.objects.all()}
        tag_created = 0

        if not dry:
            new_tags = []
            for lt in legacy_tags:
                if lt.slug not in taggit_by_slug:
                    new_tags.append(TaggitTag(name=lt.name, slug=lt.slug))
            if new_tags:
                TaggitTag.objects.bulk_create(new_tags, ignore_conflicts=True)
                tag_created = len(new_tags)
            taggit_by_slug = {t.slug: t for t in TaggitTag.objects.all()}
        else:
            tag_created = sum(1 for lt in legacy_tags if lt.slug not in taggit_by_slug)

        self.stdout.write(f"Tags taggit créés : {tag_created}")

        # 2. Relier ArticlePage ↔ taggit.Tag via CmsArticleTag
        legacy_articles = {
            a.pk: a
            for a in LegacyArticle.objects.prefetch_related('tags').filter(tags__isnull=False).distinct()
        }
        page_by_legacy = {
            p.legacy_article_id: p
            for p in ArticlePage.objects.exclude(legacy_article_id=None)
        }
        existing_links = set(
            CmsArticleTag.objects.values_list('content_object_id', 'tag_id')
        )

        bulk = []
        created = skipped = 0
        for legacy_id, legacy_article in legacy_articles.items():
            page = page_by_legacy.get(legacy_id)
            if not page:
                continue
            for lt in legacy_article.tags.all():
                tgt = taggit_by_slug.get(lt.slug)
                if not tgt:
                    continue
                key = (page.pk, tgt.pk)
                if key in existing_links:
                    skipped += 1
                    continue
                created += 1
                existing_links.add(key)
                bulk.append(CmsArticleTag(content_object=page, tag=tgt))
                if len(bulk) >= 500 and not dry:
                    CmsArticleTag.objects.bulk_create(bulk, ignore_conflicts=True)
                    bulk = []

        if bulk and not dry:
            CmsArticleTag.objects.bulk_create(bulk, ignore_conflicts=True)

        if dry:
            self.stdout.write(f"Tags liens (dry-run) : {created} à créer, {skipped} déjà existants")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Tags liens : {created} créés, {skipped} déjà existants"
            ))
