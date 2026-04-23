"""
Commande Django pour importer les données depuis WordPress (MySQL)

Usage:
    # Connexion directe au serveur (via tunnel SSH)
    python manage.py import_wordpress --host=127.0.0.1 --port=3306 --user=root --password=xxx --database=wp_cnt

    # Ou après import local du dump
    python manage.py import_wordpress --host=localhost --user=root --password=xxx --database=wp_cnt_local
"""

import pymysql
import pymysql.cursors
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.utils.dateparse import parse_datetime
from content.models import Site, Author, Category, Tag, Media, Article, Page


# Mapping des blog_id vers les infos des sites
SITES_CONFIG = {
    1: {'name': 'CNT-SO', 'slug': 'principal', 'path': '/', 'site_type': 'main'},
    2: {'name': 'CNT-SO 13 (Marseille)', 'slug': '13', 'path': '/13/', 'site_type': 'regional'},
    3: {'name': 'CNT-SO Rhône-Alpes', 'slug': 'rhone-alpes', 'path': '/rhone-alpes/', 'site_type': 'regional'},
    5: {'name': 'CNT-SO Auvergne', 'slug': 'auvergne', 'path': '/auvergne/', 'site_type': 'regional'},
    6: {'name': 'STAA (Artistes-Auteurs)', 'slug': 'staa', 'path': '/staa/', 'site_type': 'sectoral'},
    7: {'name': 'CNT-SO Poitiers', 'slug': 'poitiers', 'path': '/poitiers/', 'site_type': 'regional'},
    8: {'name': 'CNT-SO Numérique', 'slug': 'numerique', 'path': '/numerique/', 'site_type': 'sectoral'},
    9: {'name': 'CNT-SO Éducation', 'slug': 'education', 'path': '/education/', 'site_type': 'sectoral'},
}


