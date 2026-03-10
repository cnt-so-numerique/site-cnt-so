"""
Commande Django pour remplacer les URLs WordPress par les URLs locales

Usage:
    python manage.py fix_media_urls
    python manage.py fix_media_urls --dry-run  # Pour voir les changements sans les appliquer
"""

import re
from django.core.management.base import BaseCommand
from content.models import Article, Page


class Command(BaseCommand):
    help = 'Remplace les URLs des médias WordPress par les URLs locales'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Affiche les changements sans les appliquer'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('Mode dry-run : aucune modification ne sera effectuée'))

        # Patterns à remplacer
        patterns = [
            # URLs avec sous-domaines (educ.cnt-so.org, etc.)
            (r'https?://[a-z0-9-]+\.cnt-so\.org/wp-content/uploads/', '/media/uploads/'),
            # URLs absolues WordPress
            (r'https?://cnt-so\.org/wp-content/uploads/', '/media/uploads/'),
            # URLs avec sous-sites (cnt-so.org/13/wp-content, etc.)
            (r'https?://cnt-so\.org/[^/]+/wp-content/uploads/', '/media/uploads/'),
            # Anciennes URLs http
            (r'http://testwp\.cnt-so\.org/wp-content/uploads/', '/media/uploads/'),
        ]

        # Traiter les articles
        articles_count = 0
        articles = Article.objects.all()

        self.stdout.write(f'Traitement de {articles.count()} articles...')

        for article in articles:
            content_modified = False
            new_content = article.content

            for pattern, replacement in patterns:
                if re.search(pattern, new_content):
                    new_content = re.sub(pattern, replacement, new_content)
                    content_modified = True

            if content_modified:
                articles_count += 1
                if not dry_run:
                    article.content = new_content
                    article.save(update_fields=['content'])

                if dry_run and articles_count <= 5:
                    self.stdout.write(f'  Article: {article.title[:50]}...')

        self.stdout.write(f'  {articles_count} articles modifiés')

        # Traiter les pages
        pages_count = 0
        pages = Page.objects.all()

        self.stdout.write(f'Traitement de {pages.count()} pages...')

        for page in pages:
            content_modified = False
            new_content = page.content

            for pattern, replacement in patterns:
                if re.search(pattern, new_content):
                    new_content = re.sub(pattern, replacement, new_content)
                    content_modified = True

            if content_modified:
                pages_count += 1
                if not dry_run:
                    page.content = new_content
                    page.save(update_fields=['content'])

                if dry_run and pages_count <= 5:
                    self.stdout.write(f'  Page: {page.title[:50]}...')

        self.stdout.write(f'  {pages_count} pages modifiées')

        # Résumé
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'Dry-run terminé : {articles_count} articles et {pages_count} pages seraient modifiés'
            ))
            self.stdout.write('Relancez sans --dry-run pour appliquer les modifications')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Terminé : {articles_count} articles et {pages_count} pages modifiés'
            ))
