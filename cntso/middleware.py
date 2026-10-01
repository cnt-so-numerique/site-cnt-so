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


class ContentSecurityPolicyMiddleware:
    """Pose une Content-Security-Policy sur les pages publiques.

    Absente jusqu'ici (relevé au pentest du 08/09/2026). Elle n'est *pas*
    appliquée à l'admin (`/cms/`, `/admin/`) : Wagtail y sert quantité de
    scripts et de styles inline sans nonce, qu'une politique stricte casserait.
    Le périmètre public n'a, lui, qu'un jeu borné d'hôtes externes (hCaptcha,
    Leaflet/unpkg, Google Fonts).

    `script-src`/`style-src` gardent `'unsafe-inline'` : une douzaine de blocs
    inline (JSON-LD, init de carte, boutons de partage…) en dépendent. Le gain
    n'est donc pas de bloquer le script injecté *inline* — l'échappement Django
    s'en charge déjà — mais de fermer les vecteurs qui ne coûtent rien à
    verrouiller : `object-src`, `base-uri`, `frame-ancestors`, `form-action`,
    et le refus de charger un script/style depuis un hôte non listé.

    `frame-src` et `img-src` restent larges (`https:`) à dessein : un rédacteur
    intègre des vidéos (EmbedBlock) et des images d'origine libre ; les brider
    à une liste figée casserait le prochain embed d'un fournisseur non prévu.

    Passer à une politique par nonce (sans `'unsafe-inline'`) suppose d'ajouter
    un nonce à chaque bloc inline — chantier séparé.
    """

    EXEMPT_PREFIXES = ('/cms/', '/cms', '/admin/', '/admin', '/django-admin')

    POLICY = "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://js.hcaptcha.com "
        "https://*.hcaptcha.com https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://*.hcaptcha.com",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self' https://*.hcaptcha.com",
        "frame-src https:",
        "media-src 'self' https:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self'",
        "form-action 'self'",
    ])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(self.EXEMPT_PREFIXES):
            return response
        # Uniquement sur du HTML : inutile (et parfois gênant) sur les images,
        # flux RSS, JSON, fichiers servis…
        ctype = response.get('Content-Type', '')
        if ctype.startswith('text/html') and not response.has_header('Content-Security-Policy'):
            response['Content-Security-Policy'] = self.POLICY
        return response


