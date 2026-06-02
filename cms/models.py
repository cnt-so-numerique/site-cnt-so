from django import forms
from django.db import models
from django.utils.text import slugify

from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from taggit.models import TaggedItemBase

from wagtail import blocks
from wagtail.admin.panels import (
    FieldPanel, FieldRowPanel, MultiFieldPanel, ObjectList, TabbedInterface,
)
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Orderable, Page
from wagtail.search import index
from wagtail.snippets.models import register_snippet


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
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        try:
            if self.section_slug and self.section_slug != 'principal':
                return reverse('content:site_category_detail',
                               kwargs={'site_slug': self.section_slug, 'slug': self.slug})
            return reverse('content:category_detail', kwargs={'slug': self.slug})
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
    'bold', 'italic', 'underline', 'strikethrough',
    'h2', 'h3', 'h4', 'h5',
    'ol', 'ul',
    'link',
    'blockquote',
    'hr',
]


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

    class Meta:
        icon = 'image'
        label = "Image"
        template = 'cms/blocks/image_block.html'


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


ARTICLE_BODY_BLOCKS = [
    ('rich_text', blocks.RichTextBlock(
        features=RICHTEXT_FEATURES,
        label="Texte",
        template='cms/blocks/rich_text_block.html',
    )),
    ('image', ImageBlock()),
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

class HomePage(Page):
    """Page racine du site CNT-SO. Une seule instance."""

    intro_text = models.TextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro_text'),
    ]

    subpage_types = ['cms.SectionPage', 'cms.ArticlePage', 'cms.ContentPage']

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
        sticky = list(base_qs.filter(is_featured=True)[:4])
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


class SectionPage(Page):
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
    agenda_url = models.URLField(blank=True)
    linkstack_url = models.URLField(blank=True, verbose_name="URL Linkstack")
    framaform_url = models.URLField(blank=True, verbose_name="URL Framaform adhésion")
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
        FieldPanel('agenda_url'),
        FieldPanel('linkstack_url'),
        FieldPanel('framaform_url'),
        FieldPanel('intro_text'),
        FieldPanel('rejoindre_text'),
        FieldPanel('agenda_text'),
        FieldPanel('logo'),
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

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        if self.external_url:
            return self.external_url
        slug = self.legacy_site_slug or self.slug
        try:
            if slug == 'principal':
                return reverse('content:home')
            return reverse('content:site_home', kwargs={'site_slug': slug})
        except NoReverseMatch:
            return self.url or '/'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # S'assurer que legacy_site_slug est renseigné
        slug = self.legacy_site_slug or self.slug
        if slug and not self.legacy_site_slug:
            SectionPage.objects.filter(pk=self.pk).update(legacy_site_slug=slug)


class ArticlePage(Page):
    """Article de blog — remplace content.Article."""

    body = StreamField(
        ARTICLE_BODY_BLOCKS,
        blank=True,
        use_json_field=True,
    )
    excerpt = models.TextField(blank=True, verbose_name="Extrait")
    featured_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Image mise en avant",
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name="Article mis en avant (sticky)",
    )
    author_name = models.CharField(max_length=200, blank=True, verbose_name="Auteur")
    author_user = models.ForeignKey(
        'auth.User',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='cms_articles',
        verbose_name="Compte utilisateur auteur",
    )
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

    content_panels = Page.content_panels + [
        TabbedInterface([
            ObjectList([
                MultiFieldPanel([
                    FieldPanel('publication_date'),
                    FieldPanel('is_featured'),
                    FieldPanel('author_name'),
                    FieldPanel('author_user'),
                ], heading="Publication"),
                FieldPanel('excerpt'),
                FieldPanel('featured_image'),
                FieldPanel('cms_categories', widget=forms.CheckboxSelectMultiple),
                FieldPanel('cms_tags'),
            ], heading='Métadonnées'),
            ObjectList([
                FieldPanel('body'),
            ], heading='Contenu'),
        ])
    ]

    promote_panels = Page.promote_panels + [
        FieldPanel('section_slug'),
        FieldPanel('legacy_article_id'),
        FieldPanel('legacy_wp_id'),
    ]

    parent_page_types = ['cms.HomePage', 'cms.SectionPage']
    subpage_types = []

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"

    def save(self, *args, **kwargs):
        """Auto-rempli section_slug depuis la page parente."""
        if self.pk:
            parent = self.get_parent()
            if parent:
                specific = parent.specific
                if isinstance(specific, SectionPage):
                    self.section_slug = specific.legacy_site_slug or specific.slug
                else:
                    self.section_slug = 'principal'
        super().save(*args, **kwargs)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['article'] = self
        context['site'] = SectionPage.objects.filter(legacy_site_slug=self.section_slug).first()

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
        return 'cms/article_detail.html'

    def get_absolute_url(self):
        from django.urls import reverse, NoReverseMatch
        try:
            if self.section_slug and self.section_slug != 'principal':
                return reverse('content:site_article_detail',
                               kwargs={'site_slug': self.section_slug, 'slug': self.slug})
            return reverse('content:article_detail', kwargs={'slug': self.slug})
        except NoReverseMatch:
            return self.url or '/'

    @property
    def published_at(self):
        return self.publication_date or self.first_published_at

    @property
    def categories(self):
        return self.cms_categories

    @property
    def tags(self):
        return self.cms_tags


class ContentPage(Page):
    """Page statique — remplace content.Page."""

    body = StreamField(
        ARTICLE_BODY_BLOCKS,
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
                    self.section_slug = specific.legacy_site_slug or specific.slug
                else:
                    self.section_slug = 'principal'
        super().save(*args, **kwargs)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['page'] = self
        context['site'] = SectionPage.objects.filter(legacy_site_slug=self.section_slug).first()
        return context

    def get_template(self, request, *args, **kwargs):
        return 'cms/content_page.html'

    def get_absolute_url(self):
        return self.url or '/'


# ── Événements ────────────────────────────────────────────────────────────────

from wagtail.snippets.models import register_snippet as _register_snippet
from django.utils import timezone as _tz


@_register_snippet
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
