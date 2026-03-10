from django.apps import AppConfig


class RedactionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'redaction'
    verbose_name = 'Espace de rédaction'

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(create_redaction_groups)


def create_redaction_groups(sender, **kwargs):
    # Ne s'exécute que pour l'app 'auth' (qui gère les permissions)
    if sender.name != 'django.contrib.auth':
        return

    from django.contrib.auth.models import Group, Permission

    chef_perms = [
        'content.add_article', 'content.change_article', 'content.delete_article', 'content.view_article',
        'content.add_page', 'content.change_page', 'content.delete_page', 'content.view_page',
        'content.add_category', 'content.change_category', 'content.delete_category', 'content.view_category',
        'content.add_tag', 'content.change_tag', 'content.delete_tag', 'content.view_tag',
        'content.change_comment', 'content.view_comment', 'content.delete_comment',
        'content.view_contactmessage', 'content.change_contactmessage',
    ]

    redacteur_perms = [
        'content.add_article', 'content.change_article', 'content.view_article',
        'content.add_page', 'content.change_page', 'content.view_page',
        'content.view_category', 'content.view_tag',
    ]

    def get_permissions(perm_list):
        perms = []
        for perm_str in perm_list:
            app_label, codename = perm_str.split('.')
            try:
                perm = Permission.objects.get(
                    codename=codename,
                    content_type__app_label=app_label,
                )
                perms.append(perm)
            except Permission.DoesNotExist:
                pass
        return perms

    chef_group, _ = Group.objects.get_or_create(name='redacteur_en_chef')
    chef_group.permissions.set(get_permissions(chef_perms))

    redacteur_group, _ = Group.objects.get_or_create(name='redacteur')
    redacteur_group.permissions.set(get_permissions(redacteur_perms))
