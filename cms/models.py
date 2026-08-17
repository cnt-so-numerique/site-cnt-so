from django import forms
from django.db import models
from cms.widgets import OVHMailingListWidget
from django.utils.text import slugify

from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from taggit.models import TaggedItemBase

from wagtail import blocks
from wagtail.admin.panels import (
    FieldPanel, FieldRowPanel, InlinePanel, MultiFieldPanel, ObjectList,
    PageChooserPanel, TabbedInterface,
)
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Orderable, Page
from wagtail.search import index
from wagtail.snippets.models import register_snippet
from wagtailseo.models import SeoMixin


def url_site_principal(url):
    """Rend absolue une URL du site confédéral.

    Une URL relative n'est juste que si elle est rendue sur le site principal.
    Or son contenu s'affiche aussi sur les domaines de fédération : un article
    confédéral mis au carrousel de STUCS, ou l'étiquette d'une catégorie
    confédérale portée par un article de sous-site (31 articles en production).
    Le navigateur résolvait alors `/article/x/` contre `stucs.cnt-so.org` — un
    404. Sept liens morts relevés au crawl du 05/08/2026.

    Les sections à domaine émettent déjà des URLs absolues (`section_base_url`) :
    on applique au principal la règle qui vaut pour toutes les autres — l'adresse
    d'un contenu porte l'hôte de sa section, quel que soit l'endroit du rendu.
    """
    from django.conf import settings
    base = getattr(settings, 'MAIN_SITE_BASE_URL', '')
    return f'{base}{url}' if base and url.startswith('/') else url


def section_base_url(section_slug):
    """Préfixe absolu (https://domaine) de la section si elle a un domaine
    autonome, '' sinon (les URLs restent relatives). Mis en cache 60 s —
    appelé pour chaque lien d'article dans les listes."""
    if not section_slug or section_slug == 'principal':
        return ''
    from django.core.cache import cache
    key = f'section-base-url:{section_slug}'
    val = cache.get(key)
    if val is None:
        section = SectionPage.objects.filter(
            models.Q(legacy_site_slug=section_slug) | models.Q(slug=section_slug)
        ).only('custom_domain').first()
        val = f'https://{section.custom_domain}' if section and section.custom_domain else ''
        cache.set(key, val, 60)
    return val


# ── Taxonomie ─────────────────────────────────────────────────────────────────