def _chemin_sur_ce_site(chemin):
    """Ramène un chemin à une adresse qui reste sur ce site.

    Trouvé à l'audit du 17/09/2026. La redirection qui retire le préfixe de
    syndicat renvoyait le reste du chemin tel quel : `/stucs//evil.com/x`
    donnait un **301 vers `//evil.com/x`**, c'est-à-dire une URL
    protocole-relative — le navigateur part sur `https://evil.com`. Et comme
    la redirection est permanente, elle se met en cache chez le visiteur.
    Hameçonnage au départ d'un domaine légitime du syndicat.

    On écrase donc toute suite de barres obliques initiales. La barre inverse
    est traitée de même : plusieurs navigateurs la normalisent en `/`, si bien
    que `/\\evil.com` vaut `//evil.com` pour eux.
    """
    return '/' + (chemin or '').lstrip('/\\')


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
        request.site_en_test = None
        # Prévisualisation : Wagtail bâtit une requête factice à l'URL de la
        # page et la fait traverser toute la chaîne de middlewares
        # (`make_preview_request`). Sur une section à domaine autonome, nos
        # redirections la renvoyaient vers ce domaine — le cadre d'aperçu
        # chargeait alors une page d'une AUTRE origine, que `X-Frame-Options:
        # SAMEORIGIN` refuse d'afficher. Wagtail pose `is_dummy` précisément
        # pour qu'un middleware puisse s'abstenir (constaté le 05/08/2026 :
        # « Firefox ne peut pas ouvrir cette page »).
        if getattr(request, 'is_dummy', False):
            return self.get_response(request)
        host = request.get_host().split(':')[0].lower()
        section = self._resolve_section(host)
        if section is None:
            seg = request.path_info.lstrip('/').split('/', 1)[0]
            en_maintenance = self._maintenance_map().get(seg) if seg else None
            if en_maintenance:
                return self._site_ferme(request, *en_maintenance)
            # Hôte principal : le chemin d'une section à domaine autonome
            # redirige vers ce domaine (URL canonique unique)
            if request.method in ('GET', 'HEAD'):
                path = request.path_info
                domain = self._domain_map().get(seg) if seg else None
                if domain:
                    from django.http import HttpResponsePermanentRedirect
                    rest = path[len(seg) + 1:] or '/'
                    qs = request.META.get('QUERY_STRING', '')
                    return HttpResponsePermanentRedirect(
                        f'https://{domain}{rest}' + (f'?{qs}' if qs else ''))
            return self.get_response(request)

        if not section.live:
            return self._domaine_ferme(request, section)

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
                stripped = _chemin_sur_ce_site(path[len(slug) + 1:] or '/')
                qs = request.META.get('QUERY_STRING', '')
                return HttpResponsePermanentRedirect(stripped + (f'?{qs}' if qs else ''))
            # POST sur l'URL préfixée (action de formulaire) : servie telle quelle
            return self.get_response(request)

        from django.urls import resolve, Resolver404
        prefixed = f'/{slug}{path}'
        try:
            resolve(prefixed, urlconf='content.urls')
        except Resolver404:
            # Pas une URL de content.urls — mais peut-être une page Wagtail
            # de la section (ContentPage…), servie par le catch-all Wagtail.
            if self._is_section_wagtail_page(section, path):
                # Réécriture avec le slug Wagtail réel de la section (le
                # préfixe de content.urls peut être le legacy_site_slug)
                request.path_info = f'/{section.slug}{path}'
            elif safe_method:
                # Pas un contenu de la section → renvoi vers le site principal
                from django.http import HttpResponsePermanentRedirect
                qs = request.META.get('QUERY_STRING', '')
                return HttpResponsePermanentRedirect(
                    f'{self._main_base()}{path}' + (f'?{qs}' if qs else ''))
        else:
            request.path_info = prefixed

        return self.get_response(request)

    def _domaine_ferme(self, request, section):
        """Domaine d'une section dépubliée : tout renvoie à l'accueil confédéral.

        Sans cela l'hôte n'était plus reconnu et retombait sur « hôte
        principal » : `stucs.cnt-so.org/` servait l'accueil de la conf, et
        `/contact/` son formulaire, sous l'adresse du syndicat fermé (mesuré le
        28/09/2026 en dépubliant le STUCS). Redirection temporaire (302) et non
        permanente : republier la section doit rouvrir le domaine, ce qu'un 301
        gardé en cache par les navigateurs empêcherait.
        """
        from django.http import Http404, HttpResponseRedirect
        path = request.path_info
        if path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)
        if path.startswith(self.ADMIN_PREFIXES):
            return HttpResponseRedirect(f'{self._main_base()}{path}')
        en_maintenance = self._maintenance_map().get(
            section.legacy_site_slug or section.slug)
        if en_maintenance:
            return self._page_maintenance(request, *en_maintenance)
        if request.method not in ('GET', 'HEAD'):
            raise Http404('Syndicat dépublié')
        return HttpResponseRedirect(f'{self._main_base()}/')

    def _site_ferme(self, request, titre, slug):
        """`cnt-so.org/<slug>/` d'un syndicat en maintenance.

        Le public voit la page de maintenance ; les comptes qui écrivent ce
        syndicat voient le site lui-même, « en test », pour le reprendre en
        main avant de le rouvrir (demande du STUCS, 01/10/2026). Uniquement
        sur l'hôte principal : la session de /cms/ n'existe pas sur le
        domaine du syndicat.

        Qui regarde n'est connu qu'après `AuthenticationMiddleware`, placé
        APRÈS nous dans MIDDLEWARE : la décision se prend dans `process_view`,
        avant que la vue ne s'exécute (un POST de contact ne doit pas partir).
        Si aucune vue n'est atteinte — chemin non résolu, réponse d'un autre
        middleware — on tranche sur la réponse.
        """
        from django.utils.cache import patch_cache_control
        request._site_ferme = (titre, slug)
        response = self.get_response(request)
        if request._site_ferme is not None:
            refus = self._trancher(request)
            if refus is not None:
                return refus
        if request.site_en_test is not None:
            response['X-Robots-Tag'] = 'noindex, nofollow'
            patch_cache_control(response, private=True, no_store=True)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if getattr(request, '_site_ferme', None) is not None:
            return self._trancher(request)
        return None

    def _trancher(self, request):
        """Page de maintenance, ou None si ce compte voit le site en test
        (posé alors dans `request.site_en_test`, que lit `get_section_or_404`)."""
        titre, slug = request._site_ferme
        request._site_ferme = None
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            from cms.models import SectionPage
            from cms.site_context import peut_voir_site_en_test
            section = SectionPage.objects.filter(slug=slug, live=False).first()
            if section is not None and peut_voir_site_en_test(user, section):
                request.site_en_test = section
                return None
        return self._page_maintenance(request, titre, slug)

    def _page_maintenance(self, request, titre, slug):
        """« Site en maintenance, on revient bientôt » (503 + Retry-After).

        503 plutôt que 200 : les moteurs de recherche gardent les pages du
        syndicat en attendant sa réouverture au lieu d'indexer ce message.

        Le lien « Accès membres » passe par la connexion de /cms/ sur le site
        principal, qui renvoie au site en test (`next`) — directement si
        l'on est déjà connecté.
        """
        from django.template.loader import render_to_string
        from django.http import HttpResponse
        r = HttpResponse(render_to_string('maintenance.html', {
            'titre': titre, 'accueil': f'{self._main_base()}/',
            'acces_membres': f'{self._main_base()}/cms/login/?next=/{slug}/',
        }, request=request), status=503)
        r['Retry-After'] = '86400'
        # Un 503 voulu n'est pas une panne. Sans ce drapeau (celui que
        # `django.utils.log.log_response` consulte), Django le journalise en
        # ERROR et chaque adresse visitée part en alerte : 1 788 courriels
        # du 28 au 30/09/2026, les robots parcourant le site fermé.
        r._has_been_logged = True
        return r

    @staticmethod
    def _maintenance_map():
        """{ slug (et legacy_site_slug) → (titre, slug Wagtail) } des sections
        en test (`SectionPage.en_test`). Le slug Wagtail sert aux adresses :
        seul reconnu par les URL du site.
        """
        from django.core.cache import cache
        mapping = cache.get('section-maintenance-map')
        if mapping is None:
            from cms.models import SectionPage
            mapping = {}
            for s in SectionPage.en_test():
                mapping[s.slug] = (s.title, s.slug)
                if s.legacy_site_slug:
                    mapping[s.legacy_site_slug] = (s.title, s.slug)
            cache.set('section-maintenance-map', mapping, 60)
        return mapping

    @staticmethod
    def _is_section_wagtail_page(section, path):
        """True si `path` correspond à une page Wagtail vivante sous la
        SectionPage (ex. une ContentPage de la section)."""
        candidate = path if path.endswith('/') else f'{path}/'
        from wagtail.models import Page
        return Page.objects.live().filter(
            url_path=f'{section.url_path}{candidate.lstrip("/")}'
        ).exists()

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
            # Sans filtre `live` : un domaine dépublié doit être reconnu pour
            # être fermé (`_domaine_ferme`), pas pris pour l'hôte principal.
            section = SectionPage.objects.filter(custom_domain=host).first()
            found = section.pk if section else 0
            cache.set(key, found, 60)
        if not found:
            return None
        from cms.models import SectionPage
        return SectionPage.objects.filter(pk=found).first()
