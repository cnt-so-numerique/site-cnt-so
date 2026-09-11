"""Range sous son syndicat un article que la confédération portait.

Le site WordPress confédéral relayait les articles de ses syndicats, et
l'import les a rangés sous la conf. Mesuré le 11/09/2026 : cinq articles de la
catégorie STUCS (« communication-culture-spectacle ») vivaient sous « principal »
— le STUCS en était privé sur son propre site.

    python manage.py rend_au_syndicat --section stucs --slug un-article --dry-run
    python manage.py rend_au_syndicat --section stucs --slug un-article --slug un-autre

Ce que fait le déplacement, et pourquoi chaque étape :

- **la page change de parent** dans l'arbre Wagtail : un simple changement
  d'étiquette `section_slug` laisserait l'article sous la conf dans le CMS ;
- **`section_slug` suit** : aucun crochet ne le fait au déplacement, et c'est
  lui que filtrent toutes les vues publiques ;
- **les rubriques sont remplacées** par celles du syndicat qui portent le même
  slug. Aucune n'est créée — l'arbre des rubriques est rangé à la main — et
  celles qui n'ont pas d'équivalent sont nommées dans le compte rendu ;
- **la dernière révision est alignée** : l'éditeur ouvre la révision, pas
  l'objet vivant. Sans cela, le rédacteur verrait l'ancien rattachement et sa
  prochaine publication défairait le déplacement.

L'ancienne adresse `/article/<slug>/` ne casse pas : la vue confédérale renvoie
d'elle-même vers le syndicat propriétaire (302, `ArticlePage.dun_syndicat_publie`).

Une page qui a un brouillon en attente est laissée où elle est : la déplacer
publierait le travail non validé de quelqu'un d'autre.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from cms.models import ArticlePage, CmsCategory, SectionPage


class Command(BaseCommand):
    help = "Range sous un syndicat des articles que la confédération portait."

    def add_arguments(self, parser):
        parser.add_argument('--section', required=True,
                            help="Slug du syndicat de destination (ex. stucs).")
        parser.add_argument('--slug', action='append', required=True,
                            help="Slug d'un article à déplacer. Répétable.")
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        cible = options['section']
        sec = options['dry_run']
        syndicat = SectionPage.objects.filter(slug=cible).first()
        if syndicat is None:
            self.stderr.write(f'SectionPage « {cible} » introuvable.')
            return
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))

        rendus = ignores = 0
        for slug in options['slug']:
            candidats = ArticlePage.objects.filter(slug=slug).exclude(section_slug=cible)
            if candidats.count() != 1:
                ignores += 1
                etat = 'introuvable' if not candidats.exists() else \
                    f'{candidats.count()} articles portent ce slug'
                self.stdout.write(self.style.WARNING(f'  ? {slug[:60]} : {etat}, ignoré'))
                continue
            page = candidats.get()
            if page.has_unpublished_changes:
                ignores += 1
                self.stdout.write(self.style.WARNING(
                    f'  ? {page.title[:50]!r} a un brouillon en attente : ignoré'))
                continue

            gardees, perdues = self._rubriques(page, cible)
            self.stdout.write(
                f"  {'[simulé] ' if sec else ''}{page.title[:52]:54} "
                f"{page.section_slug} → {cible}")
            if gardees:
                self.stdout.write(f"      rubriques : {', '.join(c.slug for c in gardees)}")
            if perdues:
                self.stdout.write(f"      sans équivalent chez {cible}, retirées : "
                                  f"{', '.join(perdues)}")
            rendus += 1
            if sec:
                continue

            with transaction.atomic():
                page.move(syndicat, pos='last-child')
                # Le déplacement travaille sur une copie de l'arbre : on relit.
                page = ArticlePage.objects.get(pk=page.pk)
                page.section_slug = cible
                page.cms_categories.set(gardees)
                # ParentalManyToManyField : set() ne persiste qu'au save().
                page.save()
                self._aligne_revision(page, cible, gardees)

        self.stdout.write(self.style.SUCCESS(
            f'\n{rendus} article(s) rendu(s) à « {cible} », {ignores} ignoré(s).'))

    def _rubriques(self, page, cible):
        """Les rubriques du syndicat qui répondent à celles de l'article."""
        gardees, perdues = [], []
        for c in page.cms_categories.all():
            equivalente = CmsCategory.objects.filter(slug=c.slug, section_slug=cible).first()
            if equivalente is None:
                perdues.append(c.slug)
            else:
                gardees.append(equivalente)
        return gardees, perdues

    def _aligne_revision(self, page, cible, gardees):
        revision = page.latest_revision
        if revision is None:
            return
        contenu = revision.content
        if not isinstance(contenu, dict):
            return
        contenu['section_slug'] = cible
        if 'cms_categories' in contenu:
            contenu['cms_categories'] = [c.pk for c in gardees]
        revision.content = contenu
        revision.save(update_fields=['content'])
