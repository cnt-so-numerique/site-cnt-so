"""Dernier recours : retirer tous les téléphones d'un compte, depuis le serveur.

Pour le cas où plus personne ne peut entrer dans /cms/ pour le faire : par
exemple le seul superutilisateur, qui a perdu son téléphone ET ses codes de
secours. Le compte se reconnecte alors au mot de passe seul (un
superutilisateur devra réenregistrer un téléphone aussitôt).

    python manage.py retire_double_auth <identifiant>
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cms.double_auth import retirer_telephone, telephones


class Command(BaseCommand):
    help = "Retire tous les téléphones (et codes de secours) d'un compte."

    def add_arguments(self, parser):
        parser.add_argument('identifiant')

    def handle(self, identifiant, **options):
        try:
            user = get_user_model().objects.get_by_natural_key(identifiant)
        except get_user_model().DoesNotExist:
            raise CommandError(f"Aucun compte « {identifiant} ».")
        noms = [t.name for t in telephones(user)]
        for telephone in telephones(user):
            retirer_telephone(telephone)
        if noms:
            self.stdout.write(f"{len(noms)} téléphone(s) retiré(s) de {identifiant} : {', '.join(noms)}")
        else:
            self.stdout.write(f"{identifiant} n'avait aucun téléphone.")
