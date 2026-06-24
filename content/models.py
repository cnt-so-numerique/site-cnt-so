import uuid
from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.contrib.auth.models import User
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel



class Author(models.Model):
    """Auteur/rédacteur du site"""
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='author_profile'
    )
    site = models.ForeignKey(
        'cms.SectionPage', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='team_members', verbose_name='Site assigné'
    )
    wp_id = models.IntegerField(unique=True, null=True, blank=True, help_text="ID WordPress original")
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Auteur"
        verbose_name_plural = "Auteurs"

    def __str__(self):
        return self.display_name or self.username



class Tag(models.Model):
    """Tag/étiquette pour les articles"""
    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='tags',
        null=True,
        blank=True,
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        ordering = ['name']
        unique_together = [['site', 'slug']]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Media(models.Model):
    """Fichier média (image, PDF, etc.)"""
    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='medias',
        null=True,
        blank=True
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    title = models.CharField(max_length=300, blank=True)
    file = models.FileField(upload_to='uploads/%Y/%m/', blank=True)
    original_url = models.URLField(max_length=500, blank=True, help_text="URL WordPress originale")
    mime_type = models.CharField(max_length=100, blank=True)
    alt_text = models.CharField(max_length=300, blank=True)
    caption = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Média"
        verbose_name_plural = "Médias"

    def __str__(self):
        return self.title or self.original_url

    @property
    def url(self):
        """Fichier local s'il existe, sinon URL WordPress d'origine (uniquement si accessible)."""
        if self.file:
            return self.file.url
        if self.original_url and self.original_url.startswith('/media/'):
            import os
            from django.conf import settings
            rel = self.original_url[len('/media/'):]
            if os.path.exists(os.path.join(settings.MEDIA_ROOT, rel)):
                return self.original_url
            return None
        return self.original_url or None


