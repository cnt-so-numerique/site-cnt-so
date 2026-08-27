from django.contrib.sitemaps import Sitemap
from cms.models import ArticlePage, CmsCategory, ContentPage, SectionPage


def _chemin(url):
    """Ramène une URL à un chemin nu, pour Django qui la préfixe lui-même.

    `Sitemap.location()` doit rendre un CHEMIN : le cadriciel y colle
    `protocole://hôte`. Or `get_absolute_url()` rend une URL absolue dès qu'une
    section a son propre domaine, et pour le site principal depuis qu'il passe
    par `url_site_principal()`. Résultat, servi en production le 27/08/2026 :

        https://newsite.cnt-so.orghttps://newsite.cnt-so.org/article/…

    **725 des 866 adresses du sitemap étaient malformées — 83 %.** Personne ne
    l'avait vu parce qu'un sitemap ne se lit pas à l'œil et qu'aucun test ne
    regardait ce qu'il contenait vraiment. Les sitemaps par domaine, écrits plus
    tard, faisaient déjà ce découpage chacun de leur côté : c'est la même
    normalisation, désormais à un seul endroit.
    """
    if url and url.startswith(('http://', 'https://')):
        reste = url.split('/', 3)
        return '/' + (reste[3] if len(reste) > 3 else '')
    return url or '/'


class ArticleSitemap(Sitemap):
    """Sitemap pour les articles"""
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return ArticlePage.objects.live()

    def lastmod(self, obj):
        return obj.last_published_at or obj.publication_date or obj.first_published_at

    def location(self, obj):
        return _chemin(obj.get_absolute_url())


class PageSitemap(Sitemap):
    """Sitemap pour les pages statiques"""
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return ContentPage.objects.live()

    def lastmod(self, obj):
        return obj.last_published_at or obj.first_published_at

    def location(self, obj):
        return _chemin(obj.get_absolute_url())


class CategorySitemap(Sitemap):
    """Sitemap pour les catégories"""
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return CmsCategory.objects.all()

    def location(self, obj):
        return _chemin(obj.get_absolute_url())


class SiteSitemap(Sitemap):
    """Sitemap pour les sous-sites"""
    changefreq = "daily"
    priority = 0.7

    def items(self):
        # Les sections à `external_url` (syndicats hébergés ailleurs, comme le
        # STAA sur staa-cnt-so.org) ont un `get_absolute_url()` pointant vers un
        # AUTRE domaine : les lister publierait l'URL d'autrui dans notre
        # sitemap, ce que les moteurs ignorent au mieux. Leur propre site
        # déclare ses pages.
        return SectionPage.objects.filter(live=True).filter(external_url='')

    def location(self, obj):
        return _chemin(obj.get_absolute_url())


# ── Multi-domaines ────────────────────────────────────────────────────────────
# Sur le site principal, le contenu des sections à domaine autonome est exclu
# (il vit sur son propre sitemap) ; sur un domaine de fédération, le sitemap ne
# liste que le contenu de la section, en chemins nus (Django préfixe par l'hôte).

def _slugs_hors_sitemap_principal():
    """Slugs dont le contenu n'a rien à faire dans le sitemap du site principal.

    Deux cas, et le second manquait :

    1. **Section à domaine autonome** — son contenu vit sur son propre sitemap.
    2. **Section dépubliée** — `get_section_or_404` ferme le site d'un syndicat
       dépublié, mais le sitemap principal continuait d'annoncer ses articles.
       Le filtre `live=True` d'ici ne servait qu'à décider qui « possède » un
       domaine ; il avait pour effet de **réintroduire** le contenu des sections
       dépubliées dans le sitemap principal. Rhône-Alpes, dépublié, y plaçait
       encore 32 articles le 27/08/2026.
    """
    slugs = set()
    concernees = SectionPage.objects.exclude(custom_domain='') | \
        SectionPage.objects.filter(live=False)
    for s in concernees.distinct():
        slugs.add(s.slug)
        if s.legacy_site_slug:
            slugs.add(s.legacy_site_slug)
    return slugs


class MainArticleSitemap(ArticleSitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_slugs_hors_sitemap_principal())


class MainPageSitemap(PageSitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_slugs_hors_sitemap_principal())


class MainCategorySitemap(CategorySitemap):
    def items(self):
        return super().items().exclude(section_slug__in=_slugs_hors_sitemap_principal())


class MainSiteSitemap(SiteSitemap):
    def items(self):
        return super().items().filter(custom_domain='')


class SectionArticleSitemap(Sitemap):
    protocol = 'https'
    changefreq = "weekly"
    priority = 0.8

    def __init__(self, section):
        self.slugs = section.slugs_contenu

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
        self.slugs = section.slugs_contenu

    def items(self):
        return ContentPage.objects.live().filter(section_slug__in=self.slugs)

    def lastmod(self, obj):
        return obj.last_published_at or obj.first_published_at

    def location(self, obj):
        # URL canonique de la page Wagtail — l'ancienne forme /page/<slug>/
        # 301 vers elle. `_chemin` la ramène au chemin nu.
        return _chemin(obj.get_absolute_url())


class SectionCategorySitemap(Sitemap):
    protocol = 'https'
    changefreq = "weekly"
    priority = 0.5

    def __init__(self, section):
        self.slugs = section.slugs_contenu

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
