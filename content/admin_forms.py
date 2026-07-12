"""
Formulaires utilisateur de l'admin Wagtail (/cms/users/).

Ajoute un champ « Syndicat » aux formulaires de création/édition :
en coulisses il crée ou met à jour la fiche Author liée (Author.site),
qui porte le cloisonnement par site des rédacteurs. Plus besoin de
passer par le menu Auteurs pour rattacher un compte à un syndicat.
"""
from django import forms
from wagtail.users.forms import UserCreationForm, UserEditForm


class SyndicatFormMixin(forms.Form):
    syndicat = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Syndicat',
        help_text="Rattache ce compte à un syndicat : un rédacteur ne voit "
                  "que le contenu de ce site dans le CMS.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from cms.models import SectionPage
        self.fields['syndicat'].queryset = SectionPage.objects.order_by('title')
        if getattr(self.instance, 'pk', None):
            profile = getattr(self.instance, 'author_profile', None)
            if profile is not None:
                self.fields['syndicat'].initial = profile.site_id

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self._sync_author_profile(user)
        return user

    def _sync_author_profile(self, user):
        from .models import Author
        site = self.cleaned_data.get('syndicat')
        profile = Author.objects.filter(user=user).first()
        if profile is None:
            if site is None:
                return
            # Réutilise une éventuelle fiche importée de WordPress (username unique)
            profile = Author.objects.filter(username=user.username, user__isnull=True).first()
            if profile is None:
                profile = Author(username=user.username)
            profile.user = user
        profile.site = site
        if not profile.email:
            profile.email = user.email or ''
        if not profile.first_name:
            profile.first_name = user.first_name or ''
        if not profile.last_name:
            profile.last_name = user.last_name or ''
        if not profile.display_name:
            profile.display_name = user.get_full_name() or user.username
        profile.save()


class SyndicatUserCreationForm(SyndicatFormMixin, UserCreationForm):
    pass


class SyndicatUserEditForm(SyndicatFormMixin, UserEditForm):
    pass
