"""Retrouve les abonnés que le site croit inscrits et qu'OVH ne connaît pas.

La newsletter part vers les listes OVH, pas vers la table `Subscriber` : une
personne absente des listes ne reçoit rien, même si le site lui a affiché
« inscription confirmée » et que sa ligne est active en base.

Deux façons d'y tomber, toutes deux silencieuses avant cette commande :

1. **L'ajout a échoué.** `ovh_subscribe` journalise un avertissement et rend
   `None` ; la ligne locale reste active, `ovh_list` reste vide. Une panne
   d'API de quelques minutes suffit à perdre les inscriptions de la journée.
2. **L'ajout a réussi puis l'adresse a disparu** — retrait manuel chez OVH,
   liste recréée, plafond de 5 000 atteint entre-temps.

Le premier cas se lit en base seule. Le second demande d'énumérer les listes,
ce qui est le seul comptage fiable : le champ `nbSubscribers` d'OVH reste
périmé, parfois de plusieurs années.

Usage :
    python manage.py verifie_abonnes_ovh              # constat seul
    python manage.py verifie_abonnes_ovh --syndicat principal
    python manage.py verifie_abonnes_ovh --reparer    # réinscrit les manquants
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compare les abonnés actifs du site aux listes OVH et signale les absents"

    def add_arguments(self, parser):
        parser.add_argument(
            '--syndicat', default='',
            help="Slug d'un syndicat ; par défaut, tous ceux qui ont une liste.",
        )
        parser.add_argument(
            '--reparer', action='store_true',
            help="Réinscrit chez OVH les abonnés manquants (sinon : constat seul).",
        )
        parser.add_argument(
            '--limite', type=int, default=0,
            help="N'en réparer que N — pour essayer sans tout engager.",
        )

    def handle(self, *args, **options):
        from cms.models import SectionPage
        from content.models import Subscriber
        from content.ovh_sync import lists_for_site, ovh_subscribe
        from content.ovh_sync import site_de_diffusion

        cible = options['syndicat'].strip()
        reparer = options['reparer']
        limite = options['limite']

        sites = list(SectionPage.objects.all())
        if cible:
            sites = [s for s in sites if cible in (s.slug, s.legacy_site_slug)]
            if not sites:
                self.stderr.write(self.style.ERROR(f"Syndicat introuvable : {cible}"))
                return

        total_manquants = 0
        for site in sites:
            # Un syndicat sans liste OVH n'envoie pas dans le vide : ses
            # inscrits vont sur les listes de la confédération, c'est la règle
            # de `site_de_diffusion` depuis le 17/08/2026. Sauter ces
            # syndicats — ce que faisait cette commande à sa première version —
            # revenait à ignorer précisément là où les orphelins s'accumulent :
            # deux inscrits de Marseille de mars 2026 n'étaient sur AUCUNE
            # liste, et le rapport annonçait « aucun abonné manquant ».
            destination = site_de_diffusion(site)
            listes = lists_for_site(destination)
            if not listes:
                continue

            # Les abonnés confédéraux du webhook adhésion portent `site=None`
            # (cf. content/api_views.py) ; `cms/apps.py` les renvoie vers les
            # listes du principal. Les compter ici, sinon la moitié des
            # abonnés de la conf échappe à la vérification.
            abonnes = Subscriber.objects.filter(site=site, is_active=True)
            if site.slug == 'principal':
                abonnes = Subscriber.objects.filter(
                    is_active=True).filter(site__isnull=True) | abonnes

            adresses = {a.email.strip().lower(): a for a in abonnes}
            if not adresses:
                continue

            chez_ovh = set()
            illisible = []
            for nom in listes:
                try:
                    from cms.ovh_client import get_subscribers
                    chez_ovh.update(e.strip().lower() for e in get_subscribers(nom))
                except Exception as e:
                    illisible.append(f'{nom} ({e})')

            if illisible:
                # Sans la liste, tout paraîtrait manquant : mieux vaut ne rien
                # dire que dénoncer des absents qui n'en sont pas.
                self.stderr.write(self.style.ERROR(
                    f"{site.title} : listes illisibles, syndicat ignoré — "
                    f"{' ; '.join(illisible)}"))
                continue

            manquants = [a for cle, a in sorted(adresses.items()) if cle not in chez_ovh]
            total_manquants += len(manquants)

            vers = '' if destination.pk == site.pk else f" → listes de {destination.title}"
            self.stdout.write(
                f"{site.title} : {len(adresses)} abonné(s) actif(s), "
                f"{len(chez_ovh)} chez OVH ({', '.join(listes)}){vers} — "
                f"{len(manquants)} absent(s) des listes")

            for abonne in manquants:
                cause = "jamais posé" if not abonne.ovh_list else f"posé sur {abonne.ovh_list}, disparu depuis"
                self.stdout.write(f"    {abonne.email}  [{cause}]")

            if reparer and manquants:
                a_traiter = manquants[:limite] if limite else manquants
                repares = 0
                for abonne in a_traiter:
                    choisie = ovh_subscribe(destination, abonne.email)
                    if choisie:
                        Subscriber.objects.filter(pk=abonne.pk).update(ovh_list=choisie)
                        repares += 1
                    else:
                        self.stderr.write(self.style.WARNING(
                            f"    échec de réinscription : {abonne.email}"))
                self.stdout.write(self.style.SUCCESS(
                    f"  → {repares}/{len(a_traiter)} réinscrit(s)"))

        if not total_manquants:
            self.stdout.write(self.style.SUCCESS(
                "Aucun abonné manquant : le site et OVH disent la même chose."))
        elif not reparer:
            self.stdout.write(self.style.WARNING(
                f"\n{total_manquants} abonné(s) actif(s) ne reçoivent RIEN. "
                f"Relancer avec --reparer pour les réinscrire."))