class CmsCategory(models.Model):
    """Catégorie d'article — snippet Wagtail, pas une Page."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    section_slug = models.SlugField(
        max_length=100, blank=True, default='principal',
        help_text="Slug de la SectionPage à laquelle cette catégorie appartient"
    )
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='children'
    )
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True,
                                    help_text="ID content.Category d'origine")

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('section_slug'),
        FieldPanel('description'),
        FieldPanel('parent'),
    ]

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        unique_together = [['section_slug', 'slug']]
        ordering = ['name']

    def __str__(self):
        """Nom précédé de son parent quand il y en a un.

        L'import WordPress a conservé la hiérarchie dans `parent`, mais pas
        dans le nom : le 13 a sept catégories « Revendiquons ! », six « Vos
        droits » et cinq « Actualités - luttes », chacune sous un secteur
        différent et portant ses propres articles. La liste à cocher du
        formulaire d'article n'affichait que le nom — vingt lignes
        indiscernables pour quatre libellés, où un rédacteur ne pouvait que
        se tromper de rubrique (signalé par Arnaud le 05/08/2026).

        Les gabarits publics utilisent `.name`, jamais `str()` : le préfixe
        reste confiné au back-office.
        """
        if self.parent_id and self.parent.name != self.name:
            return f'{self.parent.name} › {self.name}'
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        try:
            if self.section_slug and self.section_slug != 'principal':
                base = section_base_url(self.section_slug)
                if base:
                    return f'{base}/categorie/{self.slug}/'
                return reverse('content:site_category_detail',
                               kwargs={'site_slug': self.section_slug, 'slug': self.slug})
            return url_site_principal(
                reverse('content:category_detail', kwargs={'slug': self.slug}))
        except NoReverseMatch:
            return '/'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CmsArticleTag(TaggedItemBase):
    """Table de liaison taggit pour ArticlePage."""
    content_object = ParentalKey(
        'cms.ArticlePage',
        related_name='tagged_items',
        on_delete=models.CASCADE,
    )


# ── Blocs StreamField ─────────────────────────────────────────────────────────

RICHTEXT_FEATURES = [
    # 'underline' retiré le 15/08/2026 : Draftail ne connaît pas cette
    # fonctionnalité sous ce nom, le bouton n'existait donc pas dans la barre
    # d'outils et chaque rendu du formulaire émettait un RuntimeWarning. Le
    # souligné se confond de toute façon avec un lien à l'écran.
    'bold', 'italic', 'strikethrough',
    'h2', 'h3', 'h4', 'h5',
    'ol', 'ul',
    'link',
    'blockquote',
    'hr',
]


COULEUR_CHARTE = '#E81C24'

# Largeurs proposées, en pourcentage de la colonne de texte. Des paliers
# plutôt qu'un curseur libre : une image à 37 % ne veut rien dire de plus
# qu'une image à 33 %, et les paliers restent alignés d'un article à l'autre.
CHOIX_LARGEUR = [
    ('25', 'Un quart'),
    ('33', 'Un tiers'),
    ('50', 'Une moitié'),
    ('66', 'Deux tiers'),
    ('75', 'Trois quarts'),
    ('100', 'Toute la largeur'),
]


def extrait_depuis_corps(body, longueur=220):
    """Premier texte lisible d'un corps StreamField, coupé au mot.

    1677 articles sur 1785 n'avaient pas d'extrait (audit du 15/08/2026). Il
    sert les cartes des listes, les métadonnées de référencement et le corps
    des newsletters : sans lui, une carte s'affiche sans un mot de
    présentation.

    On lit aussi les blocs `html` : 1060 articles sur 1709 n'ont que ça, hérité
    de l'import WordPress. Ne regarder que le texte riche laisserait sans
    extrait la majorité de ceux qui en ont besoin.
    """
    from django.utils.html import strip_tags
    import html as _html
    import re

    for bloc in body or []:
        if bloc.block_type not in ('rich_text', 'html'):
            continue
        texte = _html.unescape(strip_tags(str(bloc.value))).strip()
        texte = re.sub(r'\s+', ' ', texte)
        if len(texte) < 20:
            continue          # titre isolé, légende, ligne vide : on continue
        if len(texte) <= longueur:
            return texte
        coupe = texte[:longueur].rsplit(' ', 1)[0]
        return f'{coupe}…'
    return ''


def _luminance(couleur):
    """Luminance relative WCAG d'un « #RRGGBB », entre 0 et 1."""
    couleur = (couleur or COULEUR_CHARTE).lstrip('#')
    if len(couleur) != 6:
        return 0.0
    try:
        canaux = [int(couleur[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return 0.0
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in canaux]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def texte_lisible_sur(couleur):
    """« #ffffff » ou « #000000 », celui qui se lit sur `couleur`.

    Les rédacteurs choisissent librement leurs couleurs (décision d'Arnaud du
    15/08/2026, contre mon avis de les verrouiller). Laisser aussi le choix de
    la couleur du texte produirait tôt ou tard du blanc sur jaune. On la déduit
    donc du contraste réel — aucun choix n'est retiré au rédacteur.

    **Blanc dès qu'il atteint le seuil AA (4,5), noir sinon.** La règle du
    contraste maximal — celle qu'on trouve partout — donnerait du NOIR sur le
    rouge de la charte : `#E81C24` est à 4,62 en noir contre 4,54 en blanc.
    Les deux passent AA, l'écart est de 1,8 %, mais tous les boutons du site
    sont blancs sur rouge depuis toujours. Entre deux valeurs conformes, on
    suit l'identité du site.

    La règle tient sur les cas qui piègent : gris moyen `#7F7F7F` → noir (le
    blanc n'y est qu'à 3,95), jaune `#FFD400` → noir, marine `#1A2E5A` → blanc.
    """
    return '#ffffff' if (1.05 / (_luminance(couleur) + 0.05)) >= 4.5 else '#000000'


class CouleurBlock(blocks.FieldBlock):
    """Sélecteur de couleur natif du navigateur."""

    def __init__(self, default=COULEUR_CHARTE, required=True, help_text=None, **kwargs):
        from django.core.validators import RegexValidator
        self.field = forms.CharField(
            required=required,
            help_text=help_text,
            max_length=7,
            validators=[RegexValidator(
                r'^#[0-9A-Fa-f]{6}$',
                "Indiquez une couleur au format #RRGGBB.")],
            widget=forms.TextInput(attrs={'type': 'color'}),
        )
        super().__init__(default=default, **kwargs)


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock(label="Image")
    caption = blocks.CharBlock(required=False, label="Légende")
    alignment = blocks.ChoiceBlock(
        choices=[
            ('left', 'Gauche'),
            ('center', 'Centre'),
            ('right', 'Droite'),
            ('full', 'Pleine largeur'),
        ],
        default='center',
        label="Alignement",
    )
    # Ajouté le 15/08/2026 : l'alignement gauche/droite ne servait à rien sans
    # pouvoir régler la taille — une photo de 2000 px poussée à droite occupait
    # la moitié de l'écran quoi qu'il arrive. Les articles déjà écrits n'ont
    # pas la clé : StructBlock retombe alors sur ce défaut.
    largeur = blocks.ChoiceBlock(
        choices=CHOIX_LARGEUR,
        default='50',
        label="Largeur",
        help_text="Sans effet en pleine largeur.",
    )

    class Meta:
        icon = 'image'
        label = "Image"
        template = 'cms/blocks/image_block.html'


class DuoBlock(blocks.StructBlock):
    """Média et texte côte à côte, solidaires.

    Différent de l'image flottante, qu'on garde : ici les deux colonnes
    restent alignées en haut et le texte ne repasse jamais sous le média.
    """

    media_position = blocks.ChoiceBlock(
        choices=[('left', 'À gauche'), ('right', 'À droite')],
        default='right',
        label="Média",
    )
    repartition = blocks.ChoiceBlock(
        choices=[
            ('50', 'Moitié / moitié'),
            ('33', 'Média étroit (un tiers)'),
            ('66', 'Média large (deux tiers)'),
        ],
        default='50',
        label="Répartition",
    )
    image = ImageChooserBlock(required=False, label="Image")
    video = EmbedBlock(required=False, label="Vidéo (à la place de l'image)")
    caption = blocks.CharBlock(required=False, label="Légende du média")
    texte = blocks.RichTextBlock(features=RICHTEXT_FEATURES, label="Texte")

    def clean(self, value):
        from django.core.exceptions import ValidationError
        from wagtail.blocks.struct_block import StructBlockValidationError
        value = super().clean(value)
        if not value.get('image') and not value.get('video'):
            raise StructBlockValidationError(block_errors={
                'image': ValidationError(
                    "Choisissez une image, ou collez l'adresse d'une vidéo.")})
        return value

    class Meta:
        icon = 'form'
        label = "Texte et média côte à côte"
        template = 'cms/blocks/duo_block.html'


class EncadreBlock(blocks.StructBlock):
    """Sortir une information du fil du texte : appel, date, consigne."""

    titre = blocks.CharBlock(required=False, label="Titre")
    texte = blocks.RichTextBlock(features=RICHTEXT_FEATURES, label="Texte")
    couleur = CouleurBlock(
        label="Couleur du filet",
        help_text="Le rouge de la confédération est proposé par défaut.")
    fond = blocks.ChoiceBlock(
        choices=[
            ('gris', 'Fond gris'),
            ('teinte', 'Fond teinté dans la couleur'),
            ('aucun', 'Sans fond'),
        ],
        default='gris',
        label="Fond",
    )

    class Meta:
        icon = 'warning'
        label = "Encadré"
        template = 'cms/blocks/encadre_block.html'


class BoutonItem(blocks.StructBlock):
    libelle = blocks.CharBlock(label="Libellé", max_length=60)
    url = blocks.URLBlock(label="Adresse")
    style = blocks.ChoiceBlock(
        choices=[('plein', 'Plein'), ('contour', 'Contour')],
        default='plein', label="Style")
    couleur = CouleurBlock(label="Couleur")
    nouvel_onglet = blocks.BooleanBlock(
        required=False, default=False, label="Ouvrir dans un nouvel onglet")

    class Meta:
        icon = 'link'
        label = "Bouton"


class BoutonsBlock(blocks.StructBlock):
    """Un appel à agir qui se voit, et se clique au pouce sur un téléphone."""

    boutons = blocks.ListBlock(BoutonItem(), label="Boutons", min_num=1, max_num=4)

    class Meta:
        icon = 'link'
        label = "Boutons"
        template = 'cms/blocks/boutons_block.html'


class ChiffreItem(blocks.StructBlock):
    nombre = blocks.CharBlock(
        label="Nombre", max_length=12,
        help_text="Le symbole est libre : 92 %, 4 218 €, 17…")
    legende = blocks.CharBlock(label="Légende", max_length=60)

    class Meta:
        icon = 'form'
        label = "Chiffre"


class ChiffresBlock(blocks.StructBlock):
    """Bilan de mobilisation, résultat d'élections, caisse de grève."""

    chiffres = blocks.ListBlock(ChiffreItem(), label="Chiffres",
                                min_num=2, max_num=4)
    couleur = CouleurBlock(label="Couleur des nombres")

    class Meta:
        icon = 'table'
        label = "Chiffres clés"
        template = 'cms/blocks/chiffres_block.html'


class SeparateurBlock(blocks.StructBlock):
    """Marquer une rupture sans avoir à inventer un sous-titre."""

    type = blocks.ChoiceBlock(
        choices=[
            ('filet', 'Filet'),
            ('points', 'Points'),
            ('blanc', 'Blanc'),
        ],
        default='filet',
        label="Type",
    )
    couleur = CouleurBlock(label="Couleur", required=False)

    class Meta:
        icon = 'horizontalrule'
        label = "Séparateur"
        template = 'cms/blocks/separateur_block.html'


class GalleryImageItem(blocks.StructBlock):
    image = ImageChooserBlock(label="Image")
    caption = blocks.CharBlock(required=False, label="Légende")

    class Meta:
        icon = 'image'


class GalleryBlock(blocks.StructBlock):
    images = blocks.ListBlock(GalleryImageItem(), label="Images")
    columns = blocks.IntegerBlock(default=3, min_value=1, max_value=6, label="Colonnes")

    class Meta:
        icon = 'image'
        label = "Galerie"
        template = 'cms/blocks/gallery_block.html'


class FileBlock(blocks.StructBlock):
    document = DocumentChooserBlock(label="Document", required=False)
    title = blocks.CharBlock(required=False, label="Titre affiché")

    class Meta:
        icon = 'doc-full'
        label = "Fichier à télécharger"
        template = 'cms/blocks/file_block.html'


class QuoteBlock(blocks.StructBlock):
    text = blocks.RichTextBlock(
        features=['bold', 'italic'],
        label="Citation",
    )
    citation = blocks.CharBlock(required=False, label="Source / Auteur")

    class Meta:
        icon = 'openquote'
        label = "Citation"
        template = 'cms/blocks/quote_block.html'


class CorpsBlock(blocks.StreamBlock):
    """Corps d'article : masque du menu d'insertion les blocs réservés à l'import.

    `RawHTMLBlock` laisse écrire du HTML — donc du JavaScript — sur une page
    publique, depuis n'importe quel compte de syndicat. Son propre libellé dit
    « import legacy » : ce n'est pas un outil de rédaction (audit du
    15/08/2026).

    Il est **impossible de le retirer du modèle** : 1060 articles sur 1709 et
    49 pages sur 73 en contiennent, hérités de WordPress, et leur rendu s'en
    sert. On agit donc sur `grouped_child_blocks()`, qui construit le seul menu
    « + » de l'éditeur, et non sur `child_blocks`, qui sert au rendu et à la
    validation. Les blocs existants restent lisibles et modifiables ; on ne
    peut simplement plus en ajouter.

    Le jour où ces 1060 articles auront été convertis en texte riche, le bloc
    pourra sortir du modèle et cette classe disparaître.
    """

    BLOCS_MASQUES = {'html'}

    def grouped_child_blocks(self):
        return [
            (groupe, [b for b in blocs if b.name not in self.BLOCS_MASQUES])
            for groupe, blocs in super().grouped_child_blocks()
        ]


ARTICLE_BODY_BLOCKS = [
    ('rich_text', blocks.RichTextBlock(
        features=RICHTEXT_FEATURES,
        label="Texte",
        template='cms/blocks/rich_text_block.html',
    )),
    ('image', ImageBlock()),
    ('duo', DuoBlock()),
    ('encadre', EncadreBlock()),
    ('boutons', BoutonsBlock()),
    ('chiffres', ChiffresBlock()),
    ('separateur', SeparateurBlock()),
    ('gallery', GalleryBlock()),
    ('file', FileBlock()),
    ('quote', QuoteBlock()),
    ('embed', EmbedBlock(label="Vidéo / iFrame")),
    ('html', blocks.RawHTMLBlock(
        label="HTML brut (import legacy)",
        help_text="Utilisé pour le contenu importé qui ne peut pas être converti."
    )),
]


# ── Types de pages ────────────────────────────────────────────────────────────

class ContenuDeSyndicatMixin:
    """Referme un contenu quand le syndicat qui le porte est dépublié.

    Wagtail sert une page publiée sans regarder si son parent l'est : dépublier
    un syndicat laissait donc ses articles et ses pages accessibles à qui avait
    l'adresse, alors que sa page d'accueil, elle, renvoyait un 404 (constaté sur
    Rhône-Alpes le 16/08/2026). Le site paraissait fermé et ne l'était pas.

    Le rattachement se fait par `section_slug`, qui peut porter le slug Wagtail
    ou le slug WordPress hérité — les deux sont acceptés, comme partout ailleurs.
    """

    def _syndicat_est_publie(self):
        slug = getattr(self, 'section_slug', '')
        # Le site confédéral n'est pas un sous-site : rien à refermer.
        if not slug or slug == 'principal':
            return True
        return SectionPage.objects.filter(
            models.Q(slug=slug) | models.Q(legacy_site_slug=slug), live=True
        ).exists()

    def serve(self, request, *args, **kwargs):
        if not self._syndicat_est_publie():
            from django.http import Http404
            raise Http404(
                f"Contenu rattaché à un syndicat dépublié : {self.section_slug}"
            )
        return super().serve(request, *args, **kwargs)


class HomePage(Page):
    """Page racine du site CNT-SO. Une seule instance."""

    intro_text = models.TextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro_text'),
    ]

    subpage_types = [
        'cms.SectionPage',
        'cms.RegionalSectionPage',
        'cms.SectoralSectionPage',
        'cms.ArticlePage',
        'cms.ContentPage',
    ]

    class Meta:
        verbose_name = "Page d'accueil"

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        base_qs = (
            ArticlePage.objects
            .live()
            .filter(section_slug='principal')
            .order_by('-publication_date', '-first_published_at')
            .select_related('featured_image')
            .prefetch_related('cms_categories')
        )
        # Articles vedettes : conf sticky OU promus depuis n'importe quel syndicat
        sticky = list(
            ArticlePage.objects.live()
            .filter(
                models.Q(section_slug='principal', is_featured=True)
                | models.Q(featured_on_conf=True)
            )
            .order_by('-publication_date', '-first_published_at')
            .select_related('featured_image')
            .prefetch_related('cms_categories')
            [:4]
        )
        featured = sticky[0] if sticky else base_qs.first()
        context['featured_article'] = featured

        excl = [featured.pk] if featured else []
        mini = sticky[1:4]
        if len(mini) < 3:
            mini += list(base_qs.exclude(pk__in=excl + [a.pk for a in mini])[:3 - len(mini)])
        context['hero_mini_cards'] = mini
        excl += [a.pk for a in mini]

        context['sidebar_article'] = base_qs.exclude(pk__in=excl).first()
        flux = list(base_qs.exclude(pk__in=excl)[:3])
        context['flux_grid'] = flux
        excl += [a.pk for a in flux]

        context['luttes_articles'] = list(base_qs.filter(cms_categories__slug='actualites-luttes')[:4])
        context['droits_articles'] = list(base_qs.filter(cms_categories__slug='droit')[:5])
        context['sanspapiers_articles'] = list(
            base_qs.filter(cms_categories__slug='travailleurs-euses-sans-papiers')[:5]
        )
        context['campagnes_articles'] = list(
            base_qs.filter(
                cms_categories__slug__in=['international', 'solidarites', 'campagne']
            ).distinct()[:5]
        )
        context['manques_articles'] = list(base_qs.exclude(pk__in=excl)[6:11])
        return context

    def get_template(self, request, *args, **kwargs):
        return 'content/home.html'


class SectionPage(SeoMixin, Page):
    """Représente un syndicat régional ou sectoriel."""

    SECTION_TYPE_CHOICES = [
        ('main', 'Site principal'),
        ('regional', 'Union régionale'),
        ('sectoral', 'Syndicat sectoriel'),
    ]

    section_type = models.CharField(max_length=20, choices=SECTION_TYPE_CHOICES, default='regional')
    description = models.TextField(blank=True, verbose_name="Description / accroche",
        help_text="Texte court affiché sous le titre en page d'accueil du sous-site")
    external_url = models.URLField(blank=True)
    feed_url = models.URLField(
        blank=True, verbose_name="URL du flux RSS / Atom",
        help_text="Uniquement pour un syndicat hébergé ailleurs : ses articles "
                  "remontent alors dans « Les nouvelles du réseau » sur "
                  "l'accueil confédéral. Sur un WordPress, laissez vide — le "
                  "flux est déduit de l'adresse du site (…/feed/).",
    )
    # État de la synchronisation du flux. Hors panneaux : diagnostic, pas
    # édition. `feed_etag` évite de retélécharger un flux inchangé,
    # `feed_last_sync` répond à « pourquoi ce syndicat ne remonte plus ? ».
    feed_etag = models.CharField(max_length=255, blank=True)
    feed_last_sync = models.DateTimeField(null=True, blank=True)
    agenda_url = models.URLField(blank=True)
    linkstack_url = models.URLField(blank=True, verbose_name="URL Linkstack")
    framaform_url = models.URLField(blank=True, verbose_name="URL Framaform adhésion")
    banque_images_propre = models.BooleanField(
        default=False,
        verbose_name="Banque d'images propre à ce syndicat",
        help_text="Coché : le bloc « Notre banque d'images » de la barre "
                  "latérale mène à la banque de ce syndicat. Décoché : il "
                  "renvoie à celle de la confédération.",
    )
    intro_text = StreamField(
        [('contenu', blocks.RichTextBlock(features=RICHTEXT_FEATURES, label="Contenu")),
         ('liste', blocks.ListBlock(blocks.CharBlock(label="Item"), label="Liste à puces"))],
        blank=True, verbose_name="Présentation + revendications (page accueil)",
        help_text="Affiché sur la page d'accueil du sous-site après l'accroche",
        use_json_field=True,
    )
    rejoindre_text = StreamField(
        [('contenu', blocks.RichTextBlock(features=RICHTEXT_FEATURES, label="Contenu")),
         ('liste', blocks.ListBlock(blocks.CharBlock(label="Item"), label="Liste à puces"))],
        blank=True, verbose_name="Page Nous rejoindre",
        help_text="Texte de la page d'adhésion (pourquoi, comment ça marche…)",
        use_json_field=True,
    )
    agenda_text = StreamField(
        [('contenu', blocks.RichTextBlock(features=RICHTEXT_FEATURES, label="Contenu"))],
        blank=True, verbose_name="Agenda",
        help_text="Événements, dates, calendrier",
        use_json_field=True,
    )
    logo = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    contact_email = models.EmailField(
        blank=True,
        verbose_name="Email de contact",
        help_text="Adresse email qui reçoit les messages du formulaire de contact",
    )
    ovh_mailing_list = models.CharField(
        max_length=500, blank=True,
        verbose_name="Liste(s) mail OVH (newsletter)",
        help_text="Noms des listes sur cnt-so.info, séparés par des virgules",
    )
    custom_domain = models.CharField(
        max_length=253, blank=True, default='',
        verbose_name="Domaine autonome",
        help_text="Nom d'hôte nu, ex. stucs.cnt-so.org — vide = le sous-site "
                  "reste servi sous cnt-so.org/<slug>/ (comportement actuel)",
    )

    social_mastodon = models.URLField(blank=True, verbose_name="Mastodon")
    social_bluesky = models.URLField(blank=True, verbose_name="BlueSky")
    social_twitter = models.URLField(blank=True, verbose_name="Twitter / X")
    social_facebook = models.URLField(blank=True, verbose_name="Facebook")
    social_instagram = models.URLField(blank=True, verbose_name="Instagram")
    social_youtube = models.URLField(blank=True, verbose_name="YouTube")
    social_telegram = models.URLField(blank=True, verbose_name="Telegram")
    social_discord = models.URLField(blank=True, verbose_name="Discord")
    social_linkedin = models.URLField(blank=True, verbose_name="LinkedIn")

    legacy_site_slug = models.SlugField(max_length=100, blank=True, db_index=True)
    wp_blog_id = models.IntegerField(
        null=True, blank=True, unique=True,
        verbose_name="WP blog_id",
        help_text="Identifiant blog WordPress (import legacy)",
    )
    wp_path = models.CharField(
        max_length=100, blank=True,
        verbose_name="Path WordPress",
        help_text="Path WordPress legacy (ex: /normandie/)",
    )

    content_panels = Page.content_panels + [
        FieldPanel('section_type'),
        FieldPanel('description'),
        FieldPanel('contact_email'),
        FieldPanel('external_url'),
        FieldPanel('feed_url'),
        FieldPanel('agenda_url'),
        FieldPanel('linkstack_url'),
        FieldPanel('framaform_url'),
        FieldPanel('banque_images_propre'),
        FieldPanel('intro_text'),
        FieldPanel('rejoindre_text'),
        FieldPanel('agenda_text'),
        FieldPanel('logo'),
        MultiFieldPanel([
            FieldPanel('ovh_mailing_list', widget=OVHMailingListWidget),
        ], heading="Newsletter OVH"),
        MultiFieldPanel([
            FieldPanel('social_mastodon'),
            FieldPanel('social_bluesky'),
            FieldPanel('social_twitter'),
            FieldPanel('social_facebook'),
            FieldPanel('social_instagram'),
            FieldPanel('social_youtube'),
            FieldPanel('social_telegram'),
            FieldPanel('social_discord'),
            FieldPanel('social_linkedin'),
        ], heading="Réseaux sociaux"),
        MultiFieldPanel([
            FieldPanel('custom_domain', permission='superuser'),
        ], heading="Domaine autonome", permission='superuser'),
    ]
    promote_panels = Page.promote_panels + [
        FieldPanel('legacy_site_slug'),
        FieldPanel('wp_blog_id'),
        FieldPanel('wp_path'),
    ]

    parent_page_types = ['cms.HomePage']
    subpage_types = ['cms.ArticlePage', 'cms.ContentPage']

    class Meta:
        verbose_name = "Section (syndicat)"
        verbose_name_plural = "Sections (syndicats)"

    def get_feed_url(self):
        """URL du flux à moissonner, ou '' si ce syndicat n'en a pas.

        Un syndicat hébergé chez nous n'a pas de flux à moissonner : ses
        articles sont déjà en base. Seuls les syndicats à `external_url` en
        ont un — déduit de l'adresse du site, la quasi-totalité tournant sous
        WordPress, et surchargeable par `feed_url` pour les autres.
        """
        if self.feed_url:
            return self.feed_url
        if self.external_url:
            return self.external_url.rstrip('/') + '/feed/'
        return ''

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        if self.external_url:
            context['redirect_url'] = self.external_url
        context['articles'] = (
            ArticlePage.objects
            .live()
            .child_of(self)
            .order_by('-publication_date', '-first_published_at')
        )
        context['site'] = self
        return context

    def get_template(self, request, *args, **kwargs):
        return 'content/site_home.html'

    # ── Propriétés de compatibilité avec content.Site ────────────────────────

    @property
    def name(self):
        return self.title

    @property
    def is_active(self):
        return self.live

    @property
    def site_type(self):
        return self.section_type

    @property
    def base_url(self):
        """Préfixe absolu du sous-site : https://<domaine> si domaine autonome,
        chaîne vide sinon (les URLs restent relatives = comportement actuel)."""
        if self.custom_domain:
            return f'https://{self.custom_domain}'
        return ''

    def clean(self):
        super().clean()
        if self.custom_domain:
            domain = self.custom_domain.strip().lower()
            if '://' in domain or '/' in domain or ' ' in domain or '@' in domain:
                from django.core.exceptions import ValidationError
                raise ValidationError({'custom_domain':
                    "Nom d'hôte nu attendu (ex. stucs.cnt-so.org), sans https:// ni /"})
            clash = SectionPage.objects.filter(custom_domain=domain).exclude(pk=self.pk)
            if clash.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({'custom_domain':
                    f"Ce domaine est déjà utilisé par « {clash.first().title} »"})
            self.custom_domain = domain


    @property
    def slugs_contenu(self):
        """Les deux slugs sous lesquels un contenu peut être rattaché à ce
        syndicat.

        Les contenus portent le slug Wagtail, mais quelques syndicats ont un
        slug WordPress hérité différent (Numérique « stnum », Éducation
        « fter ») et leurs contenus anciens portent celui-là. Filtrer sur un
        seul des deux vide leur espace : c'est le bug qu'on a corrigé neuf fois
        depuis juillet, une fois par endroit où l'expression était recopiée.
        Tout filtre `section_slug` passe désormais par ici.
        """
        return {self.slug, self.legacy_site_slug or self.slug}  # source-unique

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        if self.external_url:
            return self.external_url
        if self.custom_domain:
            return f'{self.base_url}/'
        # Le slug Wagtail, et lui seul : `SectionSlugConverter` (content/urls.py)
        # ne reconnaît que `slug=`, jamais `legacy_site_slug`. Émettre le slug
        # hérité produisait une adresse en 404 — /fter/ pour Éducation, publiée
        # jusque dans le sitemap (constaté le 05/08/2026).
        try:
            if self.slug == 'principal':
                return reverse('content:home')
            return reverse('content:site_home', kwargs={'site_slug': self.slug})
        except NoReverseMatch:
            return self.url or '/'

    def get_rejoindre_url(self):
        from django.urls import reverse
        if self.custom_domain:
            return f'{self.base_url}/rejoindre/'
        # Slug Wagtail, comme get_absolute_url : cette route accepte les deux,
        # mais rien ne gagne à servir deux adresses pour la même page.
        slug = self.slug
        return reverse('content:site_rejoindre', kwargs={'site_slug': slug})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # S'assurer que legacy_site_slug est renseigné
        slug = self.legacy_site_slug or self.slug
        if slug and not self.legacy_site_slug:
            SectionPage.objects.filter(pk=self.pk).update(legacy_site_slug=slug)
        # Invalide les caches domaine (middleware + section_base_url + menus)
        from django.core.cache import cache
        cache.delete_many([
            f'section-base-url:{self.slug}',
            f'section-base-url:{self.legacy_site_slug or self.slug}',
            'section-domain-map',
            'menu-internal-hosts',
        ] + ([f'section-domain:{self.custom_domain}'] if self.custom_domain else []))


def panneaux_article():
    """Les onglets d'édition d'un article — **source unique**.

    `ArticlePage` est une Page Wagtail ET un snippet : deux écrans savent
    l'éditer, `/cms/snippets/cms/articlepage/edit/<pk>/` et
    `/cms/pages/<pk>/edit/`. Leurs panneaux avaient été écrits séparément et
    avaient divergé — l'éditeur de pages proposait les métadonnées d'abord,
    n'offrait ni `in_carousel` ni `featured_on_conf`, et imbriquait un onglet
    « Contenu » dans un onglet « Contenu » (audit du 15/08/2026).

    C'est le même remède que pour la famille `legacy_site_slug` en passe 7 :
    une définition unique plutôt qu'une recopie. Une **fonction** et non une
    constante, parce qu'un `ObjectList` se lie à un modèle et garde cet état :
    partager l'instance entre deux écrans les ferait interférer.

    ⚠️ L'ordre compte : le Contenu d'abord, c'est là qu'un rédacteur commence.
    """
    return TabbedInterface([
        ObjectList([
            FieldPanel('body'),
            # L'image et l'extrait sont des éléments de rédaction, pas des
            # réglages : l'image commande le rang de l'article dans les listes
            # du site, l'extrait est le texte qu'on lira sur les cartes.
            FieldPanel('featured_image'),
            FieldPanel('excerpt'),
        ], heading='Contenu'),
        ObjectList([
            # Réservés aux chefs : imposés par `form_valid` pour les autres,
            # et leur panneau disparaît au lieu de laisser une étiquette vide.
            PanneauChefSeulement('section_slug'),
            MultiFieldPanel([
                FieldPanel('publication_date'),
                PanneauSitePrincipal('is_featured'),
                FieldPanel('in_carousel'),
                PanneauChefSeulement('featured_on_conf'),
                FieldPanel('author_name'),
            ], heading="Publication"),
            FieldPanel('cms_categories', widget=forms.CheckboxSelectMultiple),
            FieldPanel('cms_tags'),
        ], heading='Métadonnées'),
    ])


class PanneauSitePrincipal(FieldPanel):
    """Champ visible uniquement sur un article du site confédéral.

    `is_featured` n'est lu qu'à un seul endroit — la vedette de l'accueil
    confédéral, et seulement pour `section_slug='principal'` (voir
    `HomePage.get_context`). Sur un article de syndicat, cocher la case ne
    produisait **rien, nulle part**, alors que son libellé annonçait « Mis en
    avant sur l'accueil du syndicat » (relevé par Arnaud, 15/08/2026).

    Le libellé est corrigé ; le panneau disparaît là où il ne peut rien faire,
    plutôt que de proposer un geste sans effet.
    """

    class BoundPanel(FieldPanel.BoundPanel):
        def is_shown(self):
            if not super().is_shown():
                return False
            instance = getattr(self, 'instance', None)
            # À la création, la section n'est pas encore fixée : on se rabat
            # sur le syndicat sélectionné dans le back-office.
            slug = getattr(instance, 'section_slug', '') or ''
            if not slug:
                from .site_context import get_current_site
                courant = get_current_site(self.request)
                slug = getattr(courant, 'slug', '') or ''
            return slug == 'principal'


class PanneauChefSeulement(FieldPanel):
    """Champ visible des seuls chefs — panneau compris.

    Masquer le widget en `HiddenInput` ne masquait que l'`<input>` : le
    rédacteur voyait rester le libellé « Mettre en avant sur la confédération »
    et son texte d'aide, sans rien dessous. Même chose pour « Section slug »,
    accompagné de « Slug dénormalisé de la SectionPage parente » — du jargon
    interne affiché à un syndicaliste (audit du 15/08/2026).

    `is_shown()` est le point d'accroche de Wagtail pour retirer un panneau de
    l'affichage. Le verrou de fond reste `form_valid`, côté serveur : ce panneau
    règle la lisibilité, pas la sécurité.
    """

    class BoundPanel(FieldPanel.BoundPanel):
        def is_shown(self):
            # Import différé : content.admin_utils remonte jusqu'à cms.models.
            from content.admin_utils import is_chef
            return super().is_shown() and is_chef(self.request.user)


class ArticlePage(ContenuDeSyndicatMixin, SeoMixin, Page):
    """Article de blog — remplace content.Article."""

    # Le cartouche « réseau » de l'accueil mélange nos articles et ceux
    # moissonnés chez les syndicats hébergés ailleurs (content.ExternalArticle) :
    # le gabarit a besoin de les distinguer pour ouvrir les seconds dans un
    # nouvel onglet. Dire ici « je suis chez nous » vaut mieux que compter sur
    # l'absence d'attribut.
    is_external = False

    body = StreamField(
        CorpsBlock(ARTICLE_BODY_BLOCKS),
        blank=True,
        use_json_field=True,
    )
    excerpt = models.TextField(
        blank=True, verbose_name="Extrait",
        help_text="Le texte de présentation sur les listes et dans la newsletter. "
                  "Laissé vide, il est repris du début de l'article.",
    )
    featured_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Image mise en avant",
        help_text="⚠️ Sans image, votre article passe DERRIÈRE tous les articles "
                  "illustrés de sa rubrique, quelle que soit sa date — les listes "
                  "du site classent les articles illustrés d'abord. Un article "
                  "publié aujourd'hui sans image arrive en bas de page.",
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name="Mis en avant sur l'accueil de la confédération",
        help_text="Réservé aux articles du site confédéral : place l'article en "
                  "position vedette sur cnt-so.org. Pour mettre un article en "
                  "avant sur l'accueil de VOTRE syndicat, utilisez « Dans le "
                  "carrousel de l'accueil ».",
    )
    in_carousel = models.BooleanField(
        default=False,
        verbose_name="Dans le carrousel de l'accueil",
        help_text="Ajoute cet article au carrousel mis en avant (syndicats sectoriels uniquement, 5 max)",
    )
    featured_on_conf = models.BooleanField(
        default=False,
        verbose_name="Mettre en avant sur la confédération",
        help_text="Affiche cet article dans la section vedette de la page d'accueil de la confédération (tous syndicats)",
    )
    author_name = models.CharField(max_length=200, blank=True, verbose_name="Auteur")
    publication_date = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Date de publication",
        help_text="Date originale (WordPress / import)",
    )
    cms_categories = ParentalManyToManyField(
        'cms.CmsCategory',
        blank=True,
        related_name='articles',
        verbose_name="Catégories",
    )
    cms_tags = ClusterTaggableManager(
        through='cms.CmsArticleTag',
        blank=True,
        verbose_name="Tags",
    )
    section_slug = models.SlugField(
        max_length=100, blank=True, db_index=True,
        help_text="Slug dénormalisé de la SectionPage parente",
    )
    legacy_article_id = models.IntegerField(null=True, blank=True, db_index=True)
    legacy_wp_id = models.IntegerField(null=True, blank=True)

    search_fields = Page.search_fields + [
        index.SearchField('body'),
        index.SearchField('excerpt'),
        index.FilterField('section_slug'),
        index.FilterField('publication_date'),
        index.FilterField('is_featured'),
    ]

    promote_panels = SeoMixin.seo_panels + Page.promote_panels + [
        FieldPanel('legacy_article_id'),
        FieldPanel('legacy_wp_id'),
    ]

    # `edit_handler` et non `content_panels` : le `TabbedInterface` doit être la
    # racine de l'écran. Imbriqué dans `content_panels`, il produisait un onglet
    # « Contenu » à l'intérieur de l'onglet « Contenu » (audit du 15/08/2026).
    # Les onglets viennent de `panneaux_article()`, partagé avec le viewset —
    # c'est ce qui empêche les deux écrans d'édition de diverger à nouveau.
    edit_handler = TabbedInterface([
        ObjectList([FieldPanel('title')] + panneaux_article().children[0].children,
                   heading='Contenu'),
        panneaux_article().children[1],
        ObjectList(promote_panels, heading='Promotion'),
        ObjectList(Page.settings_panels, heading='Paramètres'),
    ])

    parent_page_types = ['cms.HomePage', 'cms.SectionPage']
    subpage_types = []

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"

    def save(self, *args, **kwargs):
        """Auto-rempli section_slug, date de publication, sync in_carousel ↔ CarouselArticle."""
        # Un article mis en ligne porte toujours une date. Tout le site trie
        # sur `('-publication_date', '-first_published_at')` : en PostgreSQL —
        # la production — un tri décroissant place les NULL EN TÊTE, donc un
        # article sans date passe devant tout le reste. SQLite les place en
        # queue, ce qui a rendu le défaut invisible en développement jusqu'au
        # 15/08/2026, où trois essais occupaient les 3 premières places du flux
        # RSS du STUCS.
        # `first_published_at` d'abord : republier un vieil article ne doit pas
        # le redater d'aujourd'hui.
        if self.live and self.publication_date is None:
            from django.utils import timezone
            self.publication_date = self.first_published_at or timezone.now()
        # Extrait repris du début de l'article quand le rédacteur n'en a pas
        # écrit — jamais par-dessus une saisie. Sans lui, la carte de l'article
        # s'affiche sans un mot de présentation (1677 articles sur 1785 dans ce
        # cas au 15/08/2026).
        if not (self.excerpt or '').strip():
            self.excerpt = extrait_depuis_corps(self.body)
        if self.pk and not self.section_slug:
            parent = self.get_parent()
            if parent:
                specific = parent.specific
                if isinstance(specific, SectionPage):
                    # Slug Wagtail : c'est celui que portent tous les contenus.
                    # Utiliser le slug WordPress hérité (Numérique « stnum »,
                    # Éducation « fter ») rendrait la page invisible côté public.
                    self.section_slug = specific.slug
                else:
                    self.section_slug = 'principal'
        super().save(*args, **kwargs)
        # Sync in_carousel with CarouselArticle (sectoral and regional)
        if self.pk and self.section_slug:
            from django.db.models import Q
            section = SectionPage.objects.filter(
                Q(slug=self.section_slug) | Q(legacy_site_slug=self.section_slug),
                section_type__in=['sectoral', 'regional'],
            ).first()
            if section:
                already_in = CarouselArticle.objects.filter(page=section, article=self).exists()
                if self.in_carousel and not already_in:
                    count = CarouselArticle.objects.filter(page=section).count()
                    if count < 5:
                        CarouselArticle.objects.create(
                            page=section,
                            article=self,
                            sort_order=count,
                        )
                elif not self.in_carousel and already_in:
                    CarouselArticle.objects.filter(page=section, article=self).delete()

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['article'] = self
        context['site'] = SectionPage.objects.filter(
            models.Q(legacy_site_slug=self.section_slug) | models.Q(slug=self.section_slug)
        ).first()

        related = (
            ArticlePage.objects
            .live()
            .filter(section_slug=self.section_slug, cms_categories__in=self.cms_categories.all())
            .exclude(pk=self.pk)
            .distinct()[:5]
        )
        context['related_articles'] = related

        first_cat = self.cms_categories.first()
        context['first_category'] = first_cat
        if first_cat:
            context['category_latest'] = (
                ArticlePage.objects.live()
                .filter(section_slug=self.section_slug, cms_categories=first_cat)
                .exclude(pk=self.pk)
                .order_by('-publication_date', '-first_published_at')[:5]
            )
        return context

    def get_template(self, request, *args, **kwargs):
        # Même gabarit que les vues publiques (content.views) : la préview
        # dans l'éditeur est ainsi fidèle au rendu réel de l'article.
        return 'content/article_detail.html'

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        try:
            if self.section_slug and self.section_slug != 'principal':
                base = section_base_url(self.section_slug)
                if base:
                    return f'{base}/article/{self.slug}/'
                return reverse('content:site_article_detail',
                               kwargs={'site_slug': self.section_slug, 'slug': self.slug})
            return url_site_principal(
                reverse('content:article_detail', kwargs={'slug': self.slug}))
        except NoReverseMatch:
            return self.url or '/'

    def get_cms_edit_url(self):
        """URL d'édition dans l'interface CMS (Wagtail snippets)."""
        from django.urls import reverse
        return reverse('wagtailsnippets_cms_articlepage:edit', args=[self.pk])

    @property
    def published_at(self):
        return self.publication_date or self.first_published_at

    @property
    def categories(self):
        return self.cms_categories

    @property
    def tags(self):
        return self.cms_tags

    @property
    def meta_description(self):
        """Extrait/résumé pour les balises meta description et og:description.
        Priorité : excerpt saisi, sinon premier bloc de texte du corps —
        jamais le titre dupliqué (mauvais pour le référencement)."""
        if self.excerpt:
            return self.excerpt.strip()
        from django.utils.html import strip_tags
        for block in self.body:
            if block.block_type == 'rich_text':
                text = strip_tags(str(block.value)).strip()
                if text:
                    return text
        return ''

    @property
    def any_image_url(self):
        """Wagtail featured_image d'abord, puis URL de l'image legacy (content.Media) en fallback."""
        if self.featured_image_id:
            return self.featured_image.file.url
        if self.legacy_article_id:
            from content.models import Article as LegacyArticle
            leg = LegacyArticle.objects.select_related('featured_image').filter(
                pk=self.legacy_article_id
            ).first()
            if leg and leg.featured_image:
                return leg.featured_image.url
        return None


