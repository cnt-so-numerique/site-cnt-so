"""
Crée/synchronise les groupes de permissions par section pour les rédacteurs Wagtail.

Modèle à un seul niveau par syndicat (décision 2026-07-16,
tasks/chantier-autonomie-syndicats.md) : un groupe redacteur_<slug> par
SectionPage, avec add/change/publish sur son sous-arbre de pages. Les anciens
groupes chef_<slug> sont fusionnés dedans (membres déplacés, groupe supprimé).
Les permissions modèle (articles, newsletter…) sont synchronisées par
content.apps.create_editorial_groups à chaque migrate.

Usage:
    python manage.py setup_cms_permissions
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crée/synchronise les groupes redacteur_<slug> par SectionPage (fusionne les anciens chef_<slug>)"

    def handle(self, *args, **options):
        from django.contrib.auth.models import Group, Permission
        from wagtail.models import GroupPagePermission

        try:
            add_perm = Permission.objects.get(codename='add_page', content_type__app_label='wagtailcore')
            change_perm = Permission.objects.get(codename='change_page', content_type__app_label='wagtailcore')
            publish_perm = Permission.objects.get(codename='publish_page', content_type__app_label='wagtailcore')
            access_admin = Permission.objects.get(codename='access_admin', content_type__app_label='wagtailadmin')
        except Permission.DoesNotExist as e:
            self.stderr.write(f'Permission manquante : {e}. Lancez migrate d\'abord.')
            return

        from cms.models import HomePage, SectionPage

        home = HomePage.objects.first()
        if not home:
            self.stderr.write('HomePage introuvable — lancez migrate_to_wagtail d\'abord.')
            return

        # Groupe global redacteur_en_chef → accès à HomePage (tout le site)
        chef_global, _ = Group.objects.get_or_create(name='redacteur_en_chef')
        chef_global.permissions.add(access_admin)
        for perm in [add_perm, change_perm, publish_perm]:
            GroupPagePermission.objects.get_or_create(
                group=chef_global, page=home, permission=perm
            )
        self.stdout.write('  redacteur_en_chef → accès HomePage')

        # Un groupe par section : add + change + publish sur son sous-arbre
        for section in SectionPage.objects.all():
            slug = section.legacy_site_slug or section.slug

            redac_group, _ = Group.objects.get_or_create(name=f'redacteur_{slug}')
            redac_group.permissions.add(access_admin)
            for perm in [add_perm, change_perm, publish_perm]:
                GroupPagePermission.objects.get_or_create(
                    group=redac_group, page=section, permission=perm
                )

            # Fusion de l'ancien groupe chef_<slug> (deux niveaux abandonnés)
            chef_group = Group.objects.filter(name=f'chef_{slug}').first()
            if chef_group:
                moved = 0
                for user in chef_group.user_set.all():
                    user.groups.add(redac_group)
                    moved += 1
                chef_group.delete()
                self.stdout.write(
                    f'  {slug} → redacteur_{slug} (chef_{slug} fusionné : {moved} membre(s))')
            else:
                self.stdout.write(f'  {slug} → redacteur_{slug}')

        # Synchronise aussi les permissions modèle (articles, newsletter…)
        from content.apps import create_editorial_groups
        from django.apps import apps as django_apps
        create_editorial_groups(django_apps.get_app_config('cms'))
        self.stdout.write('  permissions modèle synchronisées (create_editorial_groups)')

        # Migration des utilisateurs existants : Author.site → redacteur_<slug>
        self._migrate_existing_users(access_admin)

        self.stdout.write(self.style.SUCCESS('Permissions CMS configurées.'))

    def _migrate_existing_users(self, access_admin):
        """Assigne les utilisateurs existants au groupe de leur section."""
        from django.contrib.auth.models import Group
        from content.models import Author

        migrated = 0
        for author in Author.objects.filter(user__isnull=False, site__isnull=False):
            site = author.site
            slug = site.legacy_site_slug or site.slug
            group = Group.objects.filter(name=f'redacteur_{slug}').first()
            if group and author.user:
                author.user.groups.add(group)
                author.user.user_permissions.add(access_admin)
                migrated += 1

        if migrated:
            self.stdout.write(f'  → {migrated} utilisateur(s) migrés vers leurs groupes de section')
