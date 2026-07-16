"""Utilitaires partagés pour les vues d'administration."""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect


def is_chef(user):
    """Superuser ou membre du groupe redacteur_en_chef."""
    return user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()


def get_current_site_for_view(request):
    """Retourne le SectionPage courant selon le rôle et la session.

    Délègue au résolveur unique cms.site_context.get_current_site (session
    pour les chefs, groupe par section ou Author.site pour les rédacteurs) —
    ce module en réimplémentait une copie qui ignorait les groupes par section.
    """
    from cms.site_context import get_current_site
    return get_current_site(request)


class WagtailLoginRequiredMixin(LoginRequiredMixin):
    login_url = '/cms/'


class WagtailChefRequiredMixin(WagtailLoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_chef(self.request.user)

    def handle_no_permission(self):
        # raise_exception = True sur les vues AJAX/JSON : 403 direct plutôt
        # qu'une redirection HTML qu'un fetch suivrait comme un succès
        # (lever PermissionDenied ne suffit pas : le wrapper admin de Wagtail
        # la transformerait en redirection vers /cms/)
        if self.raise_exception and self.request.user.is_authenticated:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
        return redirect('/cms/')


class WagtailSyndicatRequiredMixin(WagtailChefRequiredMixin):
    """Chef confédéral OU membre d'un syndicat (site résolu par groupe/Author).

    Pour les outils que chaque syndicat gère en autonomie (contact, newsletter,
    abonnés — décision 2026-07-16) : la vue DOIT ensuite scoper ses données par
    get_current_site_for_view, jamais servir cross-site à un non-chef."""

    def test_func(self):
        if is_chef(self.request.user):
            return True
        return get_current_site_for_view(self.request) is not None
