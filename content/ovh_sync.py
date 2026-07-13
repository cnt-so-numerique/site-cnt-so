"""
Miroir des consentements newsletter vers les listes OVH.

L'envoi des newsletters passe par les listes OVH du syndicat : chaque
inscription/désinscription confirmée côté site est donc répercutée sur
ces listes. L'ajout ne vise que la PREMIÈRE liste du champ
ovh_mailing_list (en être membre une seule fois évite de recevoir la
newsletter en double quand le syndicat diffuse à plusieurs listes) ;
le retrait balaie toutes les listes. Les erreurs OVH sont loguées sans
bloquer le visiteur — la base interne Subscriber reste la trace du
consentement.
"""
import logging

logger = logging.getLogger(__name__)


def lists_for_site(site):
    """Noms des listes OVH du syndicat (champ multi-valeurs, séparées par des virgules)."""
    raw = getattr(site, 'ovh_mailing_list', '') if site else ''
    return [n.strip() for n in (raw or '').split(',') if n.strip()]


def ovh_subscribe(site, email):
    lists = lists_for_site(site)
    if not lists:
        return False
    try:
        from cms.ovh_client import add_subscriber
        add_subscriber(lists[0], email)
        return True
    except Exception as e:
        logger.warning("Ajout à la liste OVH %s impossible pour %s : %s", lists[0], email, e)
        return False


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
