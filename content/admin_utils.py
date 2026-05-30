"""Utilitaires partagés pour les vues d'administration."""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect


def get_current_site_for_view(request):
    """Retourne le SectionPage courant selon le rôle et la session."""
    from cms.models import SectionPage
    user = request.user
    is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
    if is_chef:
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
        user = self.request.user
        return user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('/cms/')
        return redirect('/cms/')
