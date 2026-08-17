"""Convertit le bloc HTML de la page « Nos syndicats » en fiches éditables.

Les cartes de `/syndicats/` vivaient dans un unique bloc HTML de près de
10 000 caractères, feuille de style comprise. Cette commande les relit et crée
les `FicheSyndicat` correspondantes, en rattachant chaque carte à sa catégorie
ou à son syndicat par le slug de son ancien lien — plutôt qu'à un chemin écrit
en dur, que le réimport des catégories WordPress prévu au lancement casserait
en silence.

Elle est idempotente : relancée, elle met à jour les fiches existantes (elles
sont reconnues à leur titre) et n'en crée pas de doublon.

    python manage.py importe_fiches_syndicats --dry-run   # voir sans écrire
    python manage.py importe_fiches_syndicats
    python manage.py importe_fiches_syndicats --completer  # + secteurs et syndicats absents
    python manage.py importe_fiches_syndicats --vider-la-page  # ne garder que le chapô

Le parsing passe par BeautifulSoup et non par des expressions régulières :
deux cartes (Numérique, STAA) n'ont pas d'image mais un aplat de couleur, et
une regex qui attendait un `<img>` les sautait en silence.
"""

import unicodedata

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max

from cms.models import CmsCategory, ContentPage, SectionPage
from content.models import FicheSyndicat, MenuItem


