from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


from django.views.generic import RedirectView, TemplateView
from content.sitemaps import sitemap_view
from content import views as _vues_contenu
from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

urlpatterns = [
    path('cms/', include(wagtailadmin_urls)),
    path('documents/', include(wagtaildocs_urls)),
    path('redac/', RedirectView.as_view(url='/cms/', permanent=True)),
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap_view, name='sitemap'),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt', content_type='text/plain'
    )),
    path('favicon.ico', RedirectView.as_view(
        url='/static/image/logocntso.png', permanent=True
    )),
    # La vue vit dans content.views : elle lit la fiche du syndicat et le
    # réglage ADHESION_USE_NEW_APP, ce que l'ancienne redirection en dur
    # ignorait — d'où sept boutons « Adhérer » sur huit en 404 (02/09/2026).
    path('adherer/<slug:site_slug>/', _vues_contenu.adherer, name='adherer'),
    path('', include('content.urls')),
    path('', include(wagtail_urls)),  # Wagtail page serving (en dernier)
]

# Servir les fichiers media — doit être déclaré avant content.urls pour ne pas
# être intercepté par le pattern <slug:site_slug>/
urlpatterns = static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + urlpatterns
