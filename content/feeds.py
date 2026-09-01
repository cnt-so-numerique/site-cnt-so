from django.contrib.syndication.views import Feed
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
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
        return item.author_name or "CNT-SO"


class SiteArticlesFeed(Feed):
    """Flux RSS des articles d'un sous-site"""
    feed_type = Rss201rev2Feed

    def get_object(self, request, site_slug):
        # `live=True` : sans lui, le flux d'un syndicat dépublié continuait de
        # diffuser ses articles, alors que toutes ses pages renvoyaient un 404.
        # Un agrégateur ou un lecteur RSS aurait gardé une fenêtre ouverte sur
        # un site fermé (relevé le 16/08/2026).
        obj = SectionPage.objects.filter(
            Q(slug=site_slug) | Q(legacy_site_slug=site_slug), live=True
        ).first()
        if obj is None:
            raise Http404
        return obj

    def title(self, obj):
        return f"{obj.name} - Derniers articles"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return f"Les dernières actualités de {obj.name}"

    def items(self, obj):
        return (ArticlePage.objects.live()
                .filter(section_slug__in=obj.slugs_contenu)
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

    def __call__(self, request, *args, **kwargs):
        """Même règle que la page : la conf ne diffuse que ses catégories.

        `get_object_or_404(CmsCategory, slug=slug)` levait en plus
        `MultipleObjectsReturned` — donc un **500** — sur les sept slugs portés
        par deux syndicats. Vérifié en production le 01/09/2026 :
        `/categorie/actualites-luttes/feed/`, `/btp/feed/`, `/stucs/feed/`,
        `/liens/feed/` et `/restauration/feed/` renvoyaient tous 500.
        """
        slug = kwargs.get('slug')
        if slug and not CmsCategory.objects.filter(
                slug=slug, section_slug='principal').exists():
            ailleurs = CmsCategory.dun_syndicat_publie(slug)
            if ailleurs is None:
                raise Http404(f"Aucune catégorie « {slug} » à la confédération")
            return redirect(f'{ailleurs.get_absolute_url()}feed/')
        return super().__call__(request, *args, **kwargs)

    def get_object(self, request, slug):
        category = CmsCategory.objects.filter(
            slug=slug, section_slug='principal').first()
        if category is None:
            raise Http404
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


class SiteCategoryFeed(Feed):
    """Flux RSS d'une catégorie d'un sous-site.

    Il manquait : la page existait (`site_category_detail`) mais pas son flux,
    si bien qu'une catégorie de syndicat n'avait d'adresse RSS que sous la
    confédération — celle-là même qui vient de cesser de la servir. Ajouté le
    01/09/2026 avec la redirection de `CategoryFeed`, qui pointe ici.
    """
    feed_type = Rss201rev2Feed

    def get_object(self, request, site_slug, slug):
        # `live=True` comme pour `SiteArticlesFeed` : le flux d'un syndicat
        # dépublié ne doit pas rester une fenêtre ouverte sur un site fermé.
        site = SectionPage.objects.filter(
            Q(slug=site_slug) | Q(legacy_site_slug=site_slug), live=True
        ).first()
        if site is None:
            raise Http404
        categorie = CmsCategory.objects.filter(
            slug=slug, section_slug__in=site.slugs_contenu).first()
        if categorie is None:
            raise Http404
        return categorie

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
        return item.excerpt or ''

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.publication_date or item.first_published_at
