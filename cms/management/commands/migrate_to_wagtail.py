"""
Migrate content.Article / content.Page → cms.ArticlePage / cms.ContentPage.

Usage:
    python manage.py migrate_to_wagtail            # migration complète
    python manage.py migrate_to_wagtail --dry-run  # simule sans commit
    python manage.py migrate_to_wagtail --site rhone-alpes  # un seul site
    python manage.py migrate_to_wagtail --skip-images       # sans résolution images
"""
import json
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify


# ── Résolution d'images/documents ────────────────────────────────────────────

_image_cache = {}
_doc_cache = {}


def resolve_image(url, media_root, skip=False):
    if skip or not url:
        return None
    if url in _image_cache:
        return _image_cache[url]

    from wagtail.images import get_image_model
    WImage = get_image_model()

    # Chemin relatif
    if url.startswith('/media/'):
        relative = url[len('/media/'):]
    elif url.startswith('http'):
        _image_cache[url] = None
        return None
    else:
        relative = url.lstrip('/')

    # Déjà importé ?
    existing = WImage.objects.filter(file=relative).first()
    if existing:
        _image_cache[url] = existing.pk
        return existing.pk

    abs_path = Path(media_root) / relative
    if not abs_path.exists():
        _image_cache[url] = None
        return None

    try:
        from django.core.files.base import File
        from PIL import Image as PILImage

        with open(abs_path, 'rb') as f:
            with PILImage.open(f) as pil:
                width, height = pil.size

        wimg = WImage(title=abs_path.name, width=width, height=height)
        with open(abs_path, 'rb') as f:
            wimg.file.save(relative, File(f), save=False)
        wimg.save()
        _image_cache[url] = wimg.pk
        return wimg.pk
    except Exception:
        _image_cache[url] = None
        return None


def resolve_document(url, media_root, skip=False):
    if skip or not url:
        return None
    if url in _doc_cache:
        return _doc_cache[url]

    from wagtail.documents.models import Document

    if url.startswith('/media/'):
        relative = url[len('/media/'):]
    else:
        _doc_cache[url] = None
        return None

    existing = Document.objects.filter(file=relative).first()
    if existing:
        _doc_cache[url] = existing.pk
        return existing.pk

    abs_path = Path(media_root) / relative
    if not abs_path.exists():
        _doc_cache[url] = None
        return None

    try:
        from django.core.files.base import File
        doc = Document(title=abs_path.name)
        with open(abs_path, 'rb') as f:
            doc.file.save(relative, File(f), save=False)
        doc.save()
        _doc_cache[url] = doc.pk
        return doc.pk
    except Exception:
        _doc_cache[url] = None
        return None


# ── Conversion Editor.js → StreamField ───────────────────────────────────────