class ContentPage(ContenuDeSyndicatMixin, Page):
    """Page statique — remplace content.Page."""

    body = StreamField(
        CorpsBlock(ARTICLE_BODY_BLOCKS),
        blank=True,
        use_json_field=True,
    )
    excerpt = models.TextField(blank=True)
    featured_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    author_name = models.CharField(max_length=200, blank=True)
    section_slug = models.SlugField(max_length=100, blank=True, db_index=True)
    legacy_page_id = models.IntegerField(null=True, blank=True, db_index=True)

    content_panels = Page.content_panels + [
        FieldPanel('excerpt'),
        FieldPanel('featured_image'),
        FieldPanel('author_name'),
        FieldPanel('body'),
    ]
    promote_panels = Page.promote_panels + [
        FieldPanel('section_slug'),
        FieldPanel('legacy_page_id'),
    ]

    parent_page_types = ['cms.HomePage', 'cms.SectionPage']
    subpage_types = []

    class Meta:
        verbose_name = "Page de contenu"
        verbose_name_plural = "Pages de contenu"

    def save(self, *args, **kwargs):
        """Auto-rempli section_slug depuis la page parente."""
        if self.pk:
            parent = self.get_parent()
            if parent:
                specific = parent.specific
                if isinstance(specific, SectionPage):
                    # Slug Wagtail : c'est celui que portent tous les contenus.
                    # Utiliser le slug WordPress hérité (Numérique « stnum »,
                    # Éducation « fter ») rendrait la page invisible côté public.
                    self.section_slug = specific.slug
                else:
                    self.section_slug = 'principal'
        super().save(*args, **kwargs)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['page'] = self
        context['site'] = SectionPage.objects.filter(
            models.Q(legacy_site_slug=self.section_slug) | models.Q(slug=self.section_slug)
        ).first()
        return context

    def get_template(self, request, *args, **kwargs):
        return 'cms/content_page.html'

    @property
    def meta_description(self):
        """Voir ArticlePage.meta_description : évite de dupliquer le titre."""
        if self.excerpt:
            return self.excerpt.strip()
        from django.utils.html import strip_tags
        for block in self.body:
            if block.block_type == 'rich_text':
                text = strip_tags(str(block.value)).strip()
                if text:
                    return text
        return ''


    def get_absolute_url(self):
        url = self.url or '/'
        if self.section_slug and self.section_slug != 'principal':
            base = section_base_url(self.section_slug)
            if base:
                # Sur le domaine autonome, l'URL canonique n'a pas le
                # préfixe de section (/numerique/x/ → https://domaine/x/)
                prefix = f'/{self.section_slug}/'
                if url.startswith(prefix):
                    return f'{base}/{url[len(prefix):]}'
                return f'{base}{url}'
        return url