class Article(models.Model):
    """Article de blog"""
    STATUS_CHOICES = [
        ('draft', 'Brouillon'),
        ('publish', 'Publié'),
        ('pending', 'En attente'),
        ('private', 'Privé'),
        ('trash', 'Corbeille'),
    ]

    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='articles',
        null=True,
        blank=True
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True, verbose_name="Extrait")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    author = models.ForeignKey(
        Author,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articles'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='articles')
    featured_image = models.ForeignKey(
        Media,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_in_articles'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    wp_date = models.DateTimeField(null=True, blank=True, help_text="Date WordPress originale")

    is_sticky = models.BooleanField(default=False, verbose_name="Article mis en avant")
    comment_status = models.CharField(max_length=20, default='open')

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ['-published_at', '-created_at']
        unique_together = [['site', 'slug'], ['site', 'wp_id']]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.site:
            site_slug = self.site.legacy_site_slug or self.site.slug
            if site_slug != 'principal':
                return reverse('content:site_article_detail', kwargs={'site_slug': site_slug, 'slug': self.slug})
        return reverse('content:article_detail', kwargs={'slug': self.slug})


class Page(models.Model):
    """Page statique du site"""
    STATUS_CHOICES = [
        ('draft', 'Brouillon'),
        ('publish', 'Publié'),
        ('pending', 'En attente'),
        ('private', 'Privé'),
        ('trash', 'Corbeille'),
    ]

    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='pages',
        null=True,
        blank=True
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    author = models.ForeignKey(
        Author,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pages'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    featured_image = models.ForeignKey(
        Media,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_in_pages'
    )

    menu_order = models.IntegerField(default=0)
    template = models.CharField(max_length=100, blank=True, default='default')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    wp_date = models.DateTimeField(null=True, blank=True, help_text="Date WordPress originale")

    class Meta:
        verbose_name = "Page"
        verbose_name_plural = "Pages"
        ordering = ['menu_order', 'title']
        unique_together = [['site', 'slug'], ['site', 'wp_id']]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.site:
            site_slug = self.site.legacy_site_slug or self.site.slug
            if site_slug != 'principal':
                return reverse('content:site_page_detail', kwargs={'site_slug': site_slug, 'slug': self.slug})
        return reverse('content:page_detail', kwargs={'slug': self.slug})


class Comment(models.Model):
    """Commentaire sur un article"""
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('spam', 'Spam'),
        ('trash', 'Corbeille'),
    ]

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    author_name = models.CharField(max_length=200)
    author_email = models.EmailField(blank=True)
    author_url = models.URLField(blank=True)
    author_ip = models.GenericIPAddressField(null=True, blank=True)
    content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    wp_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Commentaire"
        verbose_name_plural = "Commentaires"
        ordering = ['created_at']

    def __str__(self):
        return f"Commentaire de {self.author_name} sur {self.article.title[:30]}"


class ContactMessage(models.Model):
    """Message du formulaire de contact"""
    site = models.ForeignKey(
        'cms.SectionPage', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='contact_messages', verbose_name="Site"
    )
    formulaire = models.ForeignKey(
        'FormulaireContact', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='submissions', verbose_name="Formulaire"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    email = models.EmailField(verbose_name="Email")
    phone = models.CharField(max_length=30, default='', blank=True, verbose_name="Téléphone")
    city = models.CharField(max_length=100, default='', blank=True, verbose_name="Ville")
    sector = models.CharField(max_length=200, default='', blank=True, verbose_name="Secteur professionnel")
    subject = models.CharField(max_length=300, blank=True, verbose_name="Objet")
    message = models.TextField(blank=True, verbose_name="Message")
    custom_data = models.JSONField(default=dict, blank=True, verbose_name="Champs supplémentaires")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Message de contact"
        verbose_name_plural = "Messages de contact"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject or '(sans objet)'} – {self.name}"


class FormulaireContact(models.Model):
    """Formulaire de contact configurable par syndicat."""
    site = models.OneToOneField(
        'cms.SectionPage', on_delete=models.CASCADE, related_name='formulaire_contact',
        null=True, blank=True, verbose_name='Syndicat'
    )
    is_active = models.BooleanField(default=True, verbose_name='Actif')
    email_destination = models.EmailField(
        blank=True, verbose_name='Email de destination',
        help_text="Laissez vide pour utiliser l'email de contact du syndicat"
    )
    email_subject_prefix = models.CharField(
        max_length=100, blank=True, verbose_name='Préfixe du sujet',
        help_text='Ajouté au début du sujet (ex : [Contact CNT-SO])'
    )
    intro_text = models.TextField(blank=True, verbose_name="Texte d'introduction")
    field_nom = models.BooleanField(default=True, verbose_name='Champ Nom')
    field_telephone = models.BooleanField(default=False, verbose_name='Champ Téléphone')
    field_ville = models.BooleanField(default=False, verbose_name='Champ Ville')
    field_secteur = models.BooleanField(default=False, verbose_name='Champ Secteur')
    field_objet = models.BooleanField(default=True, verbose_name='Champ Objet')

    class Meta:
        verbose_name = "Formulaire de contact"
        verbose_name_plural = "Formulaires de contact"

    def __str__(self):
        return f"Contact – {self.site.name if self.site else '(sans site)'}"

    def get_email_destination(self):
        return self.email_destination or getattr(self.site, 'contact_email', '') or ''


class ChampContactCustom(models.Model):
    FIELD_TYPE_CHOICES = [
        ('text', 'Texte court'),
        ('textarea', 'Texte long'),
        ('select', 'Liste déroulante'),
        ('checkbox', 'Case à cocher'),
    ]
    formulaire = models.ForeignKey(
        FormulaireContact, on_delete=models.CASCADE, related_name='champs_custom'
    )
    label = models.CharField(max_length=200, verbose_name='Libellé')
    slug = models.SlugField(max_length=100)
    field_type = models.CharField(
        max_length=20, choices=FIELD_TYPE_CHOICES, default='text', verbose_name='Type'
    )
    choices_text = models.TextField(
        blank=True, verbose_name='Options',
        help_text='Une option par ligne (pour les listes déroulantes)'
    )
    is_required = models.BooleanField(default=False, verbose_name='Obligatoire')
    order = models.IntegerField(default=0, verbose_name='Ordre')

    class Meta:
        ordering = ['order', 'pk']
        verbose_name = "Champ personnalisé"
        verbose_name_plural = "Champs personnalisés"

    def __str__(self):
        return f"{self.label} ({self.formulaire.site.name})"

    def get_choices_list(self):
        return [c.strip() for c in self.choices_text.splitlines() if c.strip()]


class MenuItem(models.Model):
    """Élément de menu de navigation"""
    MENU_CHOICES = [
        ('main', 'Menu principal'),
        ('footer', 'Menu pied de page'),
        ('secondary', 'Menu secondaire'),
    ]
    LINK_TYPE_CHOICES = [
        ('url',      'URL externe / personnalisée'),
        ('category', 'Catégorie du site'),
        ('site',     'Lien vers un site CNT'),
        ('article',  'Article du site'),
        ('page',     'Page du site'),
        ('contact',  'Formulaire de contact'),
        ('agenda',   'Agenda'),
    ]

    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='menu_items',
        null=True,
        blank=True,
    )
    menu = models.CharField(max_length=20, choices=MENU_CHOICES, default='main')
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, default='url')
    title = models.CharField(max_length=200)
    url = models.CharField(max_length=500, blank=True)

    # Lien vers un contenu interne (optionnel)
    article = models.ForeignKey('cms.ArticlePage', on_delete=models.SET_NULL, null=True, blank=True)
    page = models.ForeignKey('cms.ContentPage', on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey('cms.CmsCategory', on_delete=models.SET_NULL, null=True, blank=True)
    target_site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_as_target',
    )

    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    opens_new_tab = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Élément de menu"
        verbose_name_plural = "Éléments de menu"
        ordering = ['menu', 'order']

    def __str__(self):
        return f"{self.get_menu_display()} - {self.title}"

    def get_url(self):
        """Retourne l'URL du lien selon link_type."""

        if self.link_type == 'url' or not self.link_type:
            return self.url or '#'
        if self.link_type == 'category' and self.category:
            return self.category.get_absolute_url()
        if self.link_type == 'site' and self.target_site:
            return self.target_site.get_absolute_url()
        if self.link_type == 'article' and self.article:
            return self.article.get_absolute_url()
        if self.link_type == 'page' and self.page:
            return self.page.get_absolute_url()
        if self.link_type == 'contact':
            from django.urls import reverse
            if self.site and self.site.slug != 'principal':
                return reverse('content:site_contact', kwargs={'site_slug': self.site.slug})
            return reverse('content:contact')
        if self.link_type == 'agenda' and self.site and self.site.slug != 'principal':
            from django.urls import reverse
            return reverse('content:site_agenda', kwargs={'site_slug': self.site.slug})
        # Fallback legacy
        if self.url:
            return self.url
        if self.article:
            return self.article.get_absolute_url()
        if self.page:
            return self.page.get_absolute_url()
        if self.category:
            return self.category.get_absolute_url()
        return '#'


