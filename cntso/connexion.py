"""Connexion au CMS par identifiant OU par adresse courriel.

Le 21/09/2026, un collègue a réinitialisé le mot de passe du compte `media`
avec succès, puis échoué trois fois à se connecter. Le parcours de
réinitialisation lui avait demandé son ADRESSE ; la page de connexion lui
demandait son IDENTIFIANT (`media`), et seul l'identifiant était accepté. Six
autres personnes passaient le même parcours la même semaine.

Les deux sont désormais acceptés. L'identifiant reste prioritaire : si ce qui
est tapé est l'identifiant d'un compte, c'est ce compte-là et lui seul qui est
essayé — on ne tente jamais le même mot de passe sur deux comptes.
"""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from wagtail.admin.forms.auth import LoginForm


class IdentifiantOuCourrielBackend(ModelBackend):
    """`ModelBackend`, qui accepte aussi l'adresse courriel.

    Hérite de tout le reste (permissions, `get_user`) : seule la recherche du
    compte change.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None

        user = self._trouver(User, username.strip())
        if user is None:
            # Même coût qu'une vraie vérification, comme le fait ModelBackend :
            # sans cela, la durée de la réponse dirait si le compte existe.
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _trouver(User, saisie):
        # 1. L'identifiant, exactement comme ModelBackend.
        try:
            return User._default_manager.get_by_natural_key(saisie)
        except User.DoesNotExist:
            pass

        # 2. L'adresse, sans tenir compte de la casse — mais seulement si elle
        #    désigne UN compte actif et un seul. Deux comptes sur la même
        #    adresse : on refuse plutôt que de deviner lequel.
        if '@' not in saisie:
            return None
        candidats = list(User._default_manager.filter(
            email__iexact=saisie, is_active=True)[:2])
        return candidats[0] if len(candidats) == 1 else None


class FormulaireConnexion(LoginForm):
    """Le formulaire de connexion de Wagtail, qui dit accepter les deux.

    Sans lui, le champ continuerait d'afficher « Entrez votre nom
    d'utilisateur », et personne ne saurait que l'adresse marche aussi.
    """

    error_messages = {
        **LoginForm.error_messages,
        'invalid_login': "Identifiant (ou adresse courriel) et mot de passe ne "
                         "correspondent pas. Veuillez réessayer.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        champ = self.fields['username']
        champ.label = "Identifiant ou adresse courriel"
        champ.widget.attrs['placeholder'] = "Identifiant ou adresse courriel"
        champ.widget.attrs['autocomplete'] = 'username'
