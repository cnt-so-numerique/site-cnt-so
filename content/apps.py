from django.apps import AppConfig

from wagtail.users.apps import WagtailUsersAppConfig


class CustomUsersAppConfig(WagtailUsersAppConfig):
    """Remplace 'wagtail.users' dans INSTALLED_APPS : formulaires
    utilisateur avec champ « Syndicat » (fiche Author synchronisée)."""
    default = False  # pas l'AppConfig de l'app content
    user_viewset = 'content.viewsets.UserViewSet'


class ContentConfig(AppConfig):
    default = True
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'content'

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(create_editorial_groups)


def create_editorial_groups(sender, **kwargs):
    """
    Crée / met à jour les groupes redacteur / redacteur_en_chef.
    S'exécute après la migration de auth (permissions content) ET de cms
    (permissions cms.*). Les permissions manquantes sont silencieusement
    ignorées pour chaque déclenchement.
    """
    if sender.name not in ('django.contrib.auth', 'cms'):
        return

    from django.contrib.auth.models import Group, Permission

    # Permissions legacy content.* (toujours utiles pour les vues publiques)
    _CHEF_CONTENT = [
        'content.add_article', 'content.change_article', 'content.delete_article', 'content.view_article',
        'content.add_page', 'content.change_page', 'content.delete_page', 'content.view_page',
        'content.add_category', 'content.change_category', 'content.delete_category', 'content.view_category',
        'content.add_tag', 'content.change_tag', 'content.delete_tag', 'content.view_tag',
        'content.change_comment', 'content.view_comment', 'content.delete_comment',
        'content.view_contactmessage', 'content.change_contactmessage',
        'content.view_formulairecontact', 'content.change_formulairecontact',
        # Outils par syndicat : newsletter, abonnés, menus — le dashboard et
        # /cms/menus/ pointent vers ces snippets, le chef doit pouvoir y accéder
        'content.add_newsletter', 'content.change_newsletter', 'content.delete_newsletter', 'content.view_newsletter',
        'content.add_subscriber', 'content.change_subscriber', 'content.delete_subscriber', 'content.view_subscriber',
        'content.add_menuitem', 'content.change_menuitem', 'content.delete_menuitem', 'content.view_menuitem',
    ]
    _REDACTEUR_CONTENT = [
        'content.add_article', 'content.change_article', 'content.view_article',
        'content.add_page', 'content.change_page', 'content.view_page',
        'content.view_category', 'content.view_tag',
    ]

    # Permissions CMS Wagtail (cms.ArticlePage, ContentPage, CmsCategory, images, docs)
    _CHEF_CMS = [
        'wagtailadmin.access_admin',
        'cms.add_articlepage', 'cms.change_articlepage', 'cms.delete_articlepage', 'cms.view_articlepage',
        'cms.publish_articlepage', 'cms.publish_contentpage', 'cms.publish_sectionpage',
        'cms.add_contentpage', 'cms.change_contentpage', 'cms.delete_contentpage', 'cms.view_contentpage',
        'cms.add_cmscategory', 'cms.change_cmscategory', 'cms.delete_cmscategory', 'cms.view_cmscategory',
        'cms.add_event', 'cms.change_event', 'cms.delete_event', 'cms.view_event',
        'wagtailimages.add_image', 'wagtailimages.change_image', 'wagtailimages.view_image',
        'wagtailimages.choose_image', 'wagtailimages.delete_image',
        'wagtaildocs.add_document', 'wagtaildocs.change_document', 'wagtaildocs.view_document',
        'wagtaildocs.choose_document', 'wagtaildocs.delete_document',
    ]
    _REDACTEUR_CMS = [
        'wagtailadmin.access_admin',
        'cms.add_articlepage', 'cms.change_articlepage', 'cms.view_articlepage',
        # Publication directe : pas de circuit d'approbation (décision 2026-07-16,
        # cf. tasks/chantier-autonomie-syndicats.md) — le brouillon reste un état
        # de travail, le queryset scoppé par syndicat borne ce qui est publiable.
        'cms.publish_articlepage', 'cms.publish_contentpage',
        'cms.add_contentpage', 'cms.change_contentpage', 'cms.view_contentpage',
        'cms.view_cmscategory',
        'wagtailimages.add_image', 'wagtailimages.change_image', 'wagtailimages.view_image',
        'wagtailimages.choose_image',
        'wagtaildocs.add_document', 'wagtaildocs.change_document', 'wagtaildocs.view_document',
        'wagtaildocs.choose_document',
    ]

    def get_permissions(perm_list):
        perms = []
        for perm_str in perm_list:
            app_label, codename = perm_str.split('.')
            try:
                perms.append(Permission.objects.get(codename=codename, content_type__app_label=app_label))
            except Permission.DoesNotExist:
                pass
        return perms

    chef_group, _ = Group.objects.get_or_create(name='redacteur_en_chef')
    chef_group.permissions.add(*get_permissions(_CHEF_CONTENT + _CHEF_CMS))

    redacteur_group, _ = Group.objects.get_or_create(name='redacteur')
    redacteur_group.permissions.add(*get_permissions(_REDACTEUR_CONTENT + _REDACTEUR_CMS))
