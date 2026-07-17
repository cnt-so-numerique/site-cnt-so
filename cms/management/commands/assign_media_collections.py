"""
Ventile les images et documents de la collection Root vers les collections
par syndicat, d'après leurs utilisations réelles (ReferenceIndex Wagtail).

Règles :
- utilisé par un seul syndicat → collection de ce syndicat ;
- utilisé par plusieurs syndicats → « Commun » (visuels partagés) ;
- non utilisé (ou utilisé hors contenu de syndicat) → reste dans Root,
  visible du seul chef ; signalé dans le rapport.

Deux passes de détection : les références structurées (ReferenceIndex
Wagtail : image mise en avant, blocs image…), puis une recherche du nom de
fichier dans les corps de contenus (Wagtail + legacy WordPress) — l'import
Éducation, notamment, insérait les médias par URL brute, invisibles pour
l'index.

À lancer après `rebuild_references_index` si le contenu a été importé par
scripts (l'index n'est maintenu automatiquement qu'aux saves).

Usage:
    python manage.py assign_media_collections --dry-run
    python manage.py assign_media_collections
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ventile images/documents de Root vers les collections par syndicat selon leurs utilisations"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Affiche la ventilation sans rien déplacer")

    def handle(self, *args, **options):
        from wagtail.documents.models import Document
        from wagtail.images.models import Image
        from wagtail.models import Collection

        from cms.provisioning import commun_collection

        self.dry = options['dry_run']
        self._coll_cache = {}
        self._src_cache = {}
        self._corpus = None
        root = Collection.get_first_root_node()
        commun = commun_collection()

        for model, label in ((Image, 'images'), (Document, 'documents')):
            self._assign(model, label, root, commun)

        if self.dry:
            self.stdout.write(self.style.WARNING('Dry-run : rien n\'a été déplacé.'))
        else:
            self.stdout.write(self.style.SUCCESS('Ventilation terminée.'))

    def _slug_of(self, obj):
        """Syndicat auquel appartient un objet référençant un média."""
        from cms.models import HomePage, SectionPage
        if isinstance(obj, SectionPage):
            return obj.legacy_site_slug or obj.slug
        slug = getattr(obj, 'section_slug', None)
        if slug:
            return slug
        if isinstance(obj, HomePage):
            return 'principal'
        site = getattr(obj, 'site', None)
        if isinstance(site, SectionPage):
            return site.legacy_site_slug or site.slug
        return None

    def _collection_for_slug(self, slug):
        """Collection de médias du syndicat désigné par ce slug (None si le
        syndicat ou son groupe n'existent pas)."""
        if slug in self._coll_cache:
            return self._coll_cache[slug]
        from django.contrib.auth.models import Group
        from django.db.models import Q
        from cms.models import SectionPage
        from cms.provisioning import section_collection

        collection = None
        section = SectionPage.objects.filter(
            Q(slug=slug) | Q(legacy_site_slug=slug)).first()
        if section is not None:
            gslug = section.legacy_site_slug or section.slug
            group = Group.objects.filter(name=f'redacteur_{gslug}').first()
            if group is not None:
                collection = section_collection(group, section)
        self._coll_cache[slug] = collection
        return collection

    def _source_of(self, ref):
        """Objet source d'une référence, avec cache (une image est souvent
        référencée plusieurs fois par le même objet)."""
        key = (ref.content_type_id, ref.object_id)
        if key not in self._src_cache:
            try:
                self._src_cache[key] = ref.content_type.get_object_for_this_type(
                    pk=ref.object_id)
            except Exception:
                self._src_cache[key] = None
        return self._src_cache[key]

    def _url_corpus(self):
        """Corps de contenus par syndicat (texte brut), construit une fois :
        pages Wagtail (StreamField) + modèles legacy WordPress."""
        if self._corpus is not None:
            return self._corpus
        from collections import defaultdict
        from django.db import models as djm
        from cms.models import ArticlePage, ContentPage

        parts = defaultdict(list)
        for page_model in (ArticlePage, ContentPage):
            for page in page_model.objects.only('section_slug', 'body').iterator():
                parts[page.section_slug].append(str(page.body.raw_data))
        try:
            from content.models import Article as WpArticle
            from content.models import Page as WpPage
            for legacy_model in (WpArticle, WpPage):
                tfields = [f.name for f in legacy_model._meta.fields
                           if isinstance(f, djm.TextField)]
                for obj in legacy_model.objects.select_related('site').iterator():
                    site = getattr(obj, 'site', None)
                    if site is None:
                        continue
                    parts[site.legacy_site_slug or site.slug].append(
                        ' '.join(str(getattr(obj, n) or '') for n in tfields))
        except Exception:
            pass
        self._corpus = {slug: ' '.join(chunks) for slug, chunks in parts.items()}
        return self._corpus

    def _slugs_from_urls(self, obj):
        """Syndicats dont les contenus citent le fichier par son nom (URL brute)."""
        import os
        name = os.path.basename(obj.file.name or '')
        if not name:
            return set()
        return {slug for slug, text in self._url_corpus().items() if name in text}

    def _assign(self, model, label, root, commun):
        from django.contrib.contenttypes.models import ContentType
        from wagtail.models import ReferenceIndex

        ct = ContentType.objects.get_for_model(model)
        slugs_by_target = {}
        for ref in ReferenceIndex.objects.filter(
                to_content_type=ct).select_related('content_type'):
            source = self._source_of(ref)
            if source is None:
                continue
            slugs_by_target.setdefault(
                str(ref.to_object_id), set()).add(self._slug_of(source))

        moved = {}
        left_in_root = 0
        for obj in model.objects.filter(collection=root).order_by('pk'):
            slugs = {s for s in slugs_by_target.get(str(obj.pk), set()) if s}
            if not slugs:
                slugs = self._slugs_from_urls(obj)
            if len(slugs) == 1:
                target = self._collection_for_slug(next(iter(slugs)))
            elif slugs:
                target = commun
            else:
                target = None
            if target is None:
                left_in_root += 1
                continue
            moved[target.name] = moved.get(target.name, 0) + 1
            if not self.dry:
                obj.collection = target
                obj.save(update_fields=['collection'])

        self.stdout.write(f'{label} :')
        for name in sorted(moved):
            self.stdout.write(f'  → « {name} » : {moved[name]}')
        self.stdout.write(f'  restent dans Root (non utilisés ou hors syndicat) : {left_in_root}')
