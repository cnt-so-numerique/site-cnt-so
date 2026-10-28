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

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from content.models import Comment, ContactMessage, Subscriber

#: Messages du formulaire de contact : deux ans.
CONSERVATION_CONTACT = timedelta(days=730)

#: Abonnés non confirmés ou désinscrits : trente jours. Un abonné actif reste
#: jusqu'à sa désinscription ; la ligne d'un désinscrit n'a plus d'objet (sa
#: sortie des listes OVH est faite au moment même où il se désinscrit — ou
#: retentée ici si OVH l'avait refusée : la ligne attend alors son retrait).
CONSERVATION_ABONNE_INACTIF = timedelta(days=30)

#: Commentaires (hérités de WordPress) : l'adresse et l'IP de l'auteur partent
#: au bout de deux ans, comme un message de contact. Le nom et le texte, publiés,
#: restent.
CONSERVATION_COMMENTAIRE = timedelta(days=730)


class Command(BaseCommand):
    help = ("Supprime les messages de contact et les abonnés inactifs trop "
            "anciens, anonymise les vieux commentaires, vide les sessions expirées.")

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
        commentaires = (Comment.objects
                        .filter(created_at__lt=maintenant - CONSERVATION_COMMENTAIRE)
                        .exclude(author_email='', author_ip=None))

        nb_messages, nb_commentaires = messages.count(), commentaires.count()
        en_attente = 0
        if not dry_run:
            en_attente = self._retenter_les_retraits_ovh(abonnes)
        abonnes = abonnes.filter(ovh_list='') if not dry_run else abonnes
        nb_abonnes = abonnes.count()
        if not dry_run:
            messages.delete()
            abonnes.delete()
            commentaires.update(author_email='', author_ip=None)
            call_command('clearsessions')

        verbe = 'à supprimer' if dry_run else 'supprimés'
        self.stdout.write(
            f'{nb_messages} message(s) de contact et '
            f'{nb_abonnes} abonné(s) inactif(s) {verbe}, '
            f'{nb_commentaires} commentaire(s) anonymisé(s).')
        if en_attente:
            self.stderr.write(
                f'{en_attente} abonné(s) inactif(s) gardé(s) : OVH refuse encore '
                f'leur retrait, la ligne reste comme trace pour la nuit suivante.')

    @staticmethod
    def _retenter_les_retraits_ovh(abonnes):
        """Une ligne inactive dont `ovh_list` est encore renseigné attend son
        retrait : OVH l'a refusé au désabonnement. La supprimer effacerait la
        seule trace que la personne reçoit encore la lettre. On retente ; en cas
        de nouvel échec, elle attend la nuit suivante."""
        from cms.apps import listes_de_labonne
        from content.ovh_sync import ovh_unsubscribe

        en_attente = 0
        for abonne in abonnes.exclude(ovh_list=''):
            site = listes_de_labonne(abonne)
            if site is not None and ovh_unsubscribe(site, abonne.email):
                Subscriber.objects.filter(pk=abonne.pk).update(ovh_list='')
            else:
                en_attente += 1
        return en_attente
