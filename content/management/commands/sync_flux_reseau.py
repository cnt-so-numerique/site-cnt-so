"""Moissonne les flux RSS/Atom des syndicats hébergés ailleurs.

Ces syndicats (le STAA, le TAS) n'ont aucune `ArticlePage` chez nous : sans ce
moissonnage, ils sont absents du cartouche « Les nouvelles du réseau » de
l'accueil confédéral.

La lecture des flux se fait ICI, dans une tâche périodique, et jamais pendant
le rendu d'une page : un serveur voisin en panne ou lent ferait autrement
tomber ou ramer l'accueil de la confédération.

À lancer par cron, une fois par heure :

    cd /var/www/cntso && venv/bin/python manage.py sync_flux_reseau
"""

import logging
from datetime import datetime, timezone as dt_timezone

import feedparser
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from cms.models import SectionPage
from content.models import ExternalArticle

logger = logging.getLogger(__name__)

#: Au-delà, les articles les plus anciens sont purgés : le cartouche n'en
#: montre que quelques-uns, garder tout l'historique d'un site qu'on n'héberge
#: pas ferait grossir la base pour rien.
MAX_PAR_SITE = 20

TIMEOUT = 15
USER_AGENT = 'CNT-SO feed reader (+https://cnt-so.org/)'


def _date_entree(entree):
    """Date de publication d'une entrée, en UTC, à défaut maintenant.

    Un flux sans date n'est pas une raison d'ignorer l'article : il arrive
    alors en tête, ce qui est le comportement le moins surprenant pour une
    entrée qu'on découvre à l'instant.
    """
    for champ in ('published_parsed', 'updated_parsed'):
        struct = entree.get(champ)
        if struct:
            return datetime(*struct[:6], tzinfo=dt_timezone.utc)
    return timezone.now()


class Command(BaseCommand):
    help = "Moissonne les flux RSS des syndicats hébergés sur un site externe."

    def add_arguments(self, parser):
        parser.add_argument(
            '--site', dest='site',
            help="Ne traiter que ce syndicat (slug Wagtail).",
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Lire les flux et afficher le résultat sans rien écrire.",
        )

    def handle(self, *args, **options):
        sections = SectionPage.objects.filter(live=True)
        if options['site']:
            sections = sections.filter(slug=options['site'])

        sections = [s for s in sections if s.get_feed_url()]
        if not sections:
            self.stdout.write("Aucun syndicat à flux externe.")
            return

        for section in sections:
            self._traiter(section, dry_run=options['dry_run'])

    def _traiter(self, section, dry_run=False):
        url = section.get_feed_url()
        try:
            reponse = self._telecharger(section, url)
        except requests.RequestException as exc:
            # Un flux injoignable ne doit ni interrompre les autres syndicats
            # ni faire échouer le cron : les articles déjà en base restent
            # affichés, on réessaiera à l'heure suivante.
            logger.warning("Flux illisible pour %s (%s) : %s", section.slug, url, exc)
            self.stderr.write(self.style.WARNING(
                f"{section.title} : flux illisible ({exc})"))
            return

        if reponse is None:
            self.stdout.write(f"{section.title} : inchangé depuis la dernière synchro.")
            return

        entrees = feedparser.parse(reponse.content).entries
        if not entrees:
            logger.warning("Flux vide ou illisible pour %s (%s)", section.slug, url)
            self.stderr.write(self.style.WARNING(f"{section.title} : flux vide."))
            return

        nouveaux = inchanges = 0
        for entree in entrees[:MAX_PAR_SITE]:
            lien = (entree.get('link') or '').strip()
            titre = (entree.get('title') or '').strip()
            if not lien or not titre:
                continue
            if dry_run:
                nouveaux += 1
                self.stdout.write(f"  · {titre} — {lien}")
                continue
            _, cree = ExternalArticle.objects.update_or_create(
                section=section,
                guid=(entree.get('id') or lien)[:500],
                defaults={
                    'title': titre[:500],
                    'url': lien[:500],
                    'published_at': _date_entree(entree),
                },
            )
            nouveaux += cree
            inchanges += not cree

        if dry_run:
            self.stdout.write(f"{section.title} : {nouveaux} entrées lues (à blanc).")
            return

        self._purger(section)
        section.feed_etag = reponse.headers.get('ETag', '')[:255]
        section.feed_last_sync = timezone.now()
        SectionPage.objects.filter(pk=section.pk).update(
            feed_etag=section.feed_etag, feed_last_sync=section.feed_last_sync)
        self.stdout.write(self.style.SUCCESS(
            f"{section.title} : {nouveaux} nouveaux, {inchanges} déjà connus."))

    def _telecharger(self, section, url):
        """Télécharge le flux, ou renvoie None s'il n'a pas changé.

        L'en-tête `If-None-Match` évite de retélécharger toutes les heures un
        flux identique chez un syndicat voisin qui nous héberge gratuitement
        sa bande passante.
        """
        entetes = {'User-Agent': USER_AGENT}
        if section.feed_etag:
            entetes['If-None-Match'] = section.feed_etag
        reponse = requests.get(url, timeout=TIMEOUT, headers=entetes)
        if reponse.status_code == 304:
            return None
        reponse.raise_for_status()
        return reponse

    def _purger(self, section):
        """Ne garde que les `MAX_PAR_SITE` articles les plus récents du site."""
        a_garder = (
            ExternalArticle.objects.filter(section=section)
            .order_by('-published_at')
            .values_list('pk', flat=True)[:MAX_PAR_SITE]
        )
        (ExternalArticle.objects.filter(section=section)
         .exclude(pk__in=list(a_garder))
         .delete())
