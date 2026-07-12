"""Utilitaires partagés pour les vues d'administration."""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect


def is_chef(user):
    """Superuser ou membre du groupe redacteur_en_chef."""
    return user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()


def get_current_site_for_view(request):
    """Retourne le SectionPage courant selon le rôle et la session."""
    from cms.models import SectionPage
    user = request.user
    if is_chef(user):
        site_id = request.session.get('redac_current_site_id')
        if site_id:
            try:
                return SectionPage.objects.get(pk=site_id)
            except SectionPage.DoesNotExist:
                pass
        return None
    author_profile = getattr(user, 'author_profile', None)
    if author_profile:
        return author_profile.site  # FK SectionPage
    return None


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
