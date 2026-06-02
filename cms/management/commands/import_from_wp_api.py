"""
Importe un site WordPress via son API REST publique.

Usage :
    python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education
    python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education --dry-run
"""
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Importe articles/catégories/médias depuis une API REST WordPress"

    def add_arguments(self, parser):
        parser.add_argument('--url', required=True, help='URL du site WP (ex: https://educ.cnt-so.org)')
        parser.add_argument('--section', required=True, help='section_slug cible (ex: education)')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        self.base_url = options['url'].rstrip('/')
        self.api = f'{self.base_url}/wp-json/wp/v2'
        self.section = options['section']
        self.dry_run = options['dry_run']
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'CNT-SO-Importer/1.0'

        if self.dry_run:
            self.stdout.write(self.style.WARNING('=== DRY-RUN ==='))

        from cms.models import SectionPage, CmsCategory, HomePage
        from wagtail.models import Page

        # Vérifier que la SectionPage existe
        self.section_page = SectionPage.objects.filter(slug=self.section).first()
        if not self.section_page:
            self.stderr.write(f'SectionPage "{self.section}" introuvable.')
            return
        self.stdout.write(f'Section cible : {self.section_page.title}')

        # Import catégories
        self.cat_map = self._import_categories()

        # Import médias (featured images)
        self.media_cache = {}

        # Import articles
        self._import_posts()

        self.stdout.write(self.style.SUCCESS('Import terminé.'))

    # ── Catégories ────────────────────────────────────────────────────────────

    def _import_categories(self):
        from cms.models import CmsCategory
        self.stdout.write('Import catégories...')
        cats = self._fetch_all('/categories', {'_fields': 'id,name,slug,description'})
        cat_map = {}  # wp_id → CmsCategory
        created = skipped = 0
        for c in cats:
            if c['slug'] in ('uncategorized', 'non-classe'):
                continue
            if self.dry_run:
                self.stdout.write(f'  [dry] catégorie : {c["name"]}')
                skipped += 1
                continue
            obj, is_new = CmsCategory.objects.get_or_create(
                slug=c['slug'],
                section_slug=self.section,
                defaults={'name': c['name']},
            )
            cat_map[c['id']] = obj
            if is_new:
                created += 1
            else:
                skipped += 1
        self.stdout.write(f'  {created} créées, {skipped} existantes/ignorées')
        return cat_map

    # ── Articles ───────────────────────────────────────────────────────────────

    def _import_posts(self):
        from cms.models import ArticlePage, HomePage
        from wagtail.models import Page

        self.stdout.write('Import articles...')
        posts = self._fetch_all('/posts', {
            '_fields': 'id,title,slug,date,modified,content,excerpt,categories,featured_media,status',
            'status': 'publish',
            '_embed': '1',
        })

        created = skipped = errors = 0
        parent = self.section_page

        with transaction.atomic():
            for post in posts:
                slug = post['slug']
                title = post['title']['rendered']

                # Déjà importé ?
                if ArticlePage.objects.filter(slug=slug, section_slug=self.section).exists():
                    skipped += 1
                    continue

                if self.dry_run:
                    self.stdout.write(f'  [dry] {title[:60]}')
                    created += 1
                    continue

                try:
                    # Image à la une
                    featured_image = self._get_featured_image(post)

                    # Contenu → StreamField JSON
                    body_json = self._html_to_body(post['content']['rendered'])

                    # Catégories
                    cats = [self.cat_map[cid] for cid in post.get('categories', [])
                            if cid in self.cat_map]

                    # Date de publication
                    from django.utils import timezone
                    from datetime import datetime
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
                    parent.add_child(instance=page)

                    if cats:
                        page.cms_categories.set(cats)

                    created += 1
                    if created % 10 == 0:
                        self.stdout.write(f'  ... {created}/{len(posts)}')

                except Exception as e:
                    errors += 1
                    self.stderr.write(f'  Erreur sur {slug}: {e}')

            if self.dry_run:
                transaction.set_rollback(True)

        self.stdout.write(f'  {created} créés, {skipped} existants, {errors} erreurs')

    # ── Images ────────────────────────────────────────────────────────────────

    def _get_featured_image(self, post):
        media_id = post.get('featured_media', 0)
        if not media_id:
            return None
        if media_id in self.media_cache:
            return self.media_cache[media_id]

        # Tenter via _embedded d'abord
        embedded = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if embedded and embedded[0].get('source_url'):
            img_url = embedded[0]['source_url']
            img = self._download_image(img_url, embedded[0].get('title', {}).get('rendered', ''))
            self.media_cache[media_id] = img
            return img

        self.media_cache[media_id] = None
        return None

    def _download_image(self, url, title=''):
        from wagtail.images import get_image_model
        from django.conf import settings
        from django.core.files.base import File
        from PIL import Image as PILImage

        WImage = get_image_model()

        # Déjà téléchargée ?
        existing = WImage.objects.filter(title=title or url.split('/')[-1]).first()
        if existing:
            return existing

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            content = resp.content

            with PILImage.open(BytesIO(content)) as pil:
                width, height = pil.size

            filename = Path(urlparse(url).path).name
            media_root = Path(settings.MEDIA_ROOT)
            dest_dir = media_root / 'uploads' / 'sites' / '9' / 'imported'
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename

            with open(dest, 'wb') as f:
                f.write(content)

            rel = str(dest.relative_to(media_root))
            wimg = WImage(
                title=title or filename,
                width=width,
                height=height,
            )
            with open(dest, 'rb') as f:
                wimg.file.save(rel, File(f), save=False)
            wimg.save()
            return wimg

        except Exception as e:
            self.stderr.write(f'    Image non téléchargée ({url}): {e}')
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _html_to_body(self, html):
        """Convertit le HTML WP en liste de blocs StreamField JSON."""
        import json
        if not html or not html.strip():
            return json.dumps([])

        # Sépare par les blocs WP (<!-- wp:xxx --> ... <!-- /wp:xxx -->)
        # Sinon traite comme un seul bloc HTML
        blocks = []

        # Nettoyer les commentaires WP mais garder le contenu
        content = re.sub(r'<!--\s*/?wp:[^>]*-->', '', html).strip()

        if content:
            blocks.append({
                'type': 'html',
                'value': content,
                'id': str(uuid.uuid4()),
            })

        return __import__('json').dumps(blocks)

    def _clean_html(self, html):
        return re.sub(r'<[^>]+>', '', html).strip()

    def _fetch_all(self, endpoint, params=None):
        """Récupère toutes les pages d'un endpoint paginé."""
        params = params or {}
        params['per_page'] = 100
        page = 1
        results = []

        while True:
            params['page'] = page
            try:
                resp = self.session.get(f'{self.api}{endpoint}', params=params, timeout=30)
                if resp.status_code == 400:
                    break
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                results.extend(data)
                total_pages = int(resp.headers.get('X-WP-TotalPages', 1))
                if page >= total_pages:
                    break
                page += 1
                time.sleep(0.2)
            except Exception as e:
                self.stderr.write(f'Erreur fetch {endpoint} page {page}: {e}')
                break

        return results
