"""
Décode les entités HTML restées visibles dans les titres et les extraits.

Constaté le 06/09/2026 : 54 articles s'affichaient « Contre l&rsquo;austérité
et la militarisation » — l'entité en toutes lettres, à la place de l'apostrophe.

La cause était dans `import_from_wp_api._clean_html`, qui retirait les balises
sans décoder les entités. Le champ `title` est du texte : Django échappe
l'esperluette au rendu, si bien que `&rsquo;` stocké devient `&amp;rsquo;` dans
la page, et que le lecteur voit le code. La fonction est corrigée, mais les
articles déjà importés gardent leurs titres abîmés : d'où cette réparation.

Portée volontairement étroite : **uniquement des champs de texte brut**
(titre, extrait, titre et description SEO). Le corps de l'article n'est pas
touché — il contient du HTML, où les entités sont à leur place et où les
décoder produirait des balises parasites, voire une injection.

Usage :
    python manage.py repare_entites_html --dry-run
    python manage.py repare_entites_html
"""

import re
from html import unescape

from django.core.management.base import BaseCommand

# Une entité nommée (&rsquo;) ou numérique (&#8217;), sans plus.
ENTITE = re.compile(r'&(?:[a-zA-Z][a-zA-Z0-9]{1,8}|#[0-9]{2,6}|#x[0-9a-fA-F]{2,6});')

CHAMPS = ('title', 'draft_title', 'excerpt', 'seo_title', 'search_description')


class Command(BaseCommand):
    help = "Décode les entités HTML visibles dans les titres et extraits des pages"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Montre ce qui serait corrigé, sans rien enregistrer")

    def handle(self, *args, **options):
        from cms.models import ArticlePage, ContentPage

        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode essai : rien ne sera enregistré.\n"))

        total_pages = 0
        total_champs = 0

        for modele in (ArticlePage, ContentPage):
            for page in modele.objects.all():
                modifies = []
                for champ in CHAMPS:
                    valeur = getattr(page, champ, None)
                    if not valeur or not ENTITE.search(valeur):
                        continue
                    propre = unescape(valeur)
                    if propre == valeur:
                        # Une esperluette suivie d'un mot qui n'est pas une
                        # entité connue : « AT&MP; » par exemple. On laisse.
                        continue
                    setattr(page, champ, propre)
                    modifies.append(champ)

                if not modifies:
                    continue

                total_pages += 1
                total_champs += len(modifies)

                if total_pages <= 10:
                    self.stdout.write(f"  {page.title[:66]}")
                    self.stdout.write(f"      champs : {', '.join(modifies)}")

                if not dry_run:
                    page.save(update_fields=modifies)
                    # Le titre affiché vient de la version publiée : sans
                    # nouvelle révision publiée, la correction resterait
                    # invisible sur le site.
                    if page.live:
                        page.save_revision(log_action=False).publish()

        self.stdout.write("")
        self.stdout.write(f"  pages corrigées : {total_pages}")
        self.stdout.write(f"  champs corrigés : {total_champs}")
        if not dry_run and total_pages:
            self.stdout.write(self.style.SUCCESS("  Terminé."))
