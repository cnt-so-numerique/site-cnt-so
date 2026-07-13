from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cms'
    verbose_name = 'CMS Wagtail'

    def ready(self):
        from django.db.models.signals import post_save

        def _sync_subscriber_to_ovh(sender, instance, created, **kwargs):
            """Répercute le consentement d'un abonné sur les listes OVH du syndicat.

            Confirmé (is_active=True) → ajout à la première liste du site ;
            désactivé sur une fiche existante → retrait de toutes les listes.
            La création d'une fiche inactive (double opt-in en attente) ne
            touche pas à OVH.
            """
            from content.ovh_sync import ovh_subscribe, ovh_unsubscribe

            site = instance.site
            if site is None:
                # Abonné confédéral (webhook adhésion) → listes du site principal
                from cms.models import SectionPage
                site = SectionPage.objects.filter(slug='principal').first()

            if instance.is_active:
                ovh_subscribe(site, instance.email)
            elif not created:
                ovh_unsubscribe(site, instance.email)

        # Import différé pour éviter les problèmes d'imports circulaires au démarrage
        from content.models import Subscriber
        post_save.connect(_sync_subscriber_to_ovh, sender=Subscriber, weak=False)
