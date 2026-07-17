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
                chosen = ovh_subscribe(site, instance.email)
                if chosen and chosen != instance.ovh_list:
                    # .update() pour ne pas re-déclencher post_save
                    from content.models import Subscriber as Sub
                    Sub.objects.filter(pk=instance.pk).update(ovh_list=chosen)
            elif not created:
                ovh_unsubscribe(site, instance.email)
                if instance.ovh_list:
                    from content.models import Subscriber as Sub
                    Sub.objects.filter(pk=instance.pk).update(ovh_list='')

        # Import différé pour éviter les problèmes d'imports circulaires au démarrage
        from content.models import Subscriber
        post_save.connect(_sync_subscriber_to_ovh, sender=Subscriber, weak=False)

        def _provision_new_section(sender, instance, created, **kwargs):
            """Un syndicat créé dans l'admin est gérable immédiatement :
            groupe redacteur_<slug>, permissions et collection de médias,
            sans repasser par setup_cms_permissions."""
            if created:
                from cms.provisioning import provision_section
                provision_section(instance)

        from cms.models import (
            RegionalSectionPage, SectionPage, SectoralSectionPage,
        )
        # post_save filtre sur la classe exacte : brancher aussi les proxies
        for model in (SectionPage, RegionalSectionPage, SectoralSectionPage):
            post_save.connect(_provision_new_section, sender=model, weak=False)
