from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from content.sitemaps import ArticleSitemap, PageSitemap, CategorySitemap, SiteSitemap

sitemaps = {
    'articles': ArticleSitemap,
    'pages': PageSitemap,
    'categories': CategorySitemap,
    'sites': SiteSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('redac/', include('redaction.urls')),
    path('', include('content.urls')),
]

# Servir les fichiers media en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