# ── Sous-sites spécialisés (proxy) ───────────────────────────────────────────

class CarouselArticle(Orderable):
    """Article sélectionné pour le carrousel d'un sous-site (sectoriel ou régional)."""

    page = ParentalKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='carousel_items',
    )
    article = models.ForeignKey(
        'cms.ArticlePage',
        on_delete=models.CASCADE,
        related_name='+',
        verbose_name="Article",
    )

    panels = [PageChooserPanel('article', page_type='cms.ArticlePage')]

    class Meta(Orderable.Meta):
        verbose_name = "Article du carrousel"


class RegionalSectionPage(SectionPage):
    """Union régionale — proxy de SectionPage, section_type forcé à 'regional'."""

    class Meta:
        proxy = True
        verbose_name = "Union régionale"
        verbose_name_plural = "Unions régionales"

    content_panels = SectionPage.content_panels + [
        MultiFieldPanel(
            [InlinePanel('carousel_items', label="Article", max_num=5)],
            heading="Carrousel d'articles mis en avant (max 5)",
        ),
    ]

    def save(self, *args, **kwargs):
        self.section_type = 'regional'
        super().save(*args, **kwargs)

    def get_template(self, request, *args, **kwargs):
        return 'content/sectoral_site_home.html'

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['carousel_articles'] = [
            ci.article for ci in self.carousel_items.select_related('article').all()
        ]
        context['rejoindre_url'] = self.get_rejoindre_url()
        return context


