"""Prévient technique@ quand une tâche systemd échoue.

Appelée par `OnFailure=` : si `pg-backup.service` rate une nuit, personne ne
l'apprendrait avant d'avoir besoin d'une sauvegarde. C'est le pire moment pour
découvrir qu'il n'y en a plus (audit du 04/09/2026).

Une commande Django plutôt qu'un script isolé : elle vit dans le dépôt, elle se
teste, et elle réutilise l'envoi de courriel déjà en service — le serveur n'a
aucun client mail en ligne de commande.

Usage (par systemd) :
    python manage.py alerte_echec pg-backup.service
"""
import subprocess

from django.conf import settings
from django.core.mail import mail_admins
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Envoie une alerte aux ADMINS après l'échec d'une unité systemd"

    def add_arguments(self, parser):
        parser.add_argument('unite', help="nom de l'unité, ex. pg-backup.service")
        parser.add_argument('--lignes', type=int, default=30,
                            help="lignes de journal à joindre (défaut 30)")

    def handle(self, *args, **options):
        unite = options['unite']

        if not settings.ADMINS:
            self.stderr.write(
                "ADMINS est vide : aucune alerte ne partirait. "
                "Définir DJANGO_ADMINS dans l'environnement du service.")
            return

        journal = self._journal(unite, options['lignes'])
        corps = (
            f"L'unité systemd « {unite} » a échoué sur le serveur de "
            f"production.\n\n"
            f"Dernières lignes de son journal :\n\n{journal}\n\n"
            f"Pour en savoir plus :\n"
            f"    ssh debian@51.91.242.64\n"
            f"    sudo systemctl status {unite}\n"
            f"    sudo journalctl -u {unite} -n 100\n"
        )
        mail_admins(f"Échec de {unite}", corps, fail_silently=False)
        self.stdout.write(self.style.SUCCESS(
            f"Alerte envoyée à {', '.join(a[1] for a in settings.ADMINS)}"))

    @staticmethod
    def _journal(unite, lignes):
        """Les dernières lignes du journal, ou une explication si on ne peut pas.

        `journalctl` peut être refusé selon les droits du compte : mieux vaut
        une alerte sans extrait qu'aucune alerte.
        """
        try:
            sortie = subprocess.run(
                ['journalctl', '-u', unite, '-n', str(lignes), '--no-pager'],
                capture_output=True, text=True, timeout=20,
            )
            return sortie.stdout.strip() or sortie.stderr.strip() or '(journal vide)'
        except Exception as erreur:  # pragma: no cover - dépend de l'hôte
            return f"(journal illisible : {type(erreur).__name__} — {erreur})"
