"""Alerter sans noyer.

Django sait envoyer chaque erreur 500 par courriel (`AdminEmailHandler`). Sans
lui, une panne reste dans `django.log` et dans journald — deux fichiers que
personne ne lit. C'est exactement ce qui s'est produit : 43 adresses d'article
rendaient une erreur serveur **depuis le 26/08/2026**, et on ne l'a su que le
03/09 en fouillant les journaux à la main.

Mais `AdminEmailHandler` n'a aucune limite. Ces 43 adresses, martelées par les
robots d'indexation, auraient rempli la boîte de centaines de messages
identiques — et une boîte pleine de doublons ne se lit pas mieux qu'un journal.

D'où ce garde-fou : **une seule alerte par heure et par signature d'erreur**.
La signature est le couple (chemin demandé, type d'exception) : une deuxième
page cassée passe donc tout de suite, ce n'est pas un plafond global.

⚠️ Le compteur vit dans le processus. La production tourne à trois workers
gunicorn : on peut donc recevoir jusqu'à trois exemplaires d'une même alerte.
C'est assumé — un cache partagé demanderait Redis, que ce projet n'a pas, pour
économiser deux courriels.
"""
import time

from django.utils.log import AdminEmailHandler


class AlerteLimitee(AdminEmailHandler):
    """Un courriel par heure et par signature d'erreur."""

    FENETRE = 3600  # secondes
    #: garde-fou mémoire : au-delà, on oublie les signatures les plus vieilles
    MAX_SIGNATURES = 500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vues = {}

    def _signature(self, record):
        chemin = ''
        requete = getattr(record, 'request', None)
        if requete is not None:
            chemin = getattr(requete, 'path', '') or ''
        exc = record.exc_info[0].__name__ if record.exc_info else record.getMessage()[:80]
        return f'{chemin}|{exc}'

    def emit(self, record):
        maintenant = time.time()
        sig = self._signature(record)
        dernier = self._vues.get(sig)
        if dernier is not None and maintenant - dernier < self.FENETRE:
            return
        if len(self._vues) >= self.MAX_SIGNATURES:
            # On ne garde que les plus récentes : une fuite mémoire sur un
            # gestionnaire d'alertes serait une panne de plus, pas une aide.
            for vieille in sorted(self._vues, key=self._vues.get)[:self.MAX_SIGNATURES // 2]:
                del self._vues[vieille]
        self._vues[sig] = maintenant
        super().emit(record)
