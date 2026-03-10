from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.contrib.auth.models import User


class Site(models.Model):
    """Site du multisite WordPress (principal ou sous-site)"""
    SITE_TYPE_CHOICES = [
        ('main', 'Site principal'),
        ('regional', 'Union régionale'),
        ('sectoral', 'Syndicat sectoriel'),
    ]

    wp_blog_id = models.IntegerField(unique=True, help_text="blog_id WordPress")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    path = models.CharField(max_length=100, help_text="Path WordPress (ex: /rhone-alpes/)")
    site_type = models.CharField(max_length=20, choices=SITE_TYPE_CHOICES, default='regional')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    external_url = models.URLField(blank=True, help_text="Si renseigné, les liens vers ce site pointent vers cette URL externe")

    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        if self.external_url:
            return self.external_url
        if self.slug == 'principal':
            return reverse('content:home')
        return reverse('content:site_home', kwargs={'site_slug': self.slug})


class Author(models.Model):
    """Auteur/rédacteur du site"""
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='author_profile'
    )
    site = models.ForeignKey(
        'Site', null=True, blank=True, on_delete=models.SET_NULL,
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


class Category(models.Model):
    """Catégorie d'articles"""
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='categories',
        null=True,
        blank=True
    )
    wp_id = models.IntegerField(null=True, blank=True, help_text="ID WordPress original")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ['name']
        unique_together = [['site', 'slug'], ['site', 'wp_id']]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('content:category_detail', kwargs={'slug': self.slug})


class Tag(models.Model):
    """Tag/étiquette pour les articles"""
    site = models.ForeignKey(
        Site,
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
        Site,
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
        """Fichier local s'il existe, sinon URL WordPress d'origine."""
        if self.file:
            return self.file.url
        return self.original_url


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
        Site,
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
    categories = models.ManyToManyField(Category, blank=True, related_name='articles')
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
        if self.site and self.site.slug != 'principal':
            return reverse('content:site_article_detail', kwargs={'site_slug': self.site.slug, 'slug': self.slug})
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
        Site,
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
        if self.site and self.site.slug != 'principal':
            return reverse('content:site_page_detail', kwargs={'site_slug': self.site.slug, 'slug': self.slug})
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
        'Site', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='contact_messages', verbose_name="Site"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    email = models.EmailField(verbose_name="Email")
    phone = models.CharField(max_length=30, default='', verbose_name="Téléphone")
    city = models.CharField(max_length=100, default='', verbose_name="Ville")
    sector = models.CharField(max_length=200, default='', verbose_name="Secteur professionnel")
    subject = models.CharField(max_length=300, blank=True, verbose_name="Objet")
    message = models.TextField(blank=True, verbose_name="Message")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Message de contact"
        verbose_name_plural = "Messages de contact"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} - {self.name}"


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
    ]

    site = models.ForeignKey(
        Site,
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
    article = models.ForeignKey(Article, on_delete=models.SET_NULL, null=True, blank=True)
    page = models.ForeignKey(Page, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    target_site = models.ForeignKey(
        Site,
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
