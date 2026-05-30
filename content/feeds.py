from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed
from cms.models import ArticlePage, CmsCategory, SectionPage


class LatestArticlesFeed(Feed):
    """Flux RSS des derniers articles du site principal"""
    title = "CNT-SO - Derniers articles"
    link = "/"
    description = "Les dernières actualités de la CNT-SO"
    feed_type = Rss201rev2Feed

    def items(self):
        return (ArticlePage.objects.live()
                .filter(section_slug='principal')
                .order_by('-publication_date', '-first_published_at')[:20])

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at

    def item_author_name(self, item):
        return item.author_name or (str(item.author_user) if item.author_user else "CNT-SO")


class SiteArticlesFeed(Feed):
    """Flux RSS des articles d'un sous-site"""
    feed_type = Rss201rev2Feed

    def get_object(self, request, site_slug):
        return get_object_or_404(SectionPage, slug=site_slug)

    def title(self, obj):
        return f"{obj.name} - Derniers articles"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return f"Les dernières actualités de {obj.name}"

    def items(self, obj):
        return (ArticlePage.objects.live()
                .filter(section_slug=obj.slug)
                .order_by('-publication_date', '-first_published_at')[:20])

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at


class CategoryFeed(Feed):
    """Flux RSS des articles d'une catégorie"""
    feed_type = Rss201rev2Feed

    def get_object(self, request, slug):
        category = CmsCategory.objects.filter(slug=slug, section_slug='principal').first()
        if not category:
            category = get_object_or_404(CmsCategory, slug=slug)
        return category

    def title(self, obj):
        return f"CNT-SO - {obj.name}"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return f"Articles de la catégorie {obj.name}"

    def items(self, obj):
        return (ArticlePage.objects.live()
                .filter(cms_categories=obj)
                .order_by('-publication_date', '-first_published_at')[:20])

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published_at
