"""Client OVH partagé — listes mails cnt-so.info."""
import ovh
from django.conf import settings


def get_client():
    return ovh.Client(
        endpoint='ovh-eu',
        application_key=settings.OVH_APPLICATION_KEY,
        application_secret=settings.OVH_APPLICATION_SECRET,
        consumer_key=settings.OVH_CONSUMER_KEY,
    )


def get_domain():
    return settings.OVH_DOMAIN  # cnt-so.info


def list_mailing_lists():
    """Retourne la liste des noms de listes OVH."""
    client = get_client()
    return sorted(client.get(f'/email/domain/{get_domain()}/mailingList'))


def get_mailing_list_info(name):
    """Détail d'une liste (description, replyTo, etc.)."""
    client = get_client()
    return client.get(f'/email/domain/{get_domain()}/mailingList/{name}')


def get_subscribers(name):
    """Retourne les adresses abonnées à une liste."""
    client = get_client()
    emails = client.get(f'/email/domain/{get_domain()}/mailingList/{name}/subscriber')
    return sorted(emails)


def add_subscriber(list_name, email):
    """Ajoute un abonné à une liste OVH. Ignore les doublons."""
    client = get_client()
    try:
        client.post(
            f'/email/domain/{get_domain()}/mailingList/{list_name}/subscriber',
            email=email,
        )
        return True
    except ovh.exceptions.APIError as e:
        if 'already exist' in str(e).lower() or '409' in str(e):
            return False
        raise


def remove_subscriber(list_name, email):
    """Supprime un abonné d'une liste OVH."""
    client = get_client()
    client.delete(
        f'/email/domain/{get_domain()}/mailingList/{list_name}/subscriber/{email}'
    )
