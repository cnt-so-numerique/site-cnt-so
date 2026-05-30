import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


@receiver(post_save, sender='adhesion.Adhesion')
def handle_adhesion_actif(sender, instance, **kwargs):
    if instance.status not in ('actif', 'manuel'):
        return

    _subscribe_syndicat(instance)
    _subscribe_regional(instance)
    _subscribe_national(instance)

    try:
        from adhesion.emails import send_confirmation_email
        send_confirmation_email(instance)
    except Exception:
        logger.exception("Échec envoi email confirmation adhésion %s", instance.token)


def _subscribe_syndicat(adhesion):
    if adhesion.newsletter_syndicat_done:
        return
    try:
        _create_subscriber(adhesion.site, adhesion.email, f"{adhesion.prenom} {adhesion.nom}".strip())
        adhesion.__class__.objects.filter(pk=adhesion.pk).update(newsletter_syndicat_done=True)
        adhesion.newsletter_syndicat_done = True
    except Exception:
        logger.exception("Échec abonnement newsletter syndicat pour adhésion %s", adhesion.token)


def _subscribe_regional(adhesion):
    if adhesion.newsletter_regional_done or not adhesion.code_postal:
        return
    try:
        from adhesion.models import ZoneGeographique
        prefix = adhesion.code_postal[:2]
        zone = ZoneGeographique.objects.filter(code_prefix=prefix).select_related('site').first()
        if zone and zone.site != adhesion.site:
            _create_subscriber(zone.site, adhesion.email, f"{adhesion.prenom} {adhesion.nom}".strip())
        adhesion.__class__.objects.filter(pk=adhesion.pk).update(newsletter_regional_done=True)
        adhesion.newsletter_regional_done = True
    except Exception:
        logger.exception("Échec abonnement newsletter régionale pour adhésion %s", adhesion.token)


def _subscribe_national(adhesion):
    if adhesion.newsletter_national_done:
        return
    try:
        from cms.models import SectionPage
        site_national = SectionPage.objects.filter(slug='principal').first()
        if site_national and site_national != adhesion.site:
            _create_subscriber(site_national, adhesion.email, f"{adhesion.prenom} {adhesion.nom}".strip())
        adhesion.__class__.objects.filter(pk=adhesion.pk).update(newsletter_national_done=True)
        adhesion.newsletter_national_done = True
    except Exception:
        logger.exception("Échec abonnement newsletter nationale pour adhésion %s", adhesion.token)


def _create_subscriber(site, email, name):
    from content.models import Subscriber
    subscriber, created = Subscriber.objects.get_or_create(
        site=site,
        email=email.lower().strip(),
        defaults={'name': name, 'is_active': True, 'confirmed_at': timezone.now()},
    )
    if not created and not subscriber.is_active:
        subscriber.is_active = True
        subscriber.confirmed_at = timezone.now()
        subscriber.save(update_fields=['is_active', 'confirmed_at'])