# ── Newsletter ─────────────────────────────────────────────────────────────────

class Subscriber(models.Model):
    """Abonné à la newsletter d'un site."""
    site = models.ForeignKey(
        'cms.SectionPage', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='newsletter_subscribers', verbose_name='Site'
    )
    email = models.EmailField(verbose_name='Adresse e-mail')
    name = models.CharField(max_length=200, blank=True, verbose_name='Nom')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=False, verbose_name='Confirmé')
    subscribed_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Abonné'
        verbose_name_plural = 'Abonnés'
        ordering = ['-subscribed_at']
        unique_together = [['site', 'email']]

    def __str__(self):
        return f'{self.email} ({self.site.name})'


class Newsletter(ClusterableModel, models.Model):
    """Newsletter envoyée aux abonnés d'un site."""
    STATUS_CHOICES = [
        ('draft', 'Brouillon'),
        ('sent', 'Envoyée'),
    ]
    site = models.ForeignKey(
        'cms.SectionPage', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='newsletters', verbose_name='Site'
    )
    title = models.CharField(max_length=300, verbose_name="Sujet de l'e-mail")
    intro = models.TextField(verbose_name="Texte d'introduction")
    articles = models.ManyToManyField(
        Article, through='NewsletterArticle', blank=True,
        verbose_name='Articles sélectionnés'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='sent_newsletters'
    )
    sent_count = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Newsletter'
        verbose_name_plural = 'Newsletters'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class NewsletterArticle(models.Model):
    """Article inclus dans une newsletter, avec ordre d'affichage."""
    newsletter = ParentalKey(
        Newsletter, on_delete=models.CASCADE, related_name='newsletter_articles'
    )
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = [['newsletter', 'article']]