class Command(BaseCommand):
    #: L'entrée racine du menu principal qui range les champs de
    #: syndicalisation. Les cartes de la page en sont le reflet.
    MENU_SECTEURS = 'Secteurs'

    help = ("Convertit les cartes HTML de la page « Nos syndicats » "
            "en fiches éditables dans /cms/.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Afficher ce qui serait fait, sans rien écrire.")
        parser.add_argument(
            '--completer', action='store_true',
            help="Ajouter une carte pour chaque syndicat publié et pour "
                 "chaque secteur du menu qui n'en a pas encore.",
        )
        parser.add_argument(
            '--vider-la-page', action='store_true',
            help="Après import, remplacer le corps de la page par le seul "
                 "chapô : la grille est désormais rendue par le gabarit.",
        )

    def handle(self, *args, **options):
        page = ContentPage.objects.filter(
            slug='syndicats', section_slug='principal').first()
        if page is None:
            self.stderr.write(self.style.ERROR(
                "Page « syndicats » introuvable sur le site principal."))
            return

        self.dry = options['dry_run']
        self.principal = SectionPage.objects.filter(slug='principal').first()
        #: Les syndicats et catégories déjà pointés par une carte lue. Tenus
        #: à jour pendant l'import pour que `--completer` dise vrai même à
        #: blanc, où rien n'est encore écrit en base.
        self.vus = set()
        self.vus_cat = set()
        html = ''.join(str(b.value) for b in page.body)
        soup = BeautifulSoup(html, 'html.parser')
        cartes = soup.select('a.syndicat-card')

        if not cartes:
            self.stdout.write("Aucune carte dans le corps de la page : "
                              "déjà converti ?")

        with transaction.atomic():
            for rang, carte in enumerate(cartes):
                self._importer(carte, rang)
            if options['completer']:
                self._completer(depart=len(cartes))
            if options['vider_la_page'] and not self.dry:
                self._ne_garder_que_le_chapo(page, soup, len(html))

        if self.dry:
            self.stdout.write(self.style.WARNING(
                f"{len(cartes)} cartes lues — rien écrit (--dry-run)."))
        else:
            total = FicheSyndicat.objects.filter(site=self.principal).count()
            self.stdout.write(self.style.SUCCESS(
                f"{total} fiches en base pour la confédération."))

    # ── Import d'une carte ────────────────────────────────────────────────

    def _importer(self, carte, rang):
        titre = self._texte(carte, '.syndicat-card-title')
        if not titre:
            self.stderr.write(self.style.WARNING(
                "  ? carte sans titre, ignorée"))
            return
        href = (carte.get('href') or '').strip()
        image = carte.find('img')
        cible = self._resoudre(href)
        if isinstance(cible, SectionPage):
            self.vus.add(cible.pk)
        elif isinstance(cible, CmsCategory):
            self.vus_cat.add(cible.pk)
        if cible is None and href:
            self.stderr.write(self.style.WARNING(
                f"  ? {titre} : lien « {href} » non résolu, conservé tel quel"))

        self.stdout.write(f"  · {titre:34} → {self._decrire(cible, href)}")
        if self.dry:
            return
        self._enregistrer(
            titre=titre,
            description=self._texte(carte, '.syndicat-card-desc'),
            image_url=(image.get('src') or '') if image else '',
            cible=cible,
            url='' if cible is not None else href,
            order=rang,
        )

    def _enregistrer(self, titre, description, image_url, cible, url, order):
        _, cree = FicheSyndicat.objects.update_or_create(
            site=self.principal, titre=titre,
            defaults={
                'description': description,
                'image_url': image_url,
                'categorie': cible if isinstance(cible, CmsCategory) else None,
                'site_cible': cible if isinstance(cible, SectionPage) else None,
                'url': url,
                'order': order,
            },
        )
        if not cree:
            self.stdout.write("    (fiche existante mise à jour)")

    # ── Les syndicats que la page oubliait ────────────────────────────────

    def _completer(self, depart):
        """Un syndicat publié ou un secteur du menu = une carte.

        La page et le menu « Secteurs » énumèrent la même chose et divergeaient
        pourtant : trois secteurs du menu (T.P.E., Animation & Éducation
        populaire, Intérim) n'avaient pas de carte. Non par choix, mais parce
        qu'ajouter une carte demandait de recopier des balises au milieu d'une
        feuille de style — ce que cette refonte corrige.

        La règle vaut désormais dans les deux sens : ce que le menu annonce,
        la page le montre.
        """
        # Les cartes ajoutées se rangent APRÈS celles déjà en base, et pas
        # après le nombre de cartes lues dans la page : une fois la page vidée
        # de son HTML, ce nombre est zéro et les nouvelles venaient s'entrelacer
        # en tête de grille (constaté en production, 17/08/2026).
        depart = max(depart, self._rang_libre())
        depart = self._completer_les_secteurs(depart)
        self._completer_les_syndicats(depart)

    def _rang_libre(self):
        """Le premier numéro d'ordre qui ne bouscule aucune carte existante."""
        maxi = (FicheSyndicat.objects.filter(site=self.principal)
                .aggregate(Max('order'))['order__max'])
        return 0 if maxi is None else maxi + 1

    def _completer_les_secteurs(self, depart):
        """Une carte pour chaque rubrique rangée sous « Secteurs » dans le menu.

        Sous « Secteurs » et non dans tout le menu principal : « Solidarités »
        ou « International » y sont des rubriques racine, pas des champs de
        syndicalisation, et leur fabriquer une carte n'aurait aucun sens.
        """
        secteurs = (
            MenuItem.objects
            .filter(site=self.principal, menu='main', parent__isnull=True,
                    title__iexact=self.MENU_SECTEURS)
            .first()
        )
        if secteurs is None:
            self.stderr.write(self.style.WARNING(
                f"  ? pas d'entrée de menu « {self.MENU_SECTEURS} » : "
                f"aucun secteur à compléter"))
            return depart

        deja = self.vus_cat | set(
            FicheSyndicat.objects.filter(site=self.principal)
            .exclude(categorie=None).values_list('categorie_id', flat=True)
        )
        # Le même champ de syndicalisation existe parfois en deux catégories,
        # héritage de l'import WordPress : « Activités postales et
        # Télécommunications » est en base deux fois, la fiche pointant sur
        # l'une et le menu sur l'autre. Deux cartes pour la même chose, le
        # lecteur ne verrait qu'un doublon.
        deja_noms = {
            self._normaliser(nom) for nom in
            CmsCategory.objects.filter(pk__in=deja).values_list('name', flat=True)
        }

        rang = depart
        for lien in (secteurs.children.filter(link_type='category', is_active=True)
                     .exclude(category=None).select_related('category')
                     .order_by('order')):
            categorie = lien.category
            nom = self._normaliser(categorie.name)
            if categorie.pk in deja:
                continue
            if nom in deja_noms:
                self.stdout.write(self.style.WARNING(
                    f"  = {lien.title:34} → déjà une carte sous une catégorie "
                    f"homonyme, ignoré"))
                continue
            deja.add(categorie.pk)
            deja_noms.add(nom)
            self.stdout.write(self.style.SUCCESS(
                f"  + {lien.title:34} → secteur du menu sans carte, ajouté"))
            if not self.dry:
                self._enregistrer(
                    titre=lien.title, description='', image_url='',
                    cible=categorie, url='', order=rang)
            rang += 1
        return rang

    @staticmethod
    def _normaliser(nom):
        """Un nom de catégorie comparable : sans casse, accents ni ponctuation."""
        nom = unicodedata.normalize('NFD', nom.lower())
        return ''.join(c for c in nom
                       if unicodedata.category(c) != 'Mn' and c.isalnum())

    def _completer_les_syndicats(self, depart):
        """Une carte pour chaque syndicat publié qui n'en avait pas."""
        deja = self.vus | set(
            FicheSyndicat.objects.filter(site=self.principal)
            .exclude(site_cible=None).values_list('site_cible_id', flat=True)
        )
        manquants = (
            SectionPage.objects.filter(live=True, section_type='sectoral')
            .exclude(slug='principal').exclude(pk__in=deja).order_by('title')
        )
        for i, section in enumerate(manquants):
            self.stdout.write(self.style.SUCCESS(
                f"  + {section.title:34} → syndicat absent de la page, ajouté"))
            if self.dry:
                continue
            self._enregistrer(
                titre=section.title,
                description=section.description or '',
                image_url='',
                cible=section,
                url='',
                order=depart + i,
            )

    # ── Utilitaires ───────────────────────────────────────────────────────

    def _texte(self, carte, selecteur):
        noeud = carte.select_one(selecteur)
        return noeud.get_text(strip=True) if noeud else ''

    def _resoudre(self, href):
        """La catégorie ou le syndicat visé par un ancien lien, ou None."""
        if not href:
            return None
        nu = href.strip('/').split('/')
        if len(nu) == 2 and nu[0] == 'categorie':
            return CmsCategory.objects.filter(slug=nu[1]).first()
        if len(nu) == 1 and not href.startswith('http'):
            return SectionPage.objects.filter(slug=nu[0]).first()
        # Lien absolu : c'est peut-être un syndicat hébergé sur son propre
        # site (le STAA, le TAS), auquel cas la fiche doit pointer sur la
        # section — elle suivra si le syndicat déménage.
        return SectionPage.objects.filter(external_url=href).first()

    def _decrire(self, cible, href):
        if isinstance(cible, CmsCategory):
            return f"catégorie « {cible.name} »"
        if isinstance(cible, SectionPage):
            return f"syndicat « {cible.title} »"
        return f"adresse libre {href or '(aucune)'}"

    def _ne_garder_que_le_chapo(self, page, soup, taille_avant):
        """Retire la grille du corps de la page ; le gabarit la rend désormais.

        Le chapô, lui, reste éditable dans /cms/ : c'est du texte, il a sa
        place dans la page. Seuls la grille et sa feuille de style s'en vont.
        """
        for grille in soup.select('.syndicats-grid'):
            grille.decompose()
        for style in soup.find_all('style'):
            style.decompose()
        chapo = str(soup).strip()
        page.body = [('html', chapo)]
        page.save_revision().publish()
        self.stdout.write(self.style.SUCCESS(
            f"Corps de la page réduit au chapô ({len(chapo)} caractères, "
            f"contre {taille_avant} avant)."))
