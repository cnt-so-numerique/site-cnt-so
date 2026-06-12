from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cms'
    verbose_name = 'CMS Wagtail'

    def ready(self):
        from django.db.models.signals import post_save
        from django.dispatch import receiver

        def _sync_subscriber_to_ovh(sender, instance, created, **kwargs):
            """Ajoute à OVH quand un abonné est confirmé (is_active=True)."""
            if not instance.is_active:
                return
            site = instance.site
            if not site:
                return
            list_name = getattr(site, 'ovh_mailing_list', '').strip()
            if not list_name:
                return
            try:
                from cms import ovh_client
                ovh_client.add_subscriber(list_name, instance.email)
            except Exception:
                pass  # ne pas bloquer la sauvegarde si OVH est indisponible

        # Import différé pour éviter les problèmes d'imports circulaires au démarrage
        from content.models import Subscriber
        post_save.connect(_sync_subscriber_to_ovh, sender=Subscriber, weak=False)
