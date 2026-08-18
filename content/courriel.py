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
