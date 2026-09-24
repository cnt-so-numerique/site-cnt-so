"""Supprime les données personnelles au-delà des durées annoncées.

Les mentions légales promettent des durées de conservation (décidées par
Arnaud le 24/09/2026). Avant cette commande, rien n'était jamais supprimé :
une promesse que le site ne tenait pas. Or écrire à un syndicat peut révéler
une appartenance syndicale, donnée sensible au sens de l'article 9 du RGPD.

⚠️ Changer une durée ici, c'est changer ce que disent les mentions légales :
les deux doivent rester d'accord.

Lancée chaque nuit par le timer systemd `cntso-purge.timer` (pas de cron sur
la prod) :

    cd /var/www/cntso && venv/bin/python manage.py purge_donnees_personnelles
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from content.models import ContactMessage, Subscriber

#: Messages du formulaire de contact : deux ans.
CONSERVATION_CONTACT = timedelta(days=730)

#: Abonnés non confirmés ou désinscrits : trente jours. Un abonné actif reste
#: jusqu'à sa désinscription ; la ligne d'un désinscrit n'a plus d'objet (sa
#: sortie des listes OVH est faite au moment même où il se désinscrit).
CONSERVATION_ABONNE_INACTIF = timedelta(days=30)


class Command(BaseCommand):
    help = "Supprime les messages de contact et les abonnés inactifs trop anciens."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Compter sans rien supprimer.")

    def handle(self, *args, dry_run=False, **options):
        maintenant = timezone.now()
        messages = ContactMessage.objects.filter(
            created_at__lt=maintenant - CONSERVATION_CONTACT)
        abonnes = Subscriber.objects.filter(
            is_active=False,
            subscribed_at__lt=maintenant - CONSERVATION_ABONNE_INACTIF)

        nb_messages, nb_abonnes = messages.count(), abonnes.count()
        if not dry_run:
            messages.delete()
            abonnes.delete()

        verbe = 'à supprimer' if dry_run else 'supprimés'
        self.stdout.write(
            f'{nb_messages} message(s) de contact et '
            f'{nb_abonnes} abonné(s) inactif(s) {verbe}.')
