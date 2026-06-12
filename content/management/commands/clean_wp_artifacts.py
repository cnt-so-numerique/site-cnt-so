"""Supprime les artefacts Gutenberg (wp:xxx) importés littéralement depuis WordPress."""
import re
import json
from django.core.management.base import BaseCommand
from wagtail.models import Page


WP_BLOCK_RE = re.compile(r'<p>\s*/?wp:[^<]*</p>\s*', re.IGNORECASE)


def clean_html(html):
    return WP_BLOCK_RE.sub('', html)


class Command(BaseCommand):
    help = "Nettoie les marqueurs de blocs Gutenberg wp:xxx des corps d'articles"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from cms.models import ArticlePage
        dry_run = options['dry_run']
        fixed = 0

        for article in ArticlePage.objects.all():
            body_json = json.loads(article.body.stream_block.to_python(article.body).__str__()
                                   if False else '[]') or []
            # Work directly on the raw DB value
            raw_value = article.body.stream_block.get_prep_value(article.body)
            raw_str = json.dumps(raw_value, ensure_ascii=False)

            if 'wp:' not in raw_str:
                continue

            cleaned = json.loads(raw_str)
            changed = False
            for block in cleaned:
                if block.get('type') == 'rich_text':
                    val = block.get('value', '')
                    new_val = clean_html(val)
                    if new_val != val:
                        block['value'] = new_val
                        changed = True

            if changed:
                fixed += 1
                if not dry_run:
                    article.body = json.dumps(cleaned)
                    article.save_revision().publish()
                    self.stdout.write(f'  ✓ {article.slug}')
                else:
                    self.stdout.write(f'  [dry-run] {article.slug}')

        label = 'à corriger' if dry_run else 'corrigés'
        self.stdout.write(self.style.SUCCESS(f'\n{fixed} articles {label}.'))
