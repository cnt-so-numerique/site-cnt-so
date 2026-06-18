from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


def _adhesion_redirect(request, site_slug):
    base_url = getattr(settings, 'ADHESION_BASE_URL', 'https://adhesion.cnt-so.org')
    return redirect(f"{base_url}/adherer/{site_slug}/")
from django.contrib.sitemaps.views import sitemap
from django.views.generic import RedirectView, TemplateView
from content.sitemaps import ArticleSitemap, PageSitemap, CategorySitemap, SiteSitemap
from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

sitemaps = {
    'articles': ArticleSitemap,
    'pages': PageSitemap,
    'categories': CategorySitemap,
    'sites': SiteSitemap,
}

urlpatterns = [
    path('cms/', include(wagtailadmin_urls)),
    path('documents/', include(wagtaildocs_urls)),
    path('redac/', RedirectView.as_view(url='/cms/', permanent=True)),
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt', content_type='text/plain'
    )),
    path('favicon.ico', RedirectView.as_view(
        url='/static/image/logocntso.png', permanent=True
    )),
    path('adherer/<slug:site_slug>/', _adhesion_redirect),
    path('', include('content.urls')),
    path('', include(wagtail_urls)),  # Wagtail page serving (en dernier)
]

# Servir les fichiers media — doit être déclaré avant content.urls pour ne pas
# être intercepté par le pattern <slug:site_slug>/
urlpatterns = static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + urlpatterns
