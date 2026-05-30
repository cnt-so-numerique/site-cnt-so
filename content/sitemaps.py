from django.contrib.sitemaps import Sitemap
from .models import Page, Category
from cms.models import ArticlePage, SectionPage


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
    """Sitemap pour les pages"""
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return Page.objects.filter(status='publish').select_related('site')

    def lastmod(self, obj):
        return obj.updated_at or obj.published_at

    def location(self, obj):
        return obj.get_absolute_url()


class CategorySitemap(Sitemap):
    """Sitemap pour les catégories"""
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return Category.objects.all().select_related('site')

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
