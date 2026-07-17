"""
Formulaires utilisateur de l'admin Wagtail (/cms/users/).

Ajoute un champ « Syndicat » aux formulaires de création/édition :
en coulisses il crée ou met à jour la fiche Author liée (Author.site) ET
l'appartenance au groupe redacteur_<slug> — c'est le groupe qui porte les
permissions réelles (pages, collections de médias) depuis le chantier
autonomie. Plus besoin de passer par le menu Groupes pour rattacher un
compte à un syndicat.

La case « Administrateur » (is_superuser) n'est proposée qu'aux superusers :
un redacteur_en_chef gestionnaire de comptes ne peut pas la cocher.
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
        self._request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        if 'is_superuser' in self.fields and (
                self._request_user is None
                or not self._request_user.is_superuser):
            del self.fields['is_superuser']
        from cms.models import SectionPage
        self.fields['syndicat'].queryset = SectionPage.objects.order_by('title')
        if getattr(self.instance, 'pk', None):
            self.fields['syndicat'].initial = self._current_site_of(self.instance)

    @staticmethod
    def _current_site_of(user):
        """Syndicat actuel du compte : le groupe redacteur_<slug> d'abord
        (même ordre de priorité que cms.site_context), sinon Author.site."""
        from cms.site_context import get_group_scoped_site
        site = get_group_scoped_site(user)
        if site is not None:
            return site.pk
        profile = getattr(user, 'author_profile', None)
        return profile.site_id if profile is not None else None

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self._sync_author_profile(user)
            self._sync_section_group(user)
        return user

    def _sync_section_group(self, user):
        """Aligne l'appartenance aux groupes redacteur_<slug> sur le champ
        Syndicat (un seul syndicat par compte, cf. get_group_scoped_site).
        S'exécute après le save m2m : il corrige aussi un cochage manuel
        incohérent dans la liste des groupes."""
        from django.contrib.auth.models import Group
        site = self.cleaned_data.get('syndicat')
        wanted = None
        if site is not None:
            slug = site.legacy_site_slug or site.slug
            # Groupe absent = setup_cms_permissions pas encore lancé pour ce
            # syndicat ; Author.site reste posé, rien à faire de plus ici.
            wanted = Group.objects.filter(name=f'redacteur_{slug}').first()
        stale = user.groups.filter(name__startswith='redacteur_').exclude(
            name='redacteur_en_chef')
        if wanted is not None:
            stale = stale.exclude(pk=wanted.pk)
        for group in stale:
            user.groups.remove(group)
        if wanted is not None:
            user.groups.add(wanted)

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
