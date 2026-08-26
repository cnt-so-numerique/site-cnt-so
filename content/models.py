import uuid
from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.contrib.auth.models import User
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.models import Orderable



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
    first_name = models.CharField(max_length=200, default='', blank=True, verbose_name="Prénom")
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
    featured_image = models.ForeignKey(
        'wagtailimages.Image', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name="Image d'illustration",
    )
    field_nom = models.BooleanField(default=True, verbose_name='Champ Nom')
    field_prenom = models.BooleanField(default=False, verbose_name='Champ Prénom')
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
    # Deux menus, parce que `base.html` n'en affiche que deux : `main` et
    # `footer`. Un troisième choix, « Menu secondaire », a été proposé aux
    # rédacteurs pendant des mois alors qu'aucun gabarit ne l'appelait : la
    # prod portait dix entrées invisibles, éditables, sans effet — purgées le
    # 17/08/2026. Ne rajouter un choix ici qu'en même temps que le `get_menu`
    # qui le rend.
    MENU_CHOICES = [
        ('main', 'Menu principal'),
        ('footer', 'Menu pied de page'),
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

    def _canonique(self, url):
        """Normalise une URL saisie à la main dans le menu.

        Un rédacteur tape naturellement `/stucs/ressources/` ; sur un domaine
        autonome c'est justement la forme que le middleware redirige en 301.
        On la ramène à l'URL finale, en gardant la chaîne de requête. Les URL
        externes et celles d'une autre section sont laissées telles quelles.
        """
        if not url or not url.startswith('/') or not self.site:
            return url
        from cms.models import section_base_url
        base = section_base_url(self.site.slug)
        if not base:
            return url
        for slug in self.site.slugs_contenu:
            if url == f'/{slug}':
                return f'{base}/'
            if url.startswith(f'/{slug}/'):
                return f'{base}{url[len(slug) + 1:]}'
        return url

    def get_url(self):
        """Retourne l'URL du lien selon link_type."""

        if self.link_type == 'url' or not self.link_type:
            return self._canonique(self.url) or '#'
        if self.link_type == 'category' and self.category:
            return self.category.get_absolute_url()
        if self.link_type == 'site' and self.target_site:
            return self._url_absolue_si_besoin(self.target_site.get_absolute_url())
        if self.link_type == 'article' and self.article:
            return self.article.get_absolute_url()
        if self.link_type == 'page' and self.page:
            return self.page.get_absolute_url()
        # Ces deux liens sont dans le menu de toutes les pages : sur un domaine
        # autonome, la forme préfixée coûterait une redirection 301 par clic.
        if self.link_type == 'contact':
            from django.urls import reverse
            from cms.models import section_base_url
            if self.site and self.site.slug != 'principal':
                base = section_base_url(self.site.slug)
                if base:
                    return f'{base}/contact/'
                return reverse('content:site_contact', kwargs={'site_slug': self.site.slug})
            return reverse('content:contact')
        if self.link_type == 'agenda' and self.site and self.site.slug != 'principal':
            from django.urls import reverse
            from cms.models import section_base_url
            base = section_base_url(self.site.slug)
            if base:
                return f'{base}/agenda/'
            return reverse('content:site_agenda', kwargs={'site_slug': self.site.slug})
        # Fallback legacy
        if self.url:
            return self._canonique(self.url)
        if self.article:
            return self.article.get_absolute_url()
        if self.page:
            return self.page.get_absolute_url()
        if self.category:
            return self.category.get_absolute_url()
        return '#'

    def _url_absolue_si_besoin(self, url):
        """Rend absolue une URL de section quand le menu est servi ailleurs.

        Les URLs de section sont relatives au site principal. Servies depuis un
        domaine autonome, elles y bouclent : « CNT-SO national » vaut '/' et
        renvoyait donc à l'accueil de la fédération elle-même, pas à la
        confédération (vérifié le 05/08/2026 — `auvergne.cnt-so.org/` affiche
        « CNT-SO Auvergne »). Même correction que le tag `section_url` de la
        passe 5, appliquée ici parce que `get_url()` n'a pas de requête.
        """
        if not url or not url.startswith('/'):
            return url
        if not (self.site and self.site.custom_domain):
            return url
        from django.conf import settings
        base = getattr(settings, 'MAIN_SITE_BASE_URL', '')
        return f'{base}{url}' if base else url

    # Champ à renseigner selon le type de lien. `url` n'y figure pas : une URL
    # vide reste un usage légitime pour un parent de sous-menu.
    _CIBLE_REQUISE = {
        'category': 'category',
        'site': 'target_site',
        'article': 'article',
        'page': 'page',
    }

    def clean(self):
        """Refuse un lien dont la cible manque.

        `get_url()` retombe silencieusement sur '#' quand la cible n'est pas
        renseignée : le lien s'enregistre sans broncher et ne mène nulle part.
        La production comptait 8 entrées dans cet état, dont « CNT-SO national »
        au premier niveau du menu de quatre sous-sites (audit du 05/08/2026).
        """
        super().clean()
        champ = self._CIBLE_REQUISE.get(self.link_type)
        if champ and getattr(self, f'{champ}_id', None) is None:
            from django.core.exceptions import ValidationError
            libelle = dict(self.LINK_TYPE_CHOICES).get(self.link_type, self.link_type)
            raise ValidationError({champ: (
                f"Choisissez une cible : le type de lien « {libelle} » ne mène "
                "nulle part sans elle.")})

    @property
    def est_impasse(self):
        """Le lien ne mène nulle part ET n'ouvre aucun sous-menu.

        Les cibles sont en `on_delete=SET_NULL` : un lien valide à sa création
        se vide tout seul quand sa cible est supprimée, sans qu'aucun
        enregistrement ne repasse par `clean()`. D'où ce second filet, à
        l'affichage. Un parent de sous-menu à '#' n'est pas une impasse : son
        rôle est d'ouvrir le menu, pas de naviguer.

        `children.all()` et non `children.exists()` : le menu est rendu sur
        toutes les pages et `get_menu` précharge les enfants — `exists()`
        ignorerait ce cache et rouvrirait le N+1 corrigé en juillet.
        """
        return self.get_url() in ('#', '', None) and not self.children.all()

    @property
    def should_open_new_tab(self):
        """Ouvre dans un nouvel onglet si explicitement demandé ou si l'URL est
        réellement externe (les domaines autonomes des sections restent internes)."""
        if self.opens_new_tab:
            return True
        url = self.get_url()
        if not (url.startswith('http://') or url.startswith('https://')):
            return False
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        return host not in self._internal_hosts()

    @staticmethod
    def _internal_hosts():
        from django.core.cache import cache
        hosts = cache.get('menu-internal-hosts')
        if hosts is None:
            from urllib.parse import urlparse
            from django.conf import settings
            from cms.models import SectionPage
            hosts = set(SectionPage.objects.exclude(custom_domain='')
                        .values_list('custom_domain', flat=True))
            main = getattr(settings, 'MAIN_SITE_BASE_URL', '')
            if main:
                hosts.add(urlparse(main).hostname or '')
            cache.set('menu-internal-hosts', hosts, 60)
        return hosts


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
    ovh_list = models.CharField(
        max_length=100, blank=True, verbose_name='Liste OVH',
        help_text="Liste OVH sur laquelle cet abonné a été inscrit "
                  "(répartition automatique quand un site a plusieurs listes)",
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Abonné'
        verbose_name_plural = 'Abonnés'
        ordering = ['-subscribed_at']
        unique_together = [['site', 'email']]

    def __str__(self):
        # `site` est nul pour les abonnés confédéraux : c'est ainsi que le
        # webhook cnt-adhesion les enregistre, et `cms/apps.py` les renvoie
        # vers les listes du site principal. Sans ce garde-fou, afficher un
        # tel abonné — liste des snippets, journal, page de suppression —
        # lève une AttributeError et rend une 500.
        return f'{self.email} ({self.site.name if self.site else "Confédération"})'


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
    # Le raccourci `articles` (ManyToMany à travers NewsletterArticle) est
    # tombé le 18/08/2026 : les articles pendent désormais à une rubrique, pas
    # à la lettre. Personne ne s'en servait — `articles_a_plat()` le remplace.
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

    def articles_a_plat(self):
        """Tous les articles de la lettre, rubrique après rubrique.

        La vue d'envoi annote chaque ligne d'URLs absolues avant le rendu :
        elle a besoin d'une liste plate, que `par_rubrique` regroupe ensuite.
        """
        return [
            na
            for bloc in self.rubriques.all().prefetch_related('articles__article')
            for na in bloc.articles.all()
        ]

    def par_rubrique(self, articles=None):
        """Les articles groupés par rubrique, prêts à composer le sommaire.

        Renvoie une liste de `(libellé, [articles])`, **dans l'ordre où le
        rédacteur a rangé ses rubriques** — cet ordre était figé dans le code
        jusqu'au 18/08/2026, où la rubrique est devenue un bloc à part entière
        portant ses articles. Une rubrique vide est sautée : choisir les
        articles suffit à composer l'e-mail, il n'y a aucune section à cocher.

        `articles` permet de passer la liste déjà annotée d'URLs d'images par
        la vue d'envoi, plutôt que de relire la base. L'aperçu, l'envoi HTML et
        la version texte partagent ainsi un seul groupement — trois rendus qui
        divergeraient sinon.
        """
        if articles is None:
            articles = self.articles_a_plat()
        par_bloc = {}
        for na in articles:
            par_bloc.setdefault(na.bloc_id, []).append(na)
        groupes = []
        for bloc in self.rubriques.all():
            dedans = par_bloc.get(bloc.pk)
            if dedans:
                groupes.append((bloc.libelle, dedans))
        return groupes


#: Le découpage de la newsletter confédérale. Ce sont des rubriques propres à
#: l'envoi, pas les catégories du site : « actu syndicale » et « actu générale »
#: n'existent pas en catégorie, et la conf compose son sommaire comme elle
#: l'entend. L'ordre de ce tuple est l'ordre des sections dans l'e-mail.
RUBRIQUES_NEWSLETTER = [
    ('campagne', 'Campagnes'),
    ('actu-syndicale', 'Actu syndicale'),
    ('actu-generale', 'Actu générale'),
    ('droits', 'Nos droits'),
    ('international', 'International'),
]


class NewsletterRubrique(ClusterableModel, Orderable):
    """Une section de la lettre, et les articles qu'elle contient.

    Jusqu'au 18/08/2026, chaque article portait le nom de sa rubrique : mettre
    cinq articles en « Campagnes » obligeait à choisir « Campagnes » cinq fois,
    et rien ne montrait le sommaire tel qu'il serait lu. Arnaud : « possible de
    simplement choisir une catégorie et en dessous plusieurs articles ? ».

    L'ordre des rubriques devient du même coup celui du rédacteur, alors qu'il
    était figé dans `RUBRIQUES_NEWSLETTER`.
    """

    newsletter = ParentalKey(
        Newsletter, on_delete=models.CASCADE, related_name='rubriques',
    )
    rubrique = models.CharField(
        max_length=30, blank=True,
        # Le choix vide est nommé : sans lui, Django affiche « --------- »,
        # et personne ne devine qu'une section peut n'avoir aucun titre.
        choices=[('', 'Sans titre de section')] + RUBRIQUES_NEWSLETTER,
        verbose_name='Rubrique',
        help_text="Le titre de section affiché dans l'e-mail. Sans titre, les "
                  "articles ouvrent la lettre, avant toute section.",
    )

    class Meta(Orderable.Meta):
        verbose_name = 'Rubrique de la newsletter'
        verbose_name_plural = 'Rubriques de la newsletter'

    @property
    def libelle(self):
        return dict(RUBRIQUES_NEWSLETTER).get(self.rubrique, '')

    def __str__(self):
        return self.libelle or 'Sans titre'


class NewsletterArticle(Orderable):
    """Un article dans une rubrique. L'ordre des blocs est celui de la lettre."""

    bloc = ParentalKey(
        NewsletterRubrique, on_delete=models.CASCADE, related_name='articles',
    )
    article = models.ForeignKey(
        'cms.ArticlePage', on_delete=models.CASCADE,
        related_name='+', verbose_name='Article',
    )

    class Meta(Orderable.Meta):
        verbose_name = 'Article de la newsletter'
        verbose_name_plural = 'Articles de la newsletter'

    def __str__(self):
        return self.article.title if self.article_id else ''


class Permanence(models.Model):
    """Permanence syndicale et juridique d'un syndicat local.

    Ces coordonnées vivaient dans un bloc HTML écrit à la main sur la page
    « Nos permanences juridiques » : ajouter une ville supposait de recopier
    des `<div style="...">`, ce qu'aucun rédacteur ne pouvait faire sans
    risque — et l'ancien rouge, écarté pour contraste insuffisant, y traînait
    encore faute d'oser y toucher (relevé par Arnaud, 16/08/2026).
    """

    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='permanences',
        null=True, blank=True,
        verbose_name='Syndicat',
        help_text="Le syndicat qui tient cette permanence.",
    )
    ville = models.CharField(
        max_length=120,
        help_text="Tel qu'affiché en titre de fiche, ex. « CNT-SO 13 — Marseille ».",
    )
    adresse = models.CharField(
        max_length=300,
        help_text="Rue, code postal, ville. Ajoutez le métro ou l'arrêt si utile.",
    )
    horaires = models.CharField(
        max_length=200, blank=True,
        help_text="Ex. « Lun–Ven 09h–12h / 14h–17h ». Laisser vide si variable.",
    )
    telephone = models.CharField(max_length=40, blank=True)
    telephone_secondaire = models.CharField(
        max_length=40, blank=True,
        help_text="Second numéro, si la permanence en annonce deux.",
    )
    email = models.EmailField(blank=True)
    lien = models.URLField(
        blank=True,
        help_text="Page ou site du syndicat. Laisser vide s'il n'y en a pas : "
                  "le bouton disparaît alors.",
    )
    libelle_lien = models.CharField(
        max_length=60, blank=True, default='En savoir plus',
        verbose_name='Libellé du bouton',
    )
    order = models.PositiveIntegerField(
        default=0, verbose_name='Ordre',
        help_text="Les plus petits nombres s'affichent en premier.",
    )
    is_active = models.BooleanField(default=True, verbose_name='Affichée')

    class Meta:
        verbose_name = 'Permanence juridique'
        verbose_name_plural = 'Permanences juridiques'
        ordering = ['order', 'ville']

    def __str__(self):
        return self.ville

    @property
    def telephones(self):
        """Les numéros renseignés, chacun avec sa forme cliquable.

        Le gabarit reçoit le couple tout fait plutôt que d'enchaîner trois
        filtres `cut` pour fabriquer le `tel:` — c'était illisible et ça
        cassait au premier numéro écrit autrement.
        """
        return [
            {'texte': t, 'href': t.replace(' ', '').replace('.', '').replace('-', '')}
            for t in (self.telephone, self.telephone_secondaire) if t
        ]


class ExternalArticle(models.Model):
    """Article moissonné dans le flux RSS d'un syndicat hébergé ailleurs.

    Les syndicats à `external_url` — le STAA, le TAS — n'ont aucune
    `ArticlePage` chez nous. Le cartouche « Les nouvelles du réseau » de
    l'accueil, qui pioche dans `ArticlePage`, les ignorait donc
    structurellement, alors que c'est le seul endroit de l'accueil où les
    sous-sites s'expriment : partir vivre ailleurs revenait à disparaître du
    réseau.

    On copie ici le strict minimum pour les afficher — un titre, un lien, une
    date — et surtout pas sous forme de page Wagtail : le contenu ne nous
    appartient pas, il n'a rien à faire dans l'arbre des pages, la recherche,
    le sitemap ni l'interface de rédaction. Le remplissage est le fait de la
    commande `sync_flux_reseau`, jamais du rendu d'une page.
    """

    section = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='external_articles',
        verbose_name='Syndicat',
    )
    guid = models.CharField(
        max_length=500,
        help_text="Identifiant de l'entrée dans le flux : ce qui distingue un "
                  "article republié d'un nouvel article.",
    )
    title = models.CharField(max_length=500, verbose_name='Titre')
    url = models.URLField(max_length=500, verbose_name='Lien')
    published_at = models.DateTimeField(verbose_name='Date de publication')
    fetched_at = models.DateTimeField(auto_now=True)

    # Le gabarit du réseau distingue les articles d'ici de ceux d'ailleurs.
    is_external = True

    class Meta:
        unique_together = ('section', 'guid')
        ordering = ['-published_at']
        verbose_name = "Article d'un site externe"
        verbose_name_plural = "Articles des sites externes"

    def __str__(self):
        return f'{self.title} ({self.section.title})'

    # -- Interface commune avec ArticlePage, pour le tour de table du réseau --

    @property
    def section_slug(self):
        return self.section.slug

    def get_absolute_url(self):
        return self.url


