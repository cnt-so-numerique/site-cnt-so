"""
Miroir des consentements newsletter vers les listes OVH.

L'envoi des newsletters passe par les listes OVH du syndicat : chaque
inscription/désinscription confirmée côté site est donc répercutée sur
ces listes. Une liste OVH est plafonnée à 5000 abonnés : l'ajout vise la
PREMIÈRE liste NON PLEINE du champ ovh_mailing_list (ex. « news,news2 » :
on remplit news, puis news2 automatiquement — ajouter une liste news3
dans le champ suffit à étendre la capacité, sans changement de code).
Un abonné n'est inscrit qu'à une seule liste (pas de doublon d'envoi) ;
le retrait balaie toutes les listes. Les erreurs OVH sont loguées sans
bloquer le visiteur — la base interne Subscriber reste la trace du
consentement.
"""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_COUNT_CACHE_TTL = 300  # 5 minutes


def lists_for_site(site):
    """Noms des listes OVH du syndicat (champ multi-valeurs, séparées par des virgules)."""
    raw = getattr(site, 'ovh_mailing_list', '') if site else ''
    return [n.strip() for n in (raw or '').split(',') if n.strip()]


def list_count(name):
    """
    Nombre d'abonnés d'une liste OVH (compte réel côté OVH, mis en cache).
    Fail-open : en cas d'erreur API, retourne 0 — la liste est alors
    considérée non pleine et on retombe sur le comportement historique
    (première liste), plutôt que de perdre l'inscription.
    """
    if not getattr(settings, 'OVH_APPLICATION_KEY', ''):
        return 0  # pas d'identifiants OVH (dev/tests) : pas d'appel réseau
    key = f'ovh_count_{name}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        from cms.ovh_client import get_mailing_list_info
        count = int(get_mailing_list_info(name).get('nbSubscribers', 0))
    except Exception as e:
        logger.warning("Comptage liste OVH %s impossible : %s", name, e)
        return 0
    cache.set(key, count, _COUNT_CACHE_TTL)
    return count


def pick_list(site):
    """
    Choisit la liste où inscrire un nouvel abonné : la première dont le
    nombre d'abonnés est sous le plafond (settings.OVH_LIST_CAP, marge
    sous la limite dure OVH de 5000). Si toutes sont pleines, retourne la
    dernière en le signalant — il est temps de créer une liste de plus.
    """
    lists = lists_for_site(site)
    if not lists:
        return None
    cap = getattr(settings, 'OVH_LIST_CAP', 4900)
    for name in lists:
        if list_count(name) < cap:
            return name
    logger.critical(
        "Toutes les listes OVH de %s sont pleines (%s) — créer une liste "
        "supplémentaire et l'ajouter au champ ovh_mailing_list.",
        site, ', '.join(lists),
    )
    return lists[-1]


def ovh_subscribe(site, email):
    """Inscrit l'email sur la première liste non pleine. Retourne le nom de
    la liste utilisée, ou None en cas d'échec/absence de liste."""
    name = pick_list(site)
    if not name:
        return None
    try:
        from cms.ovh_client import add_subscriber
        add_subscriber(name, email)
        cache.delete(f'ovh_count_{name}')
        return name
    except Exception as e:
        logger.warning("Ajout à la liste OVH %s impossible pour %s : %s", name, email, e)
        return None


def ovh_unsubscribe(site, email):
    ok = False
    for name in lists_for_site(site):
        try:
            from cms.ovh_client import remove_subscriber
            remove_subscriber(name, email)
            ok = True
        except Exception as e:
            logger.warning("Retrait de la liste OVH %s impossible pour %s : %s", name, email, e)
    return ok