class SectoralSectionPage(SectionPage):
    """Syndicat sectoriel — proxy de SectionPage, section_type forcé à 'sectoral'."""

    class Meta:
        proxy = True
        verbose_name = "Syndicat sectoriel"
        verbose_name_plural = "Syndicats sectoriels"

    content_panels = SectionPage.content_panels + [
        MultiFieldPanel(
            [InlinePanel('carousel_items', label="Article", max_num=5)],
            heading="Carrousel d'articles mis en avant (max 5)",
        ),
    ]

    def save(self, *args, **kwargs):
        self.section_type = 'sectoral'
        super().save(*args, **kwargs)

    def get_template(self, request, *args, **kwargs):
        return 'content/sectoral_site_home.html'

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['carousel_articles'] = [
            ci.article for ci in self.carousel_items.select_related('article').all()
        ]
        context['rejoindre_url'] = self.get_rejoindre_url()
        return context


# ── Événements ────────────────────────────────────────────────────────────────

from django.utils import timezone as _tz


class Event(models.Model):
    """Événement affiché sur la page agenda d'un sous-site."""

    section = models.ForeignKey(
        SectionPage,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name="Section / syndicat",
    )
    title = models.CharField(max_length=255, verbose_name="Titre")
    date = models.DateField(verbose_name="Date de début")
    end_date = models.DateField(null=True, blank=True, verbose_name="Date de fin (optionnel)")
    time = models.TimeField(null=True, blank=True, verbose_name="Heure (optionnel)")
    location = models.CharField(max_length=255, blank=True, verbose_name="Lieu")
    latitude = models.FloatField(null=True, blank=True, verbose_name="Latitude")
    longitude = models.FloatField(null=True, blank=True, verbose_name="Longitude")
    description = models.TextField(blank=True, verbose_name="Description")
    url = models.URLField(blank=True, verbose_name="Lien (optionnel)", help_text="Lien vers plus d'infos")

    panels = [
        FieldPanel('section'),
        FieldPanel('title'),
        MultiFieldPanel([
            FieldRowPanel([FieldPanel('date'), FieldPanel('end_date')]),
            FieldPanel('time'),
        ], heading="Date et heure"),
        FieldPanel('location'),
        FieldRowPanel([FieldPanel('latitude'), FieldPanel('longitude')]),
        FieldPanel('description'),
        FieldPanel('url'),
    ]

    class Meta:
        verbose_name = "Événement"
        verbose_name_plural = "Événements"
        ordering = ['date', 'time']

    def __str__(self):
        return f"{self.date:%d/%m/%Y} — {self.title}"

    @property
    def is_past(self):
        from django.utils.timezone import now
        return self.date < now().date()
