"""Réimporte les galeries de la banque d'images, restées dans le legacy.

L'import WordPress a recréé les 13 articles de la rubrique « Banque d'image »
avec leur image de couverture, mais SANS convertir leurs galeries : 12 des 13
articles avaient un corps entièrement vide, et les 113 visuels dormaient dans
`content.Article` sous forme de blocs EditorJS (constaté le 16/08/2026). La
rubrique proposée depuis l'accueil s'ouvrait donc sur des pages blanches.

Cette commande relit ces galeries et les réécrit en vrais blocs Wagtail, avec
de vraies images de la médiathèque — réutilisables ensuite par les rédacteurs.

Elle NE touche pas aux fichiers : elle ne fait qu'enregistrer dans la
médiathèque des fichiers déjà présents sous MEDIA_ROOT. C'est volontaire —
relancer l'import média écraserait des retouches faites à la main.

Usage :
    python manage.py importe_banque_images --dry-run
    python manage.py importe_banque_images
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.management.commands.migrate_images import _find_or_create_wagtail_image


def _images_du_legacy(contenu):
    """Extrait [(url, légende)] des blocs galerie/image d'un contenu EditorJS."""
    if not contenu:
        return []
    try:
        blocs = json.loads(contenu).get('blocks', [])
    except (ValueError, TypeError):
        return []

    trouvees = []
    for bloc in blocs:
        type_ = bloc.get('type')
        data = bloc.get('data', {}) or {}
        if type_ == 'gallery':
            for img in data.get('images', []) or []:
                url = (img or {}).get('url')
                if url:
                    trouvees.append((url, (img.get('caption') or '').strip()))
        elif type_ == 'image':
            fichier = data.get('file') or {}
            url = fichier.get('url') or data.get('url')
            if url:
                trouvees.append((url, (data.get('caption') or '').strip()))
    return trouvees


class Command(BaseCommand):
    help = "Réimporte en blocs Wagtail les galeries de la banque d'images."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, affiche seulement ce qui serait fait.")
        parser.add_argument('--categorie', default='banque-dimage')
        parser.add_argument('--section', default='principal')
        parser.add_argument('--colonnes', type=int, default=3)

    def handle(self, *args, **options):
        from cms.models import ArticlePage, CmsCategory
        from content.models import Article as ArticleLegacy

        sec = options['section']
        cat = CmsCategory.objects.filter(slug=options['categorie'],
                                         section_slug=sec).first()
        if not cat:
            self.stderr.write(self.style.ERROR(
                f"Catégorie « {options['categorie']} » introuvable pour « {sec} »."))
            return

        articles = ArticlePage.objects.filter(cms_categories=cat).order_by('pk')
        media_root = settings.MEDIA_ROOT
        cache = {}
        total_img = total_art = 0
        manquants = []

        for art in articles:
            # Idempotence : on ne repasse pas sur un article déjà pourvu.
            if any(b.get('type') == 'gallery' for b in (art.body.raw_data or [])):
                self.stdout.write(f"  = {art.title[:44]:46s} galerie déjà présente")
                continue

            legacy = (ArticleLegacy.objects.filter(pk=art.legacy_article_id).first()
                      if art.legacy_article_id else None)
            if not legacy:
                self.stdout.write(f"  · {art.title[:44]:46s} aucun legacy associé")
                continue

            paires = _images_du_legacy(legacy.content)
            if not paires:
                self.stdout.write(f"  · {art.title[:44]:46s} aucune image dans le legacy")
                continue

            items, absents = [], 0
            for url, legende in paires:
                if options['dry_run']:
                    # En simulation, on ne crée rien : on vérifie seulement que
                    # le fichier est là, sinon le compte annoncé serait faux.
                    from pathlib import Path
                    rel = url[len('/media/'):] if url.startswith('/media/') else url.lstrip('/')
                    if (Path(media_root) / rel).exists():
                        items.append(None)
                    else:
                        absents += 1
                        manquants.append(url)
                    continue

                img = _find_or_create_wagtail_image(url, media_root, cache)
                if img is None:
                    absents += 1
                    manquants.append(url)
                    continue
                items.append({'image': img, 'caption': legende})

            if not items:
                self.stdout.write(self.style.WARNING(
                    f"  ! {art.title[:44]:46s} aucun fichier trouvé ({absents} manquants)"))
                continue

            if not options['dry_run']:
                with transaction.atomic():
                    blocs = [(b.block_type, b.value) for b in art.body]
                    blocs.append(('gallery', {'images': items,
                                              'columns': options['colonnes']}))
                    art.body = blocs
                    art.save()
                    # Passer par une révision publiée : sinon la modification
                    # n'apparaît pas dans l'historique de /cms/.
                    art.save_revision().publish()

            total_img += len(items)
            total_art += 1
            suffixe = f" ({absents} fichiers manquants)" if absents else ""
            self.stdout.write(self.style.SUCCESS(
                f"  + {art.title[:44]:46s} {len(items)} images{suffixe}"))

        entete = "[SIMULATION] " if options['dry_run'] else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{entete}{total_art} articles pourvus, {total_img} images."))
        if manquants:
            self.stdout.write(self.style.WARNING(
                f"{len(manquants)} fichiers introuvables sous MEDIA_ROOT :"))
            for u in manquants[:15]:
                self.stdout.write(f"    {u}")
