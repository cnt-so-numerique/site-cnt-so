from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed
from .models import Article, Site, Category


class LatestArticlesFeed(Feed):
    """Flux RSS des derniers articles du site principal"""
    title = "CNT-SO - Derniers articles"
    link = "/"
    description = "Les dernières actualités de la CNT-SO"
    feed_type = Rss201rev2Feed

    def items(self):
        return Article.objects.filter(
            site__slug='principal',
            status='publish'
        ).order_by('-published_at')[:20]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or item.content[:500]

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at

    def item_author_name(self, item):
        return str(item.author) if item.author else "CNT-SO"


class SiteArticlesFeed(Feed):
    """Flux RSS des articles d'un sous-site"""
    feed_type = Rss201rev2Feed

    def get_object(self, request, site_slug):
        return get_object_or_404(Site, slug=site_slug)

    def title(self, obj):
        return f"{obj.name} - Derniers articles"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return f"Les dernières actualités de {obj.name}"

    def items(self, obj):
        return Article.objects.filter(
            site=obj,
            status='publish'
        ).order_by('-published_at')[:20]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or item.content[:500]

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at


class CategoryFeed(Feed):
    """Flux RSS des articles d'une catégorie"""
    feed_type = Rss201rev2Feed

    def get_object(self, request, slug):
        category = Category.objects.filter(slug=slug, site__slug='principal').first()
        if not category:
            category = get_object_or_404(Category, slug=slug)
        return category

    def title(self, obj):
        return f"CNT-SO - {obj.name}"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return f"Articles de la catégorie {obj.name}"

    def items(self, obj):
        return Article.objects.filter(
            categories=obj,
            status='publish'
        ).order_by('-published_at')[:20]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or item.content[:500]

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at
