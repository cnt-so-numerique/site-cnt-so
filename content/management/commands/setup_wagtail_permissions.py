"""
Accorde l'accès à /cms/ et configure toutes les permissions CMS
pour les groupes redacteur et redacteur_en_chef.

À lancer après chaque migrate sur une instance fraîche :
    python manage.py setup_wagtail_permissions
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


_CHEF_PERMS = [
    'wagtailadmin.access_admin',
    # Articles & Pages CMS
    'cms.add_articlepage', 'cms.change_articlepage', 'cms.delete_articlepage', 'cms.view_articlepage',
    'cms.add_contentpage', 'cms.change_contentpage', 'cms.delete_contentpage', 'cms.view_contentpage',
    # Catégories
    'cms.add_cmscategory', 'cms.change_cmscategory', 'cms.delete_cmscategory', 'cms.view_cmscategory',
    # Images & Documents
    'wagtailimages.add_image', 'wagtailimages.change_image', 'wagtailimages.view_image',
    'wagtailimages.choose_image', 'wagtailimages.delete_image',
    'wagtaildocs.add_document', 'wagtaildocs.change_document', 'wagtaildocs.view_document',
    'wagtaildocs.choose_document', 'wagtaildocs.delete_document',
    # Contenu legacy
    'content.add_article', 'content.change_article', 'content.delete_article', 'content.view_article',
    'content.add_page', 'content.change_page', 'content.delete_page', 'content.view_page',
    'content.add_category', 'content.change_category', 'content.delete_category', 'content.view_category',
    'content.add_tag', 'content.change_tag', 'content.delete_tag', 'content.view_tag',
    'content.change_comment', 'content.view_comment', 'content.delete_comment',
    'content.view_contactmessage', 'content.change_contactmessage',
]

_REDACTEUR_PERMS = [
    'wagtailadmin.access_admin',
    # Articles & Pages CMS (pas delete)
    'cms.add_articlepage', 'cms.change_articlepage', 'cms.view_articlepage',
    'cms.add_contentpage', 'cms.change_contentpage', 'cms.view_contentpage',
    # Catégories : lecture seule
    'cms.view_cmscategory',
    # Images & Documents (pas delete)
    'wagtailimages.add_image', 'wagtailimages.change_image', 'wagtailimages.view_image',
    'wagtailimages.choose_image',
    'wagtaildocs.add_document', 'wagtaildocs.change_document', 'wagtaildocs.view_document',
    'wagtaildocs.choose_document',
    # Contenu legacy (pas delete)
    'content.add_article', 'content.change_article', 'content.view_article',
    'content.add_page', 'content.change_page', 'content.view_page',
    'content.view_category', 'content.view_tag',
]


class Command(BaseCommand):
    help = "Configure toutes les permissions CMS pour redacteur et redacteur_en_chef"

    def handle(self, *args, **options):
        self._configure('redacteur_en_chef', _CHEF_PERMS)
        self._configure('redacteur', _REDACTEUR_PERMS)
        self.stdout.write(self.style.SUCCESS('Permissions CMS configurées.'))

    def _configure(self, group_name, perm_list):
        group, created = Group.objects.get_or_create(name=group_name)
        added = missing = 0
        for perm_str in perm_list:
            app_label, codename = perm_str.split('.')
            try:
                perm = Permission.objects.get(codename=codename, content_type__app_label=app_label)
                group.permissions.add(perm)
                added += 1
            except Permission.DoesNotExist:
                missing += 1
                self.stderr.write(f'  Permission manquante : {perm_str}')
        verb = 'créé' if created else 'mis à jour'
        self.stdout.write(f'Groupe "{group_name}" {verb} — {added} permissions ({missing} manquantes).')
