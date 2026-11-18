"""Fusionne les variantes d'un même tag (« grève », « grêve », « #grève »).

    python manage.py fusionne_tags --dry-run
    python manage.py fusionne_tags --garde "éducation" --garde "Extrême droite"

Deux tags sont des variantes quand ils ont la même `cms.tags.cle_tag` (casse,
accents, `#`, espaces et ponctuation ignorés). Dans chaque famille on garde
le plus employé, sauf si `--garde` nomme une autre variante, ou une
orthographe nouvelle qui renommera le tag gardé. Un tag gardé qui commence
par `#` perd son `#`.

Pour chaque variante retirée :
- ses articles, images, documents et médias passent sur le tag gardé ;
- les révisions d'articles qui la citaient sont réécrites — l'éditeur ouvre la
  révision, et un brouillon pointant un tag supprimé ne s'enregistrerait plus ;
- elle est supprimée.

Les tags sont communs à tous les syndicats : la fusion vaut pour tous.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from cms.tags import cle_tag, nom_propre, tags_par_cle


class Command(BaseCommand):
    help = "Fusionne les variantes d'un même tag."

    def add_arguments(self, parser):
        parser.add_argument('--garde', action='append', default=[],
                            help="Orthographe à garder pour sa famille. Répétable.")
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']
        choix = {cle_tag(nom): nom_propre(nom) for nom in options['garde']}
        if sec:
            self.stdout.write(self.style.WARNING('MODE SIMULATION — aucune écriture\n'))

        familles = retires = renommes = 0
        for cle, tags in sorted(tags_par_cle().items()):
            nom_voulu = choix.pop(cle, None)
            tags = sorted(tags, key=lambda t: (-t.n, t.name.startswith('#'), t.name))
            garde = next((t for t in tags if t.name == nom_voulu), tags[0])
            nouveau_nom = nom_voulu or nom_propre(garde.name)
            variantes = [t for t in tags if t is not garde]
            if not variantes and nouveau_nom == garde.name:
                continue

            familles += 1
            fleche = f' → « {nouveau_nom} »' if nouveau_nom != garde.name else ''
            self.stdout.write(f'  « {garde.name} » ({garde.n}){fleche}')
            for v in variantes:
                self.stdout.write(f'      ← « {v.name} » ({v.n})')
            retires += len(variantes)
            renommes += nouveau_nom != garde.name
            if sec:
                continue
            with transaction.atomic():
                for v in variantes:
                    self._reporte(v, garde)
                    v.delete()
                if nouveau_nom != garde.name:
                    garde.name = nouveau_nom
                    garde.save(update_fields=['name'])  # le slug ne bouge pas

        for nom in choix.values():
            self.stdout.write(self.style.WARNING(f'  ? --garde « {nom} » : aucun tag de ce nom'))
        self.stdout.write(self.style.SUCCESS(
            f'\n{familles} famille(s), {retires} variante(s) '
            f'{"à retirer" if sec else "retirée(s)"}, {renommes} renommage(s).'))

    def _reporte(self, variante, garde):
        from taggit.models import TaggedItem
        from wagtail.models import Revision
        from cms.models import ArticlePage, CmsArticleTag

        deja = set(CmsArticleTag.objects.filter(tag=garde)
                   .values_list('content_object_id', flat=True))
        CmsArticleTag.objects.filter(tag=variante, content_object_id__in=deja).delete()
        CmsArticleTag.objects.filter(tag=variante).update(tag=garde)

        deja = set(TaggedItem.objects.filter(tag=garde)
                   .values_list('content_type_id', 'object_id'))
        for lien in TaggedItem.objects.filter(tag=variante):
            if (lien.content_type_id, lien.object_id) in deja:
                lien.delete()
            else:
                lien.tag = garde
                lien.save(update_fields=['tag'])

        type_article = ContentType.objects.get_for_model(ArticlePage)
        for revision in Revision.objects.filter(content_type=type_article).iterator():
            liens = (revision.content or {}).get('tagged_items') or []
            if not any(l.get('tag') == variante.pk for l in liens):
                continue
            vus, gardes = set(), []
            for lien in liens:
                if lien.get('tag') == variante.pk:
                    lien['tag'] = garde.pk
                if lien.get('tag') in vus:
                    continue
                vus.add(lien.get('tag'))
                gardes.append(lien)
            revision.content['tagged_items'] = gardes
            revision.save(update_fields=['content'])
