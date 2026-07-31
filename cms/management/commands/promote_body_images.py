"""Récupère les visuels perdus en liste : quand un article (ou une page) n'a
pas d'image « à la une » mais porte une image dans son corps, cette image est
promue en vignette.

Contexte — audit du 31/07/2026 : l'import WordPress n'a repris l'image « à la
une » que pour les articles qui avaient une *featured image* déclarée côté WP.
Les autres gardent leur visuel dans le corps (balise <img> vers /media/), mais
les listes (une, manchette, page Ressources) tombent sur un cadre vide, car
`any_image_url` ne regarde que la vignette. Le fichier est là : il suffit de le
rattacher.

    python manage.py promote_body_images --dry-run     # inventaire, rien n'est écrit
    python manage.py promote_body_images               # applique
    python manage.py promote_body_images --section poitiers
"""

import os
import re

from django.core.files.images import ImageFile
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

RE_IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
RE_EMBED = re.compile(r'<embed[^>]+embedtype=["\']image["\'][^>]*\bid=["\'](\d+)["\']', re.I)


class Command(BaseCommand):
    help = ("Promeut la première image du corps en image « à la une » pour les "
            "articles et pages qui n'en ont pas.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, affiche seulement ce qui serait fait.")
        parser.add_argument('--section', default=None,
                            help="Ne traiter qu'un syndicat (slug de section).")
        parser.add_argument('--limit', type=int, default=None,
                            help="S'arrêter après N pages traitées.")

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        self.dry = options['dry_run']
        self.section = options['section']
        limit = options['limit']

        if self.dry:
            self.stdout.write(self.style.WARNING('DRY-RUN — aucune écriture.\n'))

        self.stats = {
            'promues': 0, 'deja_ok': 0, 'sans_image': 0,
            'fichier_absent': 0, 'image_creee': 0, 'image_reutilisee': 0,
            'brouillon_en_attente': 0,
        }
        traites = 0

        for modele in (ArticlePage, ContentPage):
            qs = modele.objects.live().order_by('pk')
            if self.section:
                qs = qs.filter(section_slug=self.section)
            for page in qs:
                if limit is not None and traites >= limit:
                    break
                if self._traiter(page):
                    traites += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Vignettes posées      : {self.stats['promues']}"))
        self.stdout.write(
            f"  images réutilisées  : {self.stats['image_reutilisee']}\n"
            f"  images créées       : {self.stats['image_creee']}")
        self.stdout.write(
            f"Déjà pourvues         : {self.stats['deja_ok']}\n"
            f"Aucune image au corps : {self.stats['sans_image']}\n"
            f"Fichier introuvable   : {self.stats['fichier_absent']}")
        if self.stats['brouillon_en_attente']:
            self.stdout.write(self.style.WARNING(
                f"Ignorées (brouillon en attente, republier les aurait mises "
                f"en ligne) : {self.stats['brouillon_en_attente']}"))
        if self.dry:
            self.stdout.write(self.style.WARNING('\n(DRY-RUN : rien n\'a été écrit.)'))

    # ------------------------------------------------------------------ #

    def _traiter(self, page):
        """Retourne True si la page a reçu (ou aurait reçu) une vignette."""
        # `any_image_url` n'existe que sur ArticlePage (repli legacy compris) ;
        # les ContentPage n'ont que la vignette.
        if page.featured_image_id or getattr(page, 'any_image_url', None):
            self.stats['deja_ok'] += 1
            return False

        # Une page qui a un brouillon en attente ne doit pas être republiée :
        # cela mettrait en ligne des modifications que personne n'a validées.
        if page.has_unpublished_changes:
            self.stats['brouillon_en_attente'] += 1
            return False

        image = self._image_du_corps(page)
        if image is None:
            return False

        titre = page.title[:50]
        if self.dry:
            self.stats['promues'] += 1
            self.stdout.write(f"  [{page.section_slug or 'principal':12}] {titre} "
                              f"← {image.file.name}")
            return True

        with transaction.atomic():
            page.featured_image = image
            page.save()
            # Republier pour que la version en ligne et le brouillon coïncident,
            # sinon la prochaine édition dans /cms/ effacerait la vignette.
            revision = page.save_revision()
            revision.publish()
        self.stats['promues'] += 1
        self.stdout.write(f"  [{page.section_slug or 'principal':12}] {titre} "
                          f"← {image.file.name}")
        return True

    def _image_du_corps(self, page):
        """Première image exploitable du corps, en objet Image Wagtail."""
        from wagtail.images.models import Image

        try:
            blocs = list(page.body)
        except Exception:
            self.stats['sans_image'] += 1
            return None

        for bloc in blocs:
            # 1. bloc image natif — déjà une Image Wagtail
            if bloc.block_type == 'image' and bloc.value:
                img = bloc.value.get('image') if hasattr(bloc.value, 'get') else bloc.value
                if img is not None:
                    self.stats['image_reutilisee'] += 1
                    return img

            brut = str(bloc.value)

            # 2. image insérée en texte riche : <embed embedtype="image" id="N">
            m = RE_EMBED.search(brut)
            if m:
                img = Image.objects.filter(pk=int(m.group(1))).first()
                if img is not None:
                    self.stats['image_reutilisee'] += 1
                    return img

            # 3. <img src="/media/…"> hérité de WordPress
            m = RE_IMG.search(brut)
            if m:
                return self._image_depuis_url(m.group(1), page)

        self.stats['sans_image'] += 1
        return None

    def _image_depuis_url(self, url, page):
        """Rattache une URL /media/… à une Image Wagtail (existante ou créée)."""
        from wagtail.images.models import Image

        prefixe = settings.MEDIA_URL or '/media/'
        if not url.startswith(prefixe):
            # URL externe (ancien serveur, CDN…) : on ne rapatrie pas de fichier.
            self.stats['fichier_absent'] += 1
            return None

        rel = url[len(prefixe):].split('?')[0]

        existante = Image.objects.filter(file=rel).first()
        if existante is not None:
            self.stats['image_reutilisee'] += 1
            return existante

        chemin = os.path.join(settings.MEDIA_ROOT, rel)
        if not os.path.exists(chemin):
            self.stats['fichier_absent'] += 1
            return None

        if self.dry:
            # En dry-run, ne rien créer : on renvoie un leurre porteur du nom.
            self.stats['image_creee'] += 1
            return _ImageFictive(rel)

        image = Image(title=page.title[:255], collection=self._collection(page))
        with open(chemin, 'rb') as fh:
            image.file = ImageFile(fh, name=os.path.basename(rel))
            image.save()
        self.stats['image_creee'] += 1
        return image

    def _collection(self, page):
        """Collection de médias du syndicat, sinon la racine."""
        from wagtail.models import Collection
        from cms.models import SectionPage

        racine = Collection.get_first_root_node()
        slug = page.section_slug
        if not slug:
            return racine
        section = SectionPage.objects.filter(slug=slug).first()
        if section is None:
            return racine
        return Collection.objects.filter(name=section.title).first() or racine


class _ImageFictive:
    """Substitut d'Image pour l'affichage en dry-run (aucune écriture)."""

    def __init__(self, rel):
        self.file = type('f', (), {'name': rel})()
