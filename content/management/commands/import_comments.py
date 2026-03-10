"""
Commande Django pour importer les commentaires depuis WordPress

Usage:
    # Via tunnel SSH (ssh -p 52022 -L 3307:127.0.0.1:3306 nono@5.196.74.69)
    python manage.py import_comments --host=127.0.0.1 --port=3307 --password='jfG5xuRa6Bfsr2jI90j5'
"""

import pymysql
import pymysql.cursors
from django.core.management.base import BaseCommand
from content.models import Site, Article, Comment


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
    help = 'Importe les commentaires depuis WordPress'

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

        total_comments = 0

        # Importer pour chaque site
        for blog_id, site_slug in BLOG_IDS.items():
            try:
                site = Site.objects.get(slug=site_slug)
                count = self.import_comments(blog_id, site)
                total_comments += count
            except Site.DoesNotExist:
                self.stderr.write(f'Site {site_slug} non trouvé')

        self.conn.close()
        self.stdout.write(self.style.SUCCESS(f'\nImport terminé ! {total_comments} commentaires importés'))

    def get_table_prefix(self, blog_id):
        if blog_id == 1:
            return 'wp_'
        return f'wp_{blog_id}_'

    def import_comments(self, blog_id, site):
        self.stdout.write(f'\n--- Import des commentaires pour {site.name} ---')

        prefix = self.get_table_prefix(blog_id)

        # Récupérer les commentaires approuvés
        self.cursor.execute(f"""
            SELECT
                c.comment_ID,
                c.comment_post_ID,
                c.comment_author,
                c.comment_author_email,
                c.comment_author_url,
                c.comment_author_IP,
                c.comment_date,
                c.comment_content,
                c.comment_approved,
                c.comment_parent
            FROM {prefix}comments c
            JOIN {prefix}posts p ON c.comment_post_ID = p.ID
            WHERE c.comment_approved = '1'
            AND p.post_type = 'post'
            AND p.post_status = 'publish'
            ORDER BY c.comment_date
        """)

        comments = self.cursor.fetchall()
        self.stdout.write(f'  {len(comments)} commentaires trouvés')

        imported = 0
        wp_to_comment = {}  # Mapping wp_id -> Comment pour les réponses

        for row in comments:
            try:
                article = Article.objects.get(site=site, wp_id=row['comment_post_ID'])
            except Article.DoesNotExist:
                continue

            # Vérifier si déjà importé
            if Comment.objects.filter(article=article, wp_id=row['comment_ID']).exists():
                continue

            # Trouver le parent si c'est une réponse
            parent = None
            if row['comment_parent'] and row['comment_parent'] in wp_to_comment:
                parent = wp_to_comment[row['comment_parent']]

            # Convertir le statut
            status = 'approved' if row['comment_approved'] == '1' else 'pending'

            comment = Comment.objects.create(
                article=article,
                wp_id=row['comment_ID'],
                author_name=row['comment_author'] or 'Anonyme',
                author_email=row['comment_author_email'] or '',
                author_url=row['comment_author_url'] or '',
                author_ip=row['comment_author_IP'] if row['comment_author_IP'] else None,
                content=row['comment_content'],
                status=status,
                parent=parent,
                wp_date=row['comment_date'],
            )

            wp_to_comment[row['comment_ID']] = comment
            imported += 1

        self.stdout.write(f'  {imported} commentaires importés')
        return imported