class FicheSyndicat(models.Model):
    """Une carte de la page « Nos syndicats et structures ».

    Les treize cartes vivaient dans un unique bloc HTML de 9 800 caractères,
    feuille de style comprise : ajouter un champ de syndicalisation supposait
    de recopier un `<a>` et ses quatre `<div>` imbriqués, au milieu du CSS.
    Trois syndicats existants (STAA, TAS, Numérique) manquaient d'ailleurs à
    l'appel, faute d'oser y toucher — le même symptôme que les permanences
    juridiques avant leur refonte (cf. `Permanence`).

    La cible du lien est une clé étrangère plutôt qu'un chemin écrit à la
    main : onze cartes pointent vers une catégorie, et le réimport des
    catégories WordPress prévu au lancement réécrira les slugs. Onze
    `/categorie/<slug>/` en dur deviendraient onze liens morts silencieux.
    """

    site = models.ForeignKey(
        'cms.SectionPage',
        on_delete=models.CASCADE,
        related_name='fiches_syndicats',
        null=True, blank=True,
        verbose_name='Site propriétaire',
        help_text="Le site dont c'est l'annuaire. La confédération, sauf "
                  "si un syndicat veut le sien.",
    )
    titre = models.CharField(
        max_length=120,
        help_text="Le nom du champ de syndicalisation, ex. « Nettoyage ».",
    )
    description = models.CharField(
        max_length=300, blank=True,
        help_text="Une ligne pour dire ce que le champ recouvre, ex. "
                  "« Hôtels, restaurants, tourisme… ».",
    )
    image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name='Visuel',
        help_text="L'affiche est montrée entière, jamais recadrée.",
    )
    image_url = models.CharField(
        max_length=500, blank=True,
        verbose_name='Visuel hérité',
        help_text="Chemin d'un visuel de l'ancien site, utilisé faute "
                  "d'image ci-dessus. Renseigné par l'import, à ne pas "
                  "saisir à la main.",
    )

    # -- Les trois cibles possibles du lien, dans l'ordre de priorité --
    categorie = models.ForeignKey(
        'cms.CmsCategory',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='fiches_syndicats',
        verbose_name='Catégorie',
        help_text="La carte mène à cette rubrique du site.",
    )
    site_cible = models.ForeignKey(
        'cms.SectionPage',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='fiches_pointant_ici',
        verbose_name='Syndicat',
        help_text="La carte mène à l'accueil de ce syndicat.",
    )
    url = models.CharField(
        max_length=500, blank=True,
        verbose_name='Autre adresse',
        help_text="À défaut de catégorie ou de syndicat : une adresse libre.",
    )

    order = models.PositiveIntegerField(
        default=0, verbose_name='Ordre',
        help_text="Les plus petits nombres s'affichent en premier.",
    )
    is_active = models.BooleanField(default=True, verbose_name='Affichée')

    class Meta:
        verbose_name = 'Fiche syndicat'
        verbose_name_plural = 'Fiches syndicats'
        ordering = ['order', 'titre']

    def __str__(self):
        return self.titre

    def clean(self):
        from django.core.exceptions import ValidationError
        if not (self.categorie_id or self.site_cible_id or self.url):
            raise ValidationError(
                "Une carte sans destination ne mène nulle part : choisissez "
                "une catégorie, un syndicat, ou saisissez une adresse."
            )

    def get_lien(self):
        """L'adresse de la carte, la première cible renseignée l'emportant."""
        if self.categorie_id:
            return reverse('content:category_detail',
                           kwargs={'slug': self.categorie.slug})
        if self.site_cible_id:
            # `get_absolute_url()` sait déjà router vers un domaine autonome
            # ou vers le site propre d'un syndicat hébergé ailleurs.
            return self.site_cible.get_absolute_url()
        return self.url

    @property
    def visuel_url(self):
        """L'image Wagtail, à défaut le visuel hérité de l'ancien site."""
        if self.image_id:
            return self.image.file.url
        return self.image_url or ''
