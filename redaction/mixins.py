from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect


class RedacLoginRequiredMixin(LoginRequiredMixin):
    login_url = '/redac/login/'


class ChefRequiredMixin(RedacLoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('/redac/login/')
        return redirect('redaction:dashboard')


class SuperuserRequiredMixin(RedacLoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('/redac/login/')
        return redirect('redaction:dashboard')
