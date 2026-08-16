"""
Migre les images pour les ArticlePages déjà créées.
- Crée les WagtailImage depuis les fichiers locaux
- Met à jour featured_image sur chaque ArticlePage
- Convertit les blocs HTML image/gallery en vrais blocs StreamField

Usage:
    python manage.py migrate_images
    python manage.py migrate_images --dry-run
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction


def _empreinte(chemin):
    """Empreinte SHA-1 du contenu, calculée comme Wagtail le fait lui-même."""
    from wagtail.utils.file import hash_filelike
    with open(chemin, 'rb') as f:
        return hash_filelike(f)


def _image_deja_importee(WImage, abs_path):
    """Retrouve l'image déjà en médiathèque correspondant à ce fichier.

    On ne peut PAS chercher sur le chemin : `AbstractImage.get_upload_to()`
    passe le nom entier dans `get_valid_name()`, ce qui supprime les barres
    obliques — « uploads/2019/02/casque-2.png » est stocké
    « original_images/uploads201902casque-2.png ». Wagtail tronque en plus au
    delà de 95 caractères et suffixe en cas de collision. L'ancienne recherche
    `file=relative` ne pouvait donc jamais aboutir : chaque exécution recréait
    les mêmes images (relevé par Arnaud, 16/08/2026).

    La seule clé stable est le contenu. Mais `file_hash` n'est rempli par
    Wagtail qu'à la demande — il était vide sur la totalité des 2 221 images en
    production — donc chercher uniquement dessus aurait tout dupliqué. On
    passe donc par un filtre de nom (large, juste pour restreindre), puis on
    tranche sur l'empreinte, qu'on en profite pour mémoriser au passage.
    """
    empreinte = _empreinte(abs_path)

    connue = WImage.objects.filter(file_hash=empreinte).first()
    if connue:
        return connue

    # Le radical du nom survit à l'aplatissement : il sert de présélection.
    radical = Path(abs_path).stem
    if not radical:
        return None
    for candidat in WImage.objects.filter(file__contains=radical,
                                          file_hash='')[:50]:
        try:
            with candidat.open_file() as f:
                from wagtail.utils.file import hash_filelike
                h = hash_filelike(f)
        except Exception:
            continue
        # Mémoriser l'empreinte évite de relire ce fichier aux exécutions
        # suivantes : la médiathèque se rattrape d'elle-même, sans commande
        # de reprise à lancer.
        candidat.file_hash = h
        candidat.save(update_fields=['file_hash'])
        if h == empreinte:
            return candidat
    return None


def _find_or_create_wagtail_image(url, media_root, cache):
    """Crée ou retrouve une WagtailImage depuis une URL /media/..."""
    if not url:
        return None
    if url in cache:
        return cache[url]

    from wagtail.images import get_image_model
    WImage = get_image_model()

    if url.startswith('/media/'):
        relative = url[len('/media/'):]
    elif url.startswith('http'):
        cache[url] = None
        return None
    else:
        relative = url.lstrip('/')

    abs_path = Path(media_root) / relative
    if not abs_path.exists():
        cache[url] = None
        return None

    existing = _image_deja_importee(WImage, abs_path)
    if existing:
        cache[url] = existing
        return existing

    try:
        from django.core.files.base import File
        from PIL import Image as PILImage

        with open(abs_path, 'rb') as f:
            with PILImage.open(f) as pil:
                width, height = pil.size

        wimg = WImage(title=abs_path.name, width=width, height=height)
        with open(abs_path, 'rb') as f:
            wimg.file.save(relative, File(f), save=False)
        # Renseigner l'empreinte dès la création : sans elle, la prochaine
        # exécution repartirait sur la présélection par nom.
        wimg.file_hash = _empreinte(abs_path)
        wimg.save()
        cache[url] = wimg
        return wimg
    except Exception as e:
        cache[url] = None
        return None


def _upgrade_body_blocks(body_json_str, media_root, cache):
    """
    Re-parcourt les blocs StreamField et convertit les html-image-fallback
    en vrais blocs image/gallery.
    """
    if not body_json_str:
        return body_json_str, 0

    try:
        blocks = json.loads(body_json_str)
    except json.JSONDecodeError:
        return body_json_str, 0

    upgraded = 0
    new_blocks = []

    for block in blocks:
        if block.get('type') == 'html':
            val = block.get('value', '')
            # Détecte <figure><img src="..."/></figure> (fallback image unique)
            m = re.match(r'<figure[^>]*><img src="([^"]+)"[^>]*/></figure>', val.strip())
            if m:
                url = m.group(1)
                wimg = _find_or_create_wagtail_image(url, media_root, cache)
                if wimg:
                    block = {
                        'type': 'image',
                        'value': {'image': wimg.pk, 'caption': '', 'alignment': 'center'},
                        'id': block.get('id'),
                    }
                    upgraded += 1

        new_blocks.append(block)

    return json.dumps(new_blocks), upgraded


class Command(BaseCommand):
    help = "Migre les images pour les ArticlePages déjà créées (featured_image + blocs body)"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from django.conf import settings as django_settings
        from content.models import Article, Media
        from cms.models import ArticlePage

        media_root = str(django_settings.MEDIA_ROOT)
        dry_run = options['dry_run']
        img_cache = {}

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY-RUN ==='))

        qs = ArticlePage.objects.filter(
            legacy_article_id__isnull=False
        ).only('pk', 'legacy_article_id', 'featured_image_id', 'body')

        total = qs.count()
        self.stdout.write(f'{total} ArticlePages à traiter...')

        featured_updated = 0
        body_upgraded = 0
        errors = 0

        with transaction.atomic():
            articles_map = {
                a.pk: a for a in Article.objects.filter(
                    pk__in=qs.values_list('legacy_article_id', flat=True)
                ).select_related('featured_image')
            }

            for i, ap in enumerate(qs.iterator(chunk_size=100)):
                orig = articles_map.get(ap.legacy_article_id)
                if not orig:
                    continue

                update_fields = []

                # 1. Featured image
                if not ap.featured_image_id and orig.featured_image:
                    media = orig.featured_image
                    url = media.url  # property: local file ou original_url
                    if url and not url.startswith('http'):
                        # URL locale → convertir en URL /media/...
                        if not url.startswith('/'):
                            url = '/' + url
                    wimg = _find_or_create_wagtail_image(url, media_root, img_cache)
                    if wimg:
                        ap.featured_image = wimg
                        update_fields.append('featured_image')
                        featured_updated += 1

                # 2. Body blocs
                if ap.body:
                    new_body, n = _upgrade_body_blocks(str(ap.body), media_root, img_cache)
                    if n > 0:
                        ap.body = new_body
                        update_fields.append('body')
                        body_upgraded += n

                if update_fields and not dry_run:
                    try:
                        ap.save(update_fields=update_fields)
                    except Exception as e:
                        errors += 1
                        self.stderr.write(f'  ✗ ArticlePage {ap.pk}: {e}')

                if (i + 1) % 200 == 0:
                    self.stdout.write(f'  ... {i + 1}/{total}')

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {featured_updated} images à la une, '
            f'{body_upgraded} blocs image upgradés, {errors} erreurs.'
        ))