class Command(BaseCommand):
    help = 'Importe les données depuis une base WordPress MySQL'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='127.0.0.1', help='Hôte MySQL')
        parser.add_argument('--port', type=int, default=3306, help='Port MySQL')
        parser.add_argument('--user', default='root', help='Utilisateur MySQL')
        parser.add_argument('--password', required=True, help='Mot de passe MySQL')
        parser.add_argument('--database', default='wp_cnt', help='Nom de la base')
        parser.add_argument('--site', type=int, help='Importer un seul site (blog_id)')

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

        # Importer les sites
        self.import_sites()

        # Importer les auteurs (globaux)
        self.import_authors()

        # Déterminer quels sites importer
        if options['site']:
            blog_ids = [options['site']]
        else:
            blog_ids = list(SITES_CONFIG.keys())

        # Importer les données de chaque site
        for blog_id in blog_ids:
            self.stdout.write(f'\n--- Import du site {blog_id} ---')
            self.import_site_data(blog_id)

        self.conn.close()
        self.stdout.write(self.style.SUCCESS('\nImport terminé !'))

    def import_sites(self):
        """Crée les objets Site"""
        self.stdout.write('Import des sites...')

        for blog_id, config in SITES_CONFIG.items():
            site, created = Site.objects.update_or_create(
                wp_blog_id=blog_id,
                defaults={
                    'name': config['name'],
                    'slug': config['slug'],
                    'path': config['path'],
                    'site_type': config['site_type'],
                }
            )
            action = 'créé' if created else 'mis à jour'
            self.stdout.write(f'  Site "{site.name}" {action}')

    def import_authors(self):
        """Importe les auteurs depuis wp_users et crée les comptes Django"""
        self.stdout.write('Import des auteurs...')

        self.cursor.execute("""
            SELECT u.ID, u.user_login, u.user_email, u.display_name,
                   MAX(CASE WHEN um.meta_key = 'first_name' THEN um.meta_value END) AS first_name,
                   MAX(CASE WHEN um.meta_key = 'last_name' THEN um.meta_value END) AS last_name
            FROM wp_users u
            LEFT JOIN wp_usermeta um ON u.ID = um.user_id
                AND um.meta_key IN ('first_name', 'last_name')
            GROUP BY u.ID, u.user_login, u.user_email, u.display_name
        """)

        for row in self.cursor.fetchall():
            email = row['user_email'] or ''
            username = row['user_login']
            first_name = row['first_name'] or ''
            last_name = row['last_name'] or ''

            # Créer ou récupérer le compte Django User
            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                }
            )
            if user_created:
                user.set_unusable_password()
                user.save()
            else:
                # Mettre à jour les infos si le compte existait déjà
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                user.save()

            author, created = Author.objects.update_or_create(
                wp_id=row['ID'],
                defaults={
                    'user': user,
                    'username': username,
                    'email': email,
                    'display_name': row['display_name'] or username,
                    'first_name': first_name,
                    'last_name': last_name,
                }
            )
            action = 'créé' if created else 'mis à jour'
            self.stdout.write(f'  Auteur "{author.username}" {action} (compte Django {"créé" if user_created else "existant"})')

    def get_table_prefix(self, blog_id):
        """Retourne le préfixe de table pour un blog_id"""
        if blog_id == 1:
            return 'wp_'
        return f'wp_{blog_id}_'

    def import_site_data(self, blog_id):
        """Importe toutes les données d'un site"""
        try:
            site = Site.objects.get(wp_blog_id=blog_id)
        except Site.DoesNotExist:
            self.stderr.write(f'Site {blog_id} non trouvé')
            return

        prefix = self.get_table_prefix(blog_id)

        # Importer catégories et tags
        self.import_terms(site, prefix)

        # Importer articles et pages
        self.import_posts(site, prefix)

    def import_terms(self, site, prefix):
        """Importe les catégories et tags"""
        self.stdout.write(f'  Import des catégories et tags...')

        self.cursor.execute(f"""
            SELECT t.term_id, t.name, t.slug, tt.taxonomy, tt.description, tt.parent
            FROM {prefix}terms t
            JOIN {prefix}term_taxonomy tt ON t.term_id = tt.term_id
            WHERE tt.taxonomy IN ('category', 'post_tag')
        """)

        categories_map = {}
        tags_map = {}

        for row in self.cursor.fetchall():
            if row['taxonomy'] == 'category':
                # Générer un slug unique pour ce site
                base_slug = row['slug'] or slugify(row['name'])
                slug = base_slug

                # Vérifier si le slug existe déjà pour ce site
                counter = 1
                while Category.objects.filter(site=site, slug=slug).exclude(wp_id=row['term_id']).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                cat, created = Category.objects.update_or_create(
                    site=site,
                    wp_id=row['term_id'],
                    defaults={
                        'name': row['name'],
                        'slug': slug,
                        'description': row['description'] or '',
                    }
                )
                categories_map[row['term_id']] = cat

            elif row['taxonomy'] == 'post_tag':
                base_slug = row['slug'] or slugify(row['name'])

                # Les tags sont globaux, on essaie de récupérer par slug
                try:
                    tag = Tag.objects.get(slug=base_slug)
                except Tag.DoesNotExist:
                    # Créer un nouveau tag
                    tag = Tag.objects.create(
                        name=row['name'],
                        slug=base_slug,
                        wp_id=row['term_id']
                    )
                tags_map[row['term_id']] = tag

        self.stdout.write(f'    {len(categories_map)} catégories, {len(tags_map)} tags')

        # Mettre à jour les parents des catégories
        self.cursor.execute(f"""
            SELECT t.term_id, tt.parent
            FROM {prefix}terms t
            JOIN {prefix}term_taxonomy tt ON t.term_id = tt.term_id
            WHERE tt.taxonomy = 'category' AND tt.parent > 0
        """)

        for row in self.cursor.fetchall():
            if row['term_id'] in categories_map and row['parent'] in categories_map:
                cat = categories_map[row['term_id']]
                cat.parent = categories_map[row['parent']]
                cat.save()

        return categories_map, tags_map

    def import_posts(self, site, prefix):
        """Importe les articles et pages"""
        self.stdout.write(f'  Import des articles et pages...')

        # Récupérer le mapping terme -> objet
        self.cursor.execute(f"""
            SELECT t.term_id, t.name, t.slug, tt.taxonomy
            FROM {prefix}terms t
            JOIN {prefix}term_taxonomy tt ON t.term_id = tt.term_id
            WHERE tt.taxonomy IN ('category', 'post_tag')
        """)

        categories_map = {}
        tags_map = {}

        for row in self.cursor.fetchall():
            if row['taxonomy'] == 'category':
                try:
                    categories_map[row['term_id']] = Category.objects.get(site=site, wp_id=row['term_id'])
                except Category.DoesNotExist:
                    pass
            elif row['taxonomy'] == 'post_tag':
                # Chercher le tag par slug (les tags sont globaux)
                slug = row['slug'] or slugify(row['name'])
                try:
                    tags_map[row['term_id']] = Tag.objects.get(slug=slug)
                except Tag.DoesNotExist:
                    pass

        # Récupérer les posts
        self.cursor.execute(f"""
            SELECT ID, post_author, post_date, post_content, post_title,
                   post_excerpt, post_status, post_name, post_type,
                   post_parent, menu_order, comment_status
            FROM {prefix}posts
            WHERE post_type IN ('post', 'page')
            AND post_status != 'auto-draft'
        """)

        articles_count = 0
        pages_count = 0

        for row in self.cursor.fetchall():
            # Trouver l'auteur
            try:
                author = Author.objects.get(wp_id=row['post_author'])
            except Author.DoesNotExist:
                author = None

            # Générer un slug unique
            base_slug = row['post_name'] or slugify(row['post_title'])
            if not base_slug:
                base_slug = f"post-{row['ID']}"

            if row['post_type'] == 'post':
                # Vérifier si le slug existe déjà pour ce site
                slug = base_slug
                counter = 1
                while Article.objects.filter(site=site, slug=slug).exclude(wp_id=row['ID']).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                article, created = Article.objects.update_or_create(
                    site=site,
                    wp_id=row['ID'],
                    defaults={
                        'title': row['post_title'] or '(Sans titre)',
                        'slug': slug,
                        'content': row['post_content'] or '',
                        'excerpt': row['post_excerpt'] or '',
                        'status': row['post_status'],
                        'author': author,
                        'wp_date': row['post_date'],
                        'published_at': row['post_date'] if row['post_status'] == 'publish' else None,
                        'comment_status': row['comment_status'] or 'closed',
                    }
                )

                # Associer les catégories et tags
                self.cursor.execute(f"""
                    SELECT tt.term_id, tt.taxonomy
                    FROM {prefix}term_relationships tr
                    JOIN {prefix}term_taxonomy tt ON tr.term_taxonomy_id = tt.term_taxonomy_id
                    WHERE tr.object_id = %s
                """, [row['ID']])

                for term_row in self.cursor.fetchall():
                    if term_row['taxonomy'] == 'category' and term_row['term_id'] in categories_map:
                        article.categories.add(categories_map[term_row['term_id']])
                    elif term_row['taxonomy'] == 'post_tag' and term_row['term_id'] in tags_map:
                        article.tags.add(tags_map[term_row['term_id']])

                articles_count += 1

            elif row['post_type'] == 'page':
                # Vérifier si le slug existe déjà pour ce site
                slug = base_slug
                counter = 1
                while Page.objects.filter(site=site, slug=slug).exclude(wp_id=row['ID']).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                page, created = Page.objects.update_or_create(
                    site=site,
                    wp_id=row['ID'],
                    defaults={
                        'title': row['post_title'] or '(Sans titre)',
                        'slug': slug,
                        'content': row['post_content'] or '',
                        'excerpt': row['post_excerpt'] or '',
                        'status': row['post_status'],
                        'author': author,
                        'wp_date': row['post_date'],
                        'published_at': row['post_date'] if row['post_status'] == 'publish' else None,
                        'menu_order': row['menu_order'] or 0,
                    }
                )
                pages_count += 1

        self.stdout.write(f'    {articles_count} articles, {pages_count} pages')
