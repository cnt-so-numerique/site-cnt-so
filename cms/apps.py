from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cms'
    verbose_name = 'CMS Wagtail'

    def ready(self):
        from django.db.models.signals import post_save, pre_delete

        def _listes_de_labonne(instance):
            """Le syndicat dont les listes portent RÉELLEMENT cette adresse.

            Deux redirections, et la seconde manquait ici :

            1. `site` nul → abonné confédéral (webhook adhésion) → principal.
            2. Syndicat **sans liste OVH** → ses inscrits vont sur celles de la
               confédération (`site_de_diffusion`, règle du 17/08/2026). Sans
               ce second saut, désactiver un abonné de Marseille — qui n'a pas
               de liste — balayait une liste vide et le laissait sur `news3`.
            """
            from cms.models import SectionPage
            from content.ovh_sync import site_de_diffusion

            site = instance.site
            if site is None:
                site = SectionPage.objects.filter(slug='principal').first()
            return site_de_diffusion(site) if site else None

        def _sync_subscriber_to_ovh(sender, instance, created, **kwargs):
            """Répercute le consentement d'un abonné sur les listes OVH.

            Confirmé (is_active=True) → ajout à la première liste non pleine ;
            désactivé sur une fiche existante → retrait de toutes les listes.
            La création d'une fiche inactive (double opt-in en attente) ne
            touche pas à OVH.
            """
            from content.ovh_sync import ovh_subscribe, ovh_unsubscribe

            site = _listes_de_labonne(instance)

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

        def _retirer_de_ovh_avant_suppression(sender, instance, **kwargs):
            """Supprimer un abonné doit aussi le retirer des listes OVH.

            Asymétrie relevée le 27/08/2026 : *désactiver* quelqu'un le
            retirait bien (post_save s'en charge), mais le *supprimer* ne
            retirait rien — l'objet disparaissait, aucun signal de mise à jour
            ne partait, et l'adresse restait chez OVH. Elle continuait donc de
            recevoir la lettre, sans plus aucune trace de consentement en base
            pour l'expliquer. Un rédacteur a le droit de supprimer un abonné
            depuis /cms/ : le geste est à portée de clic.

            `pre_delete` et non `post_delete` : on lit `site` et `email` tant
            que la ligne existe encore.

            **On ne retire que ce que le site a posé**, c'est-à-dire quand
            `ovh_list` est renseigné. Une adresse peut se trouver sur une liste
            par un autre chemin — les 5 895 adresses héritées de l'ancien
            WordPress n'ont jamais eu de ligne ici. Supprimer une ligne locale
            créée par erreur ne doit pas évincer la personne d'une liste qu'elle
            a rejointe autrement. Le cas s'est présenté le 27/08/2026 :
            `julien.huard@cnt-so.org` avait une ligne d'essai datée de mars ET
            une inscription légitime sur `news2` depuis l'import.

            La désactivation, elle, balaie bien toutes les listes : là, la
            personne retire son consentement et veut cesser de recevoir, quelle
            que soit la liste qui la porte. Supprimer une ligne est un geste
            d'administration ; se désabonner est un geste de la personne.

            Enregistrer ce récepteur désactive au passage le « fast delete » de
            Django, si bien qu'une suppression en masse passe aussi par ici.
            """
            from content.ovh_sync import ovh_unsubscribe
            if not instance.ovh_list:
                return
            site = _listes_de_labonne(instance)
            if site is not None:
                ovh_unsubscribe(site, instance.email)

        # Import différé pour éviter les problèmes d'imports circulaires au démarrage
        from content.models import Subscriber
        post_save.connect(_sync_subscriber_to_ovh, sender=Subscriber, weak=False)
        pre_delete.connect(_retirer_de_ovh_avant_suppression, sender=Subscriber,
                           weak=False)

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
