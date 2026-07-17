"""
Crée/synchronise les groupes de permissions par section pour les rédacteurs Wagtail.

Modèle à un seul niveau par syndicat (décision 2026-07-16,
tasks/chantier-autonomie-syndicats.md) : un groupe redacteur_<slug> par
SectionPage, avec add/change/publish sur son sous-arbre de pages. Les anciens
groupes chef_<slug> sont fusionnés dedans (membres déplacés, groupe supprimé).
Les permissions modèle (articles, newsletter…) sont synchronisées par
content.apps.create_editorial_groups à chaque migrate.

Médias cloisonnés par syndicat (lot 7) : une Collection Wagtail par
SectionPage + une collection « Commun » (visuels partagés, lecture seule),
avec les GroupCollectionPermission correspondantes — Wagtail ignore les
permissions Django modèle pour les images/documents, seules ces permissions
de collection comptent.

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

        # Un groupe par section : add + change + publish sur son sous-arbre,
        # permissions modèle et collection de médias (cms/provisioning.py —
        # la même logique tourne au signal de création d'une SectionPage)
        from cms.provisioning import provision_section
        for section in SectionPage.objects.all():
            slug = section.legacy_site_slug or section.slug

            redac_group = provision_section(section)
            if redac_group is None:
                continue

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

        # Médias cloisonnés : une Collection par syndicat + « Commun »
        self._setup_collections()

        # Ménage : groupes orphelins et groupes Wagtail par défaut
        self._prune_obsolete_groups()

        # Synchronise aussi les permissions modèle (articles, newsletter…)
        from content.apps import create_editorial_groups
        from django.apps import apps as django_apps
        create_editorial_groups(django_apps.get_app_config('cms'))
        self.stdout.write('  permissions modèle synchronisées (create_editorial_groups)')

        # Migration des utilisateurs existants : Author.site → redacteur_<slug>
        self._migrate_existing_users(access_admin)

        self.stdout.write(self.style.SUCCESS('Permissions CMS configurées.'))

    def _setup_collections(self):
        """Volet global des médias cloisonnés (lot 7) — le volet par-syndicat
        est fait par provision_section.

        Wagtail contrôle les images/documents par GroupCollectionPermission
        uniquement (les permissions Django modèle sont ignorées) : sans elles,
        aucun rédacteur — même en chef — ne peut téléverser ni choisir un
        média. Le chooser natif filtre sur la permission choose, et à l'upload
        la seule collection avec add est imposée : pas de hook nécessaire.
        """
        from django.contrib.auth.models import Group
        from wagtail.models import Collection
        from cms.provisioning import (
            CHOOSE_PERMS, COLLECTION_PERMS, commun_collection,
            grant_collection_perms,
        )

        commun = commun_collection()

        # redacteur_en_chef : tous les médias, partout (Root et descendants)
        chef_global = Group.objects.get(name='redacteur_en_chef')
        grant_collection_perms(
            chef_global, Collection.get_first_root_node(), COLLECTION_PERMS)

        # Groupe générique redacteur (comptes sans groupe de syndicat) :
        # visuels partagés en lecture seulement
        generic = Group.objects.filter(name='redacteur').first()
        if generic:
            grant_collection_perms(generic, commun, CHOOSE_PERMS)

    def _prune_obsolete_groups(self):
        """Garde l'onglet Rôles de /cms/users/ lisible : supprime les groupes
        redacteur_<slug> dont la SectionPage n'existe plus et les groupes
        Wagtail par défaut (Editors/Moderators, remplacés par notre modèle
        éditorial). Un groupe qui a encore des membres est signalé, jamais
        supprimé en silence."""
        from django.contrib.auth.models import Group
        from cms.models import SectionPage

        valid_slugs = set()
        for slug, legacy in SectionPage.objects.values_list('slug', 'legacy_site_slug'):
            valid_slugs.add(slug)
            if legacy:
                valid_slugs.add(legacy)

        obsolete = [
            g for g in Group.objects.filter(name__startswith='redacteur_')
                                    .exclude(name='redacteur_en_chef')
            if g.name.removeprefix('redacteur_') not in valid_slugs
        ]
        obsolete += list(Group.objects.filter(name__in=('Editors', 'Moderators')))

        for group in obsolete:
            members = group.user_set.count()
            if members:
                self.stderr.write(
                    f'  ⚠ groupe obsolète « {group.name} » conservé : {members} membre(s)')
                continue
            group.delete()
            self.stdout.write(f'  groupe obsolète supprimé : {group.name}')

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
