"""Réglages communs aux courriels sortants de la newsletter."""

from django.conf import settings


def destinataire_de_reponse():
    """Le `reply_to` des courriels, ou None si aucune adresse n'est configurée.

    « newsletter@ » n'est relevée par personne : sans adresse de réponse, un
    lecteur qui répond écrit dans le vide, et les filtres antispam comptent un
    expéditeur injoignable comme un signal de plus.
    """
    adresse = (getattr(settings, 'NEWSLETTER_REPLY_TO', '') or '').strip()
    return [adresse] if adresse else None


def expediteur_liste():
    """L'expéditeur d'une newsletter envoyée à une liste OVH.

    La liste renvoie le courriel sous une enveloppe du domaine des listes
    (cnt-so.info) et lui ajoute un pied de page, ce qui invalide la signature
    DKIM cnt-so.org. Un expéditeur @cnt-so.org n'a alors plus rien d'aligné :
    DMARC échouait pour 86 % des courriels vus par Gmail entre le 01/08 et le
    13/09/2026. Un expéditeur @cnt-so.info s'aligne sur l'enveloppe par SPF :
    dmarc=pass chez Gmail, vérifié le 15/09/2026.

    Piège : `_dmarc.cnt-so.info` doit rester en `p=none`. À l'entrée de la
    liste, OVH juge ce premier envoi en échec DMARC (enveloppe cnt-so.org, pas
    de signature cnt-so.info) ; une politique plus stricte le ferait bloquer.

    Les envois directs, sans liste, gardent DEFAULT_FROM_EMAIL : là, c'est la
    signature DKIM cnt-so.org qui fait passer DMARC.
    """
    return settings.NEWSLETTER_LIST_FROM_EMAIL
