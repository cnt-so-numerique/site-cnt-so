import base64
import hmac
from django.conf import settings
from django.http import HttpResponse


class BasicAuthMiddleware:
    """
    Middleware HTTP Basic Auth pour staging.
    Activé uniquement si BASIC_AUTH_PASSWORD est défini dans les settings.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        password = getattr(settings, 'BASIC_AUTH_PASSWORD', None)
        if not password:
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Basic '):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                _, provided_password = decoded.split(':', 1)
                if hmac.compare_digest(provided_password, password):
                    return self.get_response(request)
            except Exception:
                pass

        response = HttpResponse('Accès restreint', status=401)
        response['WWW-Authenticate'] = 'Basic realm="CNT-SO Staging"'
        return response


class SectionDomainMiddleware:
    """
    Sert les sous-sites sur leur domaine autonome (SectionPage.custom_domain).

    Sur un hôte reconnu :
    - `/cms/`, `/admin/` → redirection vers l'admin central (une seule interface)
    - `/<slug>/...` (son propre préfixe) → 301 vers l'URL sans préfixe
      (l'URL canonique du domaine autonome n'a pas de préfixe)
    - tout chemin résolvable comme contenu de la section une fois préfixé
      (`/contact/` ≡ `/stucs/contact/`) est réécrit en interne
    - tout le reste (contenu d'autres sections, pages globales, confirmations
      newsletter…) → 301 vers le site principal : un domaine de fédération ne
      sert QUE le contenu de sa section
    - les redirections ne s'appliquent qu'aux GET/HEAD — un POST (formulaire)
      n'est jamais redirigé, il est servi là où il arrive

    Hôte inconnu ou custom_domain vide partout : strictement aucun effet.
    """

    EXEMPT_PREFIXES = ('/media/', '/static/', '/documents/', '/sitemap.xml',
                       '/robots.txt', '/favicon.ico')
    ADMIN_PREFIXES = ('/cms/', '/cms', '/admin/', '/admin')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.section_page = None
        host = request.get_host().split(':')[0].lower()
        section = self._resolve_section(host)
        if section is None:
            # Hôte principal : le chemin d'une section à domaine autonome
            # redirige vers ce domaine (URL canonique unique)
            if request.method in ('GET', 'HEAD'):
                path = request.path_info
                seg = path.lstrip('/').split('/', 1)[0]
                domain = self._domain_map().get(seg) if seg else None
                if domain:
                    from django.http import HttpResponsePermanentRedirect
                    rest = path[len(seg) + 1:] or '/'
                    qs = request.META.get('QUERY_STRING', '')
                    return HttpResponsePermanentRedirect(
                        f'https://{domain}{rest}' + (f'?{qs}' if qs else ''))
            return self.get_response(request)

        request.section_page = section
        slug = section.legacy_site_slug or section.slug
        path = request.path_info
        safe_method = request.method in ('GET', 'HEAD')

        if path.startswith(self.ADMIN_PREFIXES):
            from django.http import HttpResponsePermanentRedirect
            return HttpResponsePermanentRedirect(f'{self._main_base()}{path}')

        if path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)

        if path == f'/{slug}/' or path.startswith(f'/{slug}/'):
            if safe_method:
                from django.http import HttpResponsePermanentRedirect
                stripped = path[len(slug) + 1:] or '/'
                qs = request.META.get('QUERY_STRING', '')
                return HttpResponsePermanentRedirect(stripped + (f'?{qs}' if qs else ''))
            # POST sur l'URL préfixée (action de formulaire) : servie telle quelle
            return self.get_response(request)

        from django.urls import resolve, Resolver404
        prefixed = f'/{slug}{path}'
        try:
            resolve(prefixed, urlconf='content.urls')
        except Resolver404:
            # Pas un contenu de la section → renvoi vers le site principal
            if safe_method:
                from django.http import HttpResponsePermanentRedirect
                qs = request.META.get('QUERY_STRING', '')
                return HttpResponsePermanentRedirect(
                    f'{self._main_base()}{path}' + (f'?{qs}' if qs else ''))
        else:
            request.path_info = prefixed

        return self.get_response(request)

    @staticmethod
    def _main_base():
        return getattr(settings, 'MAIN_SITE_BASE_URL',
                       getattr(settings, 'WAGTAILADMIN_BASE_URL', 'https://cnt-so.org'))

    @staticmethod
    def _domain_map():
        """{ slug (et legacy_site_slug) → custom_domain } des sections à domaine."""
        from django.core.cache import cache
        mapping = cache.get('section-domain-map')
        if mapping is None:
            from cms.models import SectionPage
            mapping = {}
            for s in SectionPage.objects.exclude(custom_domain='').filter(live=True):
                mapping[s.slug] = s.custom_domain
                if s.legacy_site_slug:
                    mapping[s.legacy_site_slug] = s.custom_domain
            cache.set('section-domain-map', mapping, 60)
        return mapping

    @staticmethod
    def _resolve_section(host):
        if not host:
            return None
        from django.core.cache import cache
        key = f'section-domain:{host}'
        found = cache.get(key)
        if found is None:
            from cms.models import SectionPage
            section = SectionPage.objects.filter(custom_domain=host, live=True).first()
            found = section.pk if section else 0
            cache.set(key, found, 60)
        if not found:
            return None
        from cms.models import SectionPage
        return SectionPage.objects.filter(pk=found).first()