def editorjs_to_streamfield(raw, media_root, skip_images=False):
    """Convertit le champ content (JSON Editor.js ou HTML) en liste de blocs StreamField."""
    if not raw:
        return []

    raw = raw.strip()

    if not raw.startswith('{'):
        # HTML legacy WordPress
        return [{'type': 'html', 'value': raw, 'id': str(uuid.uuid4())}]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [{'type': 'html', 'value': raw, 'id': str(uuid.uuid4())}]

    blocks = data.get('blocks', [])
    result = []
    pending_html = []

    def flush():
        if pending_html:
            result.append({
                'type': 'rich_text',
                'value': ''.join(pending_html),
                'id': str(uuid.uuid4()),
            })
            pending_html.clear()

    for block in blocks:
        btype = block.get('type', '')
        bdata = block.get('data', {})

        if btype == 'paragraph':
            text = bdata.get('text', '')
            if text:
                pending_html.append(f'<p>{text}</p>')

        elif btype == 'header':
            level = max(2, min(5, bdata.get('level', 2)))
            text = bdata.get('text', '')
            if text:
                pending_html.append(f'<h{level}>{text}</h{level}>')

        elif btype == 'list':
            style = bdata.get('style', 'unordered')
            tag = 'ul' if style == 'unordered' else 'ol'
            items = bdata.get('items', [])
            if items:
                pending_html.append(f'<{tag}>' + ''.join(f'<li>{i}</li>' for i in items) + f'</{tag}>')

        elif btype == 'delimiter':
            pending_html.append('<hr/>')

        elif btype == 'quote':
            text = bdata.get('text', '')
            caption = bdata.get('caption', '')
            cite = f'<cite>— {caption}</cite>' if caption else ''
            pending_html.append(f'<blockquote><p>{text}</p>{cite}</blockquote>')

        elif btype == 'image':
            flush()
            url = bdata.get('file', {}).get('url', '')
            wid = resolve_image(url, media_root, skip=skip_images)
            if wid:
                result.append({
                    'type': 'image',
                    'value': {
                        'image': wid,
                        'caption': bdata.get('caption', ''),
                        'alignment': 'full' if bdata.get('stretched') else 'center',
                    },
                    'id': str(uuid.uuid4()),
                })
            elif url:
                result.append({
                    'type': 'html',
                    'value': f'<figure><img src="{url}" alt=""/></figure>',
                    'id': str(uuid.uuid4()),
                })

        elif btype == 'gallery':
            flush()
            items = []
            for img in bdata.get('images', []):
                url = img.get('url', '')
                wid = resolve_image(url, media_root, skip=skip_images)
                if wid:
                    items.append({'image': wid, 'caption': img.get('caption', '')})
            if items:
                result.append({
                    'type': 'gallery',
                    'value': {'images': items, 'columns': bdata.get('columns', 3)},
                    'id': str(uuid.uuid4()),
                })

        elif btype == 'file':
            flush()
            url = bdata.get('url', '')
            doc_id = resolve_document(url, media_root, skip=skip_images)
            title = bdata.get('title') or bdata.get('name', 'Fichier')
            if doc_id:
                result.append({
                    'type': 'file',
                    'value': {'document': doc_id, 'title': title},
                    'id': str(uuid.uuid4()),
                })
            elif url:
                result.append({
                    'type': 'html',
                    'value': f'<p><a href="{url}" download>{title}</a></p>',
                    'id': str(uuid.uuid4()),
                })

        elif btype in ('embed', 'table', 'code'):
            # Convertit en HTML brut pour ne pas perdre le contenu
            flush()
            from content.templatetags.content_tags import _render_block
            html = _render_block(block)
            if html:
                result.append({'type': 'html', 'value': html, 'id': str(uuid.uuid4())})

    flush()
    return result


