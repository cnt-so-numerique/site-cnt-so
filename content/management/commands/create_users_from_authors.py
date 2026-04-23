"""
Crée les comptes Django User pour chaque Author sans compte,
et tente d'inférer le site assigné d'après le username.

Usage:
    python manage.py create_users_from_authors
    python manage.py create_users_from_authors --dry-run
"""

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from content.models import Author, Site

# Authors à supprimer de la base (comptes obsolètes/inconnus)
AUTHORS_TO_DELETE = {'felix86', 'cursive'}

# Correspondance username WP → slug du site Django
USERNAME_TO_SITE = {
    'cntso':         'principal',
    'media':         'principal',
    'bamiu':         'numerique',
    'nicolas13':     '13',
    'auvergne':      'auvergne',
    'cntsoauvergne': 'auvergne',
    'staa':          'staa',
    'staawriter':    'staa',
    'education':     'education',
}

# Usernames qui obtiennent redacteur_en_chef au lieu de redacteur
CHEFS = {'media', 'bamiu'}


class Command(BaseCommand):
    help = 'Crée les comptes Django User depuis les Authors WP importés'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Affiche ce qui serait fait sans modifier la base',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        if dry:
            self.stdout.write(self.style.WARNING('Mode dry-run — aucune modification'))

        redacteur_group = chef_group = None
        if not dry:
            redacteur_group, _ = Group.objects.get_or_create(name='redacteur')
            chef_group, _ = Group.objects.get_or_create(name='redacteur_en_chef')

        # Supprimer les Authors obsolètes
        for username in AUTHORS_TO_DELETE:
            try:
                author = Author.objects.get(username=username)
                self.stdout.write(f'Suppression de l\'auteur "{username}"')
                if not dry:
                    author.delete()
            except Author.DoesNotExist:
                pass

        authors_sans_user = Author.objects.filter(user__isnull=True)
        self.stdout.write(f'\n{authors_sans_user.count()} auteur(s) sans compte Django trouvé(s)\n')

        sites_cache = {s.slug: s for s in Site.objects.all()}
        created_count = 0
        skipped_count = 0

        for author in authors_sans_user.order_by('username'):
            site_slug = USERNAME_TO_SITE.get(author.username)
            site = sites_cache.get(site_slug) if site_slug else None
            is_chef = author.username in CHEFS
            role_label = 'redacteur_en_chef' if is_chef else 'redacteur'

            self.stdout.write(
                f'  {author.username} <{author.email}>'
                f' → site: {site_slug} | groupe: {role_label}'
            )

            if dry:
                continue

            # Créer ou récupérer le User Django
            user, user_created = User.objects.get_or_create(
                username=author.username,
                defaults={
                    'email': author.email,
                    'first_name': author.first_name,
                    'last_name': author.last_name,
                },
            )
            if user_created:
                user.set_unusable_password()
                user.save()
                user.groups.add(chef_group if is_chef else redacteur_group)
                created_count += 1
            else:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(f'    → User "{author.username}" existait déjà, ignoré')
                )
                continue

            # Lier User → Author et assigner le site
            author.user = user
            if site:
                author.site = site
            author.save()

            self.stdout.write(
                self.style.SUCCESS(f'    → Compte créé, site: {site.name if site else "?"}')
            )

        if not dry:
            self.stdout.write(
                f'\n{created_count} compte(s) créé(s), {skipped_count} déjà existant(s).'
            )
            self.stdout.write(
                self.style.WARNING(
                    '\nAttention : les mots de passe sont inutilisables.'
                    ' Chaque utilisateur devra faire "Mot de passe oublié" pour se connecter.'
                )
            )
