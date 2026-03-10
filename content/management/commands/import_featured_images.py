"""
Commande Django pour importer les images à la une depuis WordPress

Usage:
    # Via tunnel SSH (ssh -p 52022 -L 3307:127.0.0.1:3306 nono@5.196.74.69)
    python manage.py import_featured_images --host=127.0.0.1 --port=3307 --password='jfG5xuRa6Bfsr2jI90j5'
"""

import pymysql
import pymysql.cursors
from django.core.management.base import BaseCommand
from content.models import Site, Article, Page, Media


# Mapping des blog_id vers les sites
BLOG_IDS = {
    1: 'principal',
    2: '13',
    3: 'rhone-alpes',
    5: 'auvergne',
    6: 'staa',
    7: 'poitiers',
    8: 'numerique',
    9: 'education',
}


class Command(BaseCommand):
    help = 'Importe les images à la une depuis WordPress'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='127.0.0.1', help='Hôte MySQL')
        parser.add_argument('--port', type=int, default=3307, help='Port MySQL')
        parser.add_argument('--user', default='root', help='Utilisateur MySQL')
        parser.add_argument('--password', required=True, help='Mot de passe MySQL')
        parser.add_argument('--database', default='wp_cnt', help='Nom de la base')

    def handle(self, *args, **options):
        self.stdout.write('Connexion à MySQL...')

        try:
            self.conn = pymysql.connect(
                host=options['host'],
                port=options['port'],
                user=options['user'],
                password=options['password'],
                database=options['database'],
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.cursor = self.conn.cursor()
        except Exception as e:
            self.stderr.write(f'Erreur de connexion: {e}')
            return

        self.stdout.write(self.style.SUCCESS('Connecté à MySQL'))

        # Importer pour chaque site
        for blog_id, site_slug in BLOG_IDS.items():
            try:
                site = Site.objects.get(slug=site_slug)
                self.import_featured_images(blog_id, site)
            except Site.DoesNotExist:
                self.stderr.write(f'Site {site_slug} non trouvé')

        self.conn.close()
        self.stdout.write(self.style.SUCCESS('\nImport terminé !'))

    def get_table_prefix(self, blog_id):
        if blog_id == 1:
            return 'wp_'
        return f'wp_{blog_id}_'

    def import_featured_images(self, blog_id, site):
        self.stdout.write(f'\n--- Import des featured images pour {site.name} ---')

        prefix = self.get_table_prefix(blog_id)

        # Récupérer les articles avec leur thumbnail_id
        self.cursor.execute(f"""
            SELECT p.ID as post_id, p.post_type, pm.meta_value as thumbnail_id
            FROM {prefix}posts p
            JOIN {prefix}postmeta pm ON p.ID = pm.post_id
            WHERE pm.meta_key = '_thumbnail_id'
            AND p.post_type IN ('post', 'page')
            AND p.post_status = 'publish'
        """)

        posts_with_thumbnails = self.cursor.fetchall()
        self.stdout.write(f'  {len(posts_with_thumbnails)} posts avec thumbnail trouvés')

        articles_updated = 0
        pages_updated = 0

        for row in posts_with_thumbnails:
            thumbnail_id = row['thumbnail_id']

            # Récupérer l'URL de l'image
            self.cursor.execute(f"""
                SELECT pm.meta_value as file_path
                FROM {prefix}postmeta pm
                WHERE pm.post_id = %s AND pm.meta_key = '_wp_attached_file'
            """, [thumbnail_id])

            result = self.cursor.fetchone()
            if not result:
                continue

            file_path = result['file_path']
            image_url = f'/media/uploads/{file_path}'

            # Mettre à jour l'article ou la page
            if row['post_type'] == 'post':
                try:
                    article = Article.objects.get(site=site, wp_id=row['post_id'])

                    # Créer ou récupérer le Media
                    media, created = Media.objects.get_or_create(
                        site=site,
                        original_url=image_url,
                        defaults={
                            'title': file_path.split('/')[-1],
                        }
                    )

                    article.featured_image = media
                    article.save(update_fields=['featured_image'])
                    articles_updated += 1
                except Article.DoesNotExist:
                    pass

            elif row['post_type'] == 'page':
                try:
                    page = Page.objects.get(site=site, wp_id=row['post_id'])

                    # Créer ou récupérer le Media
                    media, created = Media.objects.get_or_create(
                        site=site,
                        original_url=image_url,
                        defaults={
                            'title': file_path.split('/')[-1],
                        }
                    )

                    page.featured_image = media
                    page.save(update_fields=['featured_image'])
                    pages_updated += 1
                except Page.DoesNotExist:
                    pass

        self.stdout.write(f'  {articles_updated} articles mis à jour')
        self.stdout.write(f'  {pages_updated} pages mises à jour')
