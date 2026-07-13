from django.contrib.sitemaps import Sitemap
from cms.models import ArticlePage, CmsCategory, ContentPage, SectionPage


class ArticleSitemap(Sitemap):
    """Sitemap pour les articles"""
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return ArticlePage.objects.live()

    def lastmod(self, obj):
        return obj.last_published_at or obj.publication_date or obj.first_published_at

    def location(self, obj):
        return obj.get_absolute_url()


class PageSitemap(Sitemap):
    """Sitemap pour les pages statiques"""
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return ContentPage.objects.live()

    def lastmod(self, obj):
        return obj.last_published_at or obj.first_published_at

    def location(self, obj):
        return obj.get_absolute_url()


class CategorySitemap(Sitemap):
    """Sitemap pour les catégories"""
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return CmsCategory.objects.all()

    def location(self, obj):
        return obj.get_absolute_url()


class SiteSitemap(Sitemap):
    """Sitemap pour les sous-sites"""
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return SectionPage.objects.filter(live=True)

    def location(self, obj):
        return obj.get_absolute_url()


# ── Multi-domaines ────────────────────────────────────────────────────────────
# Sur le site principal, le contenu des sections à domaine autonome est exclu
# (il vit sur son propre sitemap) ; sur un domaine de fédération, le sitemap ne
# liste que le contenu de la section, en chemins nus (Django préfixe par l'hôte).

def _domain_section_slugs():
    """Slugs (et legacy) des sections servies sur leur propre domaine."""
    slugs = set()
    for s in SectionPage.objects.exclude(custom_domain='').filter(live=True):
        slugs.add(s.slug)
        if s.legacy_site_slug:
            slugs.add(s.legacy_site_slug)
    return slugs


class MainArticleSitemap(ArticleSitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_domain_section_slugs())


class MainPageSitemap(PageSitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_domain_section_slugs())


class MainCategorySitemap(CategorySitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_domain_section_slugs())


class MainSiteSitemap(SiteSitemap):
    def items(self):
        return super().items().filter(custom_domain='')


class SectionArticleSitemap(Sitemap):
    protocol = 'https'
    changefreq = "weekly"
    priority = 0.8

    def __init__(self, section):
        self.slugs = {section.slug, section.legacy_site_slug or section.slug}

    def items(self):
        return ArticlePage.objects.live().filter(section_slug__in=self.slugs)

    def lastmod(self, obj):
        return obj.last_published_at or obj.publication_date or obj.first_published_at

    def location(self, obj):
        return f'/article/{obj.slug}/'


class SectionPageSitemap(Sitemap):
    protocol = 'https'
    changefreq = "monthly"
    priority = 0.6

    def __init__(self, section):
        self.slugs = {section.slug, section.legacy_site_slug or section.slug}

    def items(self):
        return ContentPage.objects.live().filter(section_slug__in=self.slugs)

    def lastmod(self, obj):
        return obj.last_published_at or obj.first_published_at

    def location(self, obj):
        return f'/page/{obj.slug}/'


class SectionCategorySitemap(Sitemap):
    protocol = 'https'
    changefreq = "weekly"
    priority = 0.5

    def __init__(self, section):
        self.slugs = {section.slug, section.legacy_site_slug or section.slug}

    def items(self):
        return CmsCategory.objects.filter(section_slug__in=self.slugs)

    def location(self, obj):
        return f'/categorie/{obj.slug}/'


class SectionStaticSitemap(Sitemap):
    protocol = 'https'
    """Pages fixes d'un sous-site à domaine autonome."""
    changefreq = "daily"
    priority = 0.7

    def __init__(self, section):
        self.section = section

    def items(self):
        return ['/', '/contact/', '/rejoindre/', '/ressources/', '/agenda/']

    def location(self, obj):
        return obj


def sitemap_view(request):
    """Sitemap adapté à l'hôte : section seule sur un domaine de fédération,
    tout le reste (sections à domaine exclues) sur le site principal."""
    from django.contrib.sitemaps.views import sitemap as django_sitemap
    section = getattr(request, 'section_page', None)
    if section is not None:
        maps = {
            'static': SectionStaticSitemap(section),
            'articles': SectionArticleSitemap(section),
            'categories': SectionCategorySitemap(section),
            'pages': SectionPageSitemap(section),
        }
    else:
        maps = {
            'articles': MainArticleSitemap,
            'pages': MainPageSitemap,
            'categories': MainCategorySitemap,
            'sites': MainSiteSitemap,
        }
    return django_sitemap(request, sitemaps=maps)
