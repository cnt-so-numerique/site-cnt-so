"""
Migre les documents (PDF, DOC...) depuis les blocs HTML des ArticlePages.
Les blocs 'html' contenant <a href="/media/..."> sont convertis en blocs 'file'.

Usage:
    python manage.py migrate_documents
    python manage.py migrate_documents --dry-run
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction


def _find_or_create_document(url, media_root, cache):
    if not url or url in cache:
        return cache.get(url)

    from wagtail.documents.models import Document

    if url.startswith('/media/'):
        relative = url[len('/media/'):]
    else:
        cache[url] = None
        return None

    existing = Document.objects.filter(file=relative).first()
    if existing:
        cache[url] = existing
        return existing

    abs_path = Path(media_root) / relative
    if not abs_path.exists():
        cache[url] = None
        return None

    try:
        from django.core.files.base import File
        doc = Document(title=abs_path.name)
        with open(abs_path, 'rb') as f:
            doc.file.save(relative, File(f), save=False)
        doc.save()
        cache[url] = doc
        return doc
    except Exception:
        cache[url] = None
        return None


# Regex: détecte les liens de téléchargement dans les blocs html
# <p><a href="/media/uploads/.../fichier.pdf" download>Titre</a></p>
_DOC_PATTERN = re.compile(
    r'<p><a href="(/media/[^"]+)"[^>]*>([^<]+)</a></p>',
    re.IGNORECASE
)


def _upgrade_html_blocks_with_docs(body_json_str, media_root, cache):
    """Convertit les blocs html contenant des liens PDF en blocs file."""
    if not body_json_str:
        return body_json_str, 0
    try:
        blocks = json.loads(body_json_str)
    except json.JSONDecodeError:
        return body_json_str, 0

    import uuid
    upgraded = 0
    new_blocks = []

    for block in blocks:
        if block.get('type') == 'html':
            val = block.get('value', '')
            m = _DOC_PATTERN.match(val.strip())
            if m:
                url, title = m.group(1), m.group(2).strip()
                doc = _find_or_create_document(url, media_root, cache)
                if doc:
                    block = {
                        'type': 'file',
                        'value': {'document': doc.pk, 'title': title or doc.title},
                        'id': str(uuid.uuid4()),
                    }
                    upgraded += 1
        new_blocks.append(block)

    return json.dumps(new_blocks), upgraded


class Command(BaseCommand):
    help = "Migre les documents (PDF...) depuis les blocs HTML des ArticlePages vers des blocs 'file' Wagtail"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from django.conf import settings as django_settings
        from cms.models import ArticlePage

        media_root = str(django_settings.MEDIA_ROOT)
        dry_run = options['dry_run']
        doc_cache = {}

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY-RUN ==='))

        qs = ArticlePage.objects.filter(body__isnull=False).only('pk', 'body')
        total = qs.count()
        self.stdout.write(f'{total} ArticlePages à analyser...')

        docs_created = 0
        blocks_upgraded = 0
        pages_updated = 0

        with transaction.atomic():
            for i, ap in enumerate(qs.iterator(chunk_size=100)):
                # stream_data donne le JSON brut (liste de dicts), pas le HTML rendu
                raw_json = json.dumps(ap.body.get_prep_value())
                new_body, n = _upgrade_html_blocks_with_docs(raw_json, media_root, doc_cache)
                if n > 0:
                    blocks_upgraded += n
                    pages_updated += 1
                    if not dry_run:
                        ap.body = new_body
                        ap.save(update_fields=['body'])

                if (i + 1) % 200 == 0:
                    self.stdout.write(f'  ... {i + 1}/{total}')

            docs_created = sum(1 for v in doc_cache.values() if v is not None)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {docs_created} documents créés, '
            f'{blocks_upgraded} blocs upgradés dans {pages_updated} pages.'
        ))
