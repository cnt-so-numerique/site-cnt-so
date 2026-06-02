"""
Importe un site WordPress via son API REST publique.

Usage :
    python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education
    python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education --media-only
    python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education --dry-run
"""
import json
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
DOC_EXTS = {'.pdf', '.doc', '.docx', '.odt', '.xls', '.xlsx', '.ppt', '.pptx', '.zip'}


class Command(BaseCommand):
    help = "Importe articles/catégories/images/documents depuis une API REST WordPress"

    def add_arguments(self, parser):
        parser.add_argument('--url', required=True, help='URL du site WP (ex: https://educ.cnt-so.org)')
        parser.add_argument('--section', required=True, help='section_slug cible (ex: education)')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--media-only', action='store_true',
                            help='Importer uniquement les médias (images+docs) pour les articles existants')

    def handle(self, *args, **options):
        self.base_url = options['url'].rstrip('/')
        self.api = f'{self.base_url}/wp-json/wp/v2'
        self.section = options['section']
        self.dry_run = options['dry_run']
        self.media_only = options['media_only']
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'CNT-SO-Importer/1.0'
        self.img_cache = {}   # url → WagtailImage or None
        self.doc_cache = {}   # url → Document or None

        if self.dry_run:
            self.stdout.write(self.style.WARNING('=== DRY-RUN ==='))

        from cms.models import SectionPage
        self.section_page = SectionPage.objects.filter(slug=self.section).first()
        if not self.section_page:
            self.stderr.write(f'SectionPage "{self.section}" introuvable.')
            return
        self.stdout.write(f'Section cible : {self.section_page.title}')

        if self.media_only:
            self._import_media_for_existing()
        else:
            self.cat_map = self._import_categories()
            self._import_posts()

        self.stdout.write(self.style.SUCCESS('Import terminé.'))

    # ── Catégories ─────────────────────────────────────────────────────────────

    def _import_categories(self):
        from cms.models import CmsCategory
        self.stdout.write('Import catégories...')
        cats = self._fetch_all('/categories', {'_fields': 'id,name,slug'})
        cat_map = {}
        created = skipped = 0
        for c in cats:
            if c['slug'] in ('uncategorized', 'non-classe'):
                continue
            if self.dry_run:
                created += 1
                continue
            obj, is_new = CmsCategory.objects.get_or_create(
                slug=c['slug'], section_slug=self.section,
                defaults={'name': c['name']},
            )
            cat_map[c['id']] = obj
            created += is_new
            skipped += not is_new
        self.stdout.write(f'  {created} créées, {skipped} existantes')
        return cat_map

    # ── Articles ───────────────────────────────────────────────────────────────

    def _import_posts(self):
        from cms.models import ArticlePage
        from django.utils import timezone
        from datetime import datetime

        self.stdout.write('Import articles...')
        posts = self._fetch_all('/posts', {
            '_fields': 'id,title,slug,date,content,excerpt,categories,featured_media,_embedded',
            'status': 'publish',
            '_embed': '1',
        })

        created = skipped = errors = 0
        with transaction.atomic():
            for post in posts:
                slug = slugify(unquote(post['slug']))
                title = self._clean_html(post['title']['rendered'])

                if ArticlePage.objects.filter(slug=slug, section_slug=self.section).exists():
                    skipped += 1
                    continue
                if self.dry_run:
                    created += 1
                    continue

                try:
                    featured_image = self._get_featured_image(post)
                    html = post['content']['rendered']
                    body_json, updated_html = self._process_content(html)

                    pub_date = datetime.fromisoformat(post['date']).date()

                    page = ArticlePage(
                        title=title,
                        slug=slug,
                        section_slug=self.section,
                        body=body_json,
                        excerpt=self._clean_html(post['excerpt']['rendered'])[:500],
                        featured_image=featured_image,
                        publication_date=pub_date,
                        first_published_at=timezone.make_aware(
                            datetime.fromisoformat(post['date'])
                        ),
                        legacy_wp_id=post['id'],
                        live=True,
                    )
                    self.section_page.add_child(instance=page)

                    cats = [self.cat_map[cid] for cid in post.get('categories', [])
                            if cid in self.cat_map]
                    if cats:
                        page.cms_categories.set(cats)

                    created += 1
                    if created % 10 == 0:
                        self.stdout.write(f'  ... {created}')

                except Exception as e:
                    errors += 1
                    self.stderr.write(f'  Erreur {slug}: {e}')

            if self.dry_run:
                transaction.set_rollback(True)

        self.stdout.write(f'  {created} créés, {skipped} existants, {errors} erreurs')

    # ── Import médias pour articles existants ──────────────────────────────────

    def _import_media_for_existing(self):
        """Retélécharge images+docs pour les articles déjà importés."""
        from cms.models import ArticlePage

        self.stdout.write('Mise à jour médias des articles existants...')
        posts = self._fetch_all('/posts', {
            '_fields': 'id,slug,content,featured_media,_embedded',
            'status': 'publish',
            '_embed': '1',
        })

        img_ok = img_skip = doc_ok = doc_skip = errors = 0

        for post in posts:
            slug = slugify(unquote(post['slug']))
            ap = ArticlePage.objects.filter(slug=slug, section_slug=self.section).first()
            if not ap:
                continue

            try:
                changed = False

                # Image à la une
                if not ap.featured_image:
                    img = self._get_featured_image(post)
                    if img:
                        ap.featured_image = img
                        changed = True
                        img_ok += 1
                    else:
                        img_skip += 1

                # Images et documents dans le corps
                html = post['content']['rendered']
                body_json, _ = self._process_content(html)
                if body_json != ap.body.stream_data if hasattr(ap.body, 'stream_data') else True:
                    ap.body = body_json
                    changed = True

                if changed and not self.dry_run:
                    ap.save(update_fields=['featured_image', 'body'])

            except Exception as e:
                errors += 1
                self.stderr.write(f'  Erreur {slug}: {e}')

        self.stdout.write(f'  Images à la une: {img_ok} ajoutées, {img_skip} sans image')
        self.stdout.write(f'  Documents: {doc_ok} ajoutés, {doc_skip} ignorés')
        if errors:
            self.stdout.write(f'  Erreurs: {errors}')

    # ── Traitement du contenu HTML ─────────────────────────────────────────────

    def _process_content(self, html):
        """
        Télécharge les images et documents inline, remplace les URLs,
        retourne (body_json, html_mis_à_jour).
        """
        if not html or not html.strip():
            return json.dumps([]), ''

        # Télécharger les images inline et remplacer les URLs
        html = self._download_inline_images(html)

        # Télécharger les documents inline et les convertir en blocs file
        html, file_blocks = self._download_inline_docs(html)

        # Nettoyer les commentaires WP
        content = re.sub(r'<!--\s*/?wp:[^>]*-->', '', html).strip()

        blocks = []
        if content:
            blocks.append({'type': 'html', 'value': content, 'id': str(uuid.uuid4())})

        # Ajouter les blocs fichiers après le contenu HTML
        blocks.extend(file_blocks)

        return json.dumps(blocks), html

    def _download_inline_images(self, html):
        """Télécharge les images inline et remplace les URLs WP par des URLs locales."""
        IMG_PAT = re.compile(
            r'(https?://' + re.escape(self.base_url.split('://', 1)[-1]) + r'[^\s"\'<>]+\.(?:jpg|jpeg|png|gif|webp))',
            re.IGNORECASE
        )
        from django.conf import settings
        media_root = Path(settings.MEDIA_ROOT)

        def replace_img(m):
            url = m.group(1)
            img = self._download_file(url, is_image=True)
            if img and hasattr(img, 'file'):
                return f'/media/{img.file.name}'
            elif img and isinstance(img, Path):
                return f'/media/{img.relative_to(media_root)}'
            return url

        return IMG_PAT.sub(replace_img, html)

    def _download_inline_docs(self, html):
        """Télécharge les documents (PDF, etc.) et les sort en blocs file Wagtail."""
        from wagtail.documents.models import Document

        DOC_PAT = re.compile(
            r'<a\s[^>]*href=["\']('
            + r'https?://' + re.escape(self.base_url.split('://', 1)[-1])
            + r'[^\s"\'<>]+\.(?:pdf|doc|docx|odt|xls|xlsx|ppt|pptx|zip))["\'][^>]*>([^<]*)</a>',
            re.IGNORECASE
        )

        file_blocks = []
        urls_replaced = set()

        for m in DOC_PAT.finditer(html):
            url, link_text = m.group(1), m.group(2).strip()
            if url in urls_replaced:
                continue
            doc = self._download_file(url, is_image=False)
            if doc and isinstance(doc, Document):
                file_blocks.append({
                    'type': 'file',
                    'value': {'document': doc.pk, 'title': link_text or doc.title},
                    'id': str(uuid.uuid4()),
                })
                # Supprimer le lien du HTML (maintenant géré par le bloc file)
                html = html.replace(m.group(0), '')
                urls_replaced.add(url)

        return html, file_blocks

    # ── Téléchargement fichiers ────────────────────────────────────────────────

    def _get_featured_image(self, post):
        media_id = post.get('featured_media', 0)
        if not media_id:
            return None
        if media_id in self.img_cache:
            return self.img_cache[media_id]

        embedded = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if embedded:
            entry = embedded[0]
            img_url = entry.get('source_url') or entry.get('guid', {}).get('rendered', '')
            if img_url:
                title = entry.get('title', {}).get('rendered', '') or Path(img_url).stem
                img = self._download_file(img_url, is_image=True, title=title)
                self.img_cache[media_id] = img
                return img

        self.img_cache[media_id] = None
        return None

    def _download_file(self, url, is_image=True, title=''):
        """Télécharge un fichier, retourne WagtailImage ou Document selon le type."""
        cache = self.img_cache if is_image else self.doc_cache
        if url in cache:
            return cache[url]

        from django.conf import settings
        from django.core.files.base import File

        media_root = Path(settings.MEDIA_ROOT)
        filename = unquote(Path(urlparse(url).path).name)
        dest_dir = media_root / 'uploads' / 'sites' / '9' / 'imported'
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename

        try:
            # Télécharger si pas déjà en cache disque
            if not dest.exists():
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                dest.write_bytes(resp.content)

            rel = str(dest.relative_to(media_root))

            if is_image:
                from wagtail.images import get_image_model
                from PIL import Image as PILImage
                WImage = get_image_model()

                existing = WImage.objects.filter(file=rel).first()
                if existing:
                    cache[url] = existing
                    return existing

                with PILImage.open(dest) as pil:
                    width, height = pil.size

                wimg = WImage(title=title or filename, width=width, height=height)
                with open(dest, 'rb') as f:
                    wimg.file.save(rel, File(f), save=False)
                wimg.save()
                cache[url] = wimg
                return wimg

            else:
                from wagtail.documents.models import Document
                existing = Document.objects.filter(file=rel).first()
                if existing:
                    cache[url] = existing
                    return existing

                doc = Document(title=title or filename)
                with open(dest, 'rb') as f:
                    doc.file.save(rel, File(f), save=False)
                doc.save()
                cache[url] = doc
                return doc

        except Exception as e:
            self.stderr.write(f'    Erreur téléchargement {url}: {e}')
            cache[url] = None
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _clean_html(self, html):
        return re.sub(r'<[^>]+>', '', html).strip()

    def _fetch_all(self, endpoint, params=None):
        params = dict(params or {})
        params['per_page'] = 100
        page = 1
        results = []
        while True:
            params['page'] = page
            try:
                resp = self.session.get(f'{self.api}{endpoint}', params=params, timeout=30)
                if resp.status_code in (400, 404):
                    break
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                results.extend(data)
                if page >= int(resp.headers.get('X-WP-TotalPages', 1)):
                    break
                page += 1
                time.sleep(0.2)
            except Exception as e:
                self.stderr.write(f'Erreur fetch {endpoint} p{page}: {e}')
                break
        return results
