"""Client OVH partagé — listes mails cnt-so.info."""
import ovh
from django.conf import settings
from django.core.cache import cache

_CACHE_TTL = 300  # 5 minutes
_client = None


def get_client():
    global _client
    if _client is None:
        _client = ovh.Client(
            endpoint='ovh-eu',
            application_key=settings.OVH_APPLICATION_KEY,
            application_secret=settings.OVH_APPLICATION_SECRET,
            consumer_key=settings.OVH_CONSUMER_KEY,
        )
    return _client


def get_domain():
    return settings.OVH_DOMAIN  # cnt-so.info


def list_mailing_lists():
    """Retourne la liste des noms de listes OVH (mise en cache)."""
    key = 'ovh_mailing_lists'
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = sorted(get_client().get(f'/email/domain/{get_domain()}/mailingList'))
    cache.set(key, result, _CACHE_TTL)
    return result


def get_mailing_list_info(name):
    """Détail d'une liste (description, replyTo, etc.)."""
    return get_client().get(f'/email/domain/{get_domain()}/mailingList/{name}')


def get_subscribers(name):
    """Retourne les adresses abonnées à une liste (mise en cache)."""
    key = f'ovh_subscribers_{name}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    emails = sorted(get_client().get(f'/email/domain/{get_domain()}/mailingList/{name}/subscriber'))
    cache.set(key, emails, _CACHE_TTL)
    return emails


def _invalidate_subscribers(list_name):
    cache.delete(f'ovh_subscribers_{list_name}')


def add_subscriber(list_name, email):
    """Ajoute un abonné à une liste OVH. Ignore les doublons."""
    try:
        get_client().post(
            f'/email/domain/{get_domain()}/mailingList/{list_name}/subscriber',
            email=email,
        )
        _invalidate_subscribers(list_name)
        return True
    except ovh.exceptions.APIError as e:
        if 'already exist' in str(e).lower() or '409' in str(e):
            return False
        raise


def remove_subscriber(list_name, email):
    """Supprime un abonné d'une liste OVH."""
    get_client().delete(
        f'/email/domain/{get_domain()}/mailingList/{list_name}/subscriber/{email}'
    )
    _invalidate_subscribers(list_name)