# ── Commande Django ───────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Migrate content.Article/Page vers cms.ArticlePage/ContentPage Wagtail"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Simule sans écrire en base')
        parser.add_argument('--site', help='Migrer seulement ce site (slug)')
        parser.add_argument('--skip-images', action='store_true', help='Ne pas résoudre les images')
        parser.add_argument('--articles-only', action='store_true', help='Ne migrer que les articles')
        parser.add_argument('--pages-only', action='store_true', help='Ne migrer que les pages statiques')

    def handle(self, *args, **options):
        from django.conf import settings as django_settings
        self.media_root = str(django_settings.MEDIA_ROOT)
        self.skip_images = options['skip_images']
        self.dry_run = options['dry_run']
        self.only_site = options.get('site')
        self.articles_only = options.get('articles_only')
        self.pages_only = options.get('pages_only')

        if self.dry_run:
            self.stdout.write(self.style.WARNING('=== MODE DRY-RUN — aucun commit ==='))

        with transaction.atomic():
            self._migrate_categories()
            self._build_page_tree()
            if not self.pages_only:
                self._migrate_articles()
            if not self.articles_only:
                self._migrate_static_pages()
            self._create_redirects()

            if self.dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING('DRY-RUN terminé — rollback effectué.'))
            else:
                self.stdout.write(self.style.SUCCESS('Migration terminée avec succès !'))

    # ── Catégories ─────────────────────────────────────────────────────────────

    def _migrate_categories(self):
        from content.models import Category
        from cms.models import CmsCategory

        self.stdout.write('Migrating categories...')
        self._cat_map = {}  # old id → new CmsCategory id

        # Premier passage : créer sans parent
        for cat in Category.objects.all():
            section_slug = cat.site.slug if cat.site else 'principal'
            cms_cat, created = CmsCategory.objects.get_or_create(
                legacy_id=cat.pk,
                defaults={
                    'name': cat.name,
                    'slug': cat.slug,
                    'section_slug': section_slug,
                    'description': cat.description,
                },
            )
            if not created:
                cms_cat.name = cat.name
                cms_cat.slug = cat.slug
                cms_cat.section_slug = section_slug
                cms_cat.description = cat.description
                cms_cat.save()
            self._cat_map[cat.pk] = cms_cat

        # Deuxième passage : résoudre les parents
        for cat in Category.objects.filter(parent__isnull=False):
            cms_cat = self._cat_map.get(cat.pk)
            parent_cms = self._cat_map.get(cat.parent_id)
            if cms_cat and parent_cms:
                cms_cat.parent = parent_cms
                cms_cat.save(update_fields=['parent'])

        self.stdout.write(f'  → {len(self._cat_map)} catégories migrées')

    # ── Arbre de pages ─────────────────────────────────────────────────────────

    def _build_page_tree(self):
        from content.models import Site as ContentSite
        from cms.models import HomePage, SectionPage
        from wagtail.models import Page as WagtailPage, Site as WagtailSite

        self.stdout.write('Building page tree...')

        # HomePage — remplace la page Welcome par défaut de Wagtail si nécessaire
        root = WagtailPage.objects.get(depth=1)
        home = HomePage.objects.first()
        if not home:
            # Supprimer la page Welcome (slug='home') si elle existe
            WagtailPage.objects.filter(depth=2, slug='home').exclude(
                pk__in=HomePage.objects.values_list('pk', flat=True)
            ).delete()
            home = HomePage(
                title='CNT-SO',
                slug='home',
                intro_text='',
            )
            root.add_child(instance=home)
            self.stdout.write('  → HomePage créée')
        self._home_page = home

        # Mettre à jour le WagtailSite pour pointer sur HomePage
        wagtail_site = WagtailSite.objects.first()
        if wagtail_site and wagtail_site.root_page_id != home.pk:
            wagtail_site.root_page = home
            wagtail_site.save()

        # SectionPages pour chaque sous-site
        self._section_map = {}  # site.slug → SectionPage
        sites = ContentSite.objects.exclude(slug='principal')
        if self.only_site:
            sites = sites.filter(slug=self.only_site)

        for site in sites:
            section = SectionPage.objects.filter(legacy_site_slug=site.slug).first()
            if not section:
                section = SectionPage(
                    title=site.name,
                    slug=site.slug,
                    section_type=site.site_type,
                    description=site.description,
                    external_url=site.external_url or '',
                    agenda_url=site.agenda_url or '',
                    legacy_site_slug=site.slug,
                )
                home.add_child(instance=section)
                self.stdout.write(f'  → SectionPage créée : {site.slug}')
            self._section_map[site.slug] = section

        self.stdout.write(f'  → {len(self._section_map)} sections créées')

    # ── Articles ───────────────────────────────────────────────────────────────

    def _migrate_articles(self):
        from content.models import Article
        from cms.models import ArticlePage
        from wagtail.contrib.redirects.models import Redirect
        from wagtail.models import Site as WagtailSite

        self.stdout.write('Migrating articles...')
        qs = Article.objects.select_related('site', 'author', 'featured_image').prefetch_related('categories', 'tags')
        if self.only_site:
            qs = qs.filter(site__slug=self.only_site)

        wagtail_site = WagtailSite.objects.first()
        created_count = skipped_count = 0

        for article in qs.iterator(chunk_size=100):
            # Éviter les doublons
            if ArticlePage.objects.filter(legacy_article_id=article.pk).exists():
                skipped_count += 1
                continue

            parent = self._get_parent(article.site)
            section_slug = article.site.slug if article.site else 'principal'

            # Conversion du contenu
            body_blocks = editorjs_to_streamfield(
                article.content, self.media_root, skip_images=self.skip_images
            )

            # Slug unique au sein du parent
            slug = self._unique_slug(article.slug, parent)

            page = ArticlePage(
                title=article.title,
                slug=slug,
                body=json.dumps(body_blocks),
                excerpt=article.excerpt or '',
                is_featured=article.is_sticky,
                author_name=article.author.display_name if article.author else '',
                author_user=article.author.user if article.author else None,
                publication_date=article.published_at or article.wp_date or article.created_at,
                section_slug=section_slug,
                legacy_article_id=article.pk,
                legacy_wp_id=article.wp_id,
                live=(article.status == 'publish'),
            )

            try:
                parent.add_child(instance=page)
            except Exception as e:
                self.stderr.write(f'  ✗ Article {article.pk} ({article.slug}): {e}')
                continue

            # Forcer la date de publication Wagtail
            if article.published_at:
                ArticlePage.objects.filter(pk=page.pk).update(
                    first_published_at=article.published_at,
                    last_published_at=article.published_at,
                )

            # Catégories
            cms_cats = [self._cat_map[c.pk] for c in article.categories.all() if c.pk in self._cat_map]
            page.cms_categories.set(cms_cats)

            # Redirects
            if wagtail_site and article.slug:
                old_paths = [f'/article/{article.slug}']
                if article.site and article.site.slug != 'principal':
                    old_paths.append(f'/{article.site.slug}/article/{article.slug}')
                if article.wp_date:
                    old_paths.append(
                        f'/{article.wp_date.year:04d}/{article.wp_date.month:02d}/{article.slug}'
                    )
                for old_path in old_paths:
                    Redirect.objects.get_or_create(
                        old_path=old_path,
                        site=wagtail_site,
                        defaults={'redirect_page': page, 'is_permanent': True},
                    )

            created_count += 1
            if created_count % 100 == 0:
                self.stdout.write(f'  ... {created_count} articles migrés')

        self.stdout.write(f'  → {created_count} articles créés, {skipped_count} ignorés (déjà migrés)')

    # ── Pages statiques ────────────────────────────────────────────────────────

    def _migrate_static_pages(self):
        from content.models import Page as ContentPage
        from cms.models import ContentPage as CmsContentPage
        from wagtail.contrib.redirects.models import Redirect
        from wagtail.models import Site as WagtailSite

        self.stdout.write('Migrating static pages...')
        qs = ContentPage.objects.select_related('site', 'author', 'featured_image')
        if self.only_site:
            qs = qs.filter(site__slug=self.only_site)

        wagtail_site = WagtailSite.objects.first()
        created_count = skipped_count = 0

        for cp in qs.iterator(chunk_size=100):
            if CmsContentPage.objects.filter(legacy_page_id=cp.pk).exists():
                skipped_count += 1
                continue

            parent = self._get_parent(cp.site)
            section_slug = cp.site.slug if cp.site else 'principal'
            body_blocks = editorjs_to_streamfield(
                cp.content, self.media_root, skip_images=self.skip_images
            )
            slug = self._unique_slug(cp.slug, parent)

            page = CmsContentPage(
                title=cp.title,
                slug=slug,
                body=json.dumps(body_blocks),
                excerpt=cp.excerpt or '',
                author_name=cp.author.display_name if cp.author else '',
                section_slug=section_slug,
                legacy_page_id=cp.pk,
                live=(cp.status == 'publish'),
            )

            try:
                parent.add_child(instance=page)
            except Exception as e:
                self.stderr.write(f'  ✗ Page {cp.pk} ({cp.slug}): {e}')
                continue

            if wagtail_site and cp.slug:
                for old_path in [f'/page/{cp.slug}', f'/{section_slug}/page/{cp.slug}']:
                    Redirect.objects.get_or_create(
                        old_path=old_path,
                        site=wagtail_site,
                        defaults={'redirect_page': page, 'is_permanent': True},
                    )

            created_count += 1

        self.stdout.write(f'  → {created_count} pages créées, {skipped_count} ignorées')

    # ── Redirects supplémentaires ──────────────────────────────────────────────

    def _create_redirects(self):
        """Redirects pour les sous-sites (/<slug>/ → SectionPage)."""
        from wagtail.contrib.redirects.models import Redirect
        from wagtail.models import Site as WagtailSite

        wagtail_site = WagtailSite.objects.first()
        if not wagtail_site:
            return

        for slug, section in self._section_map.items():
            Redirect.objects.get_or_create(
                old_path=f'/{slug}',
                site=wagtail_site,
                defaults={'redirect_page': section, 'is_permanent': True},
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_parent(self, site):
        """Retourne la page parente pour un site donné."""
        if not site or site.slug == 'principal':
            return self._home_page
        return self._section_map.get(site.slug, self._home_page)

    def _unique_slug(self, base_slug, parent):
        """S'assure que le slug est unique parmi les enfants du parent."""
        from wagtail.models import Page as WagtailPage
        slug = base_slug or 'article'
        existing = set(
            WagtailPage.objects.child_of(parent).values_list('slug', flat=True)
        )
        if slug not in existing:
            return slug
        i = 2
        while f'{slug}-{i}' in existing:
            i += 1
        return f'{slug}-{i}'
