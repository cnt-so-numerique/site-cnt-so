"""
Formulaires utilisateur de l'admin Wagtail (/cms/users/).

Ajoute un champ « Syndicats » aux formulaires de création/édition :
en coulisses il crée ou met à jour la fiche Author liée (Author.site, le
premier syndicat) ET l'appartenance aux groupes redacteur_<slug> — c'est le groupe qui porte les
permissions réelles (pages, collections de médias) depuis le chantier
autonomie. Plus besoin de passer par le menu Groupes pour rattacher un
compte à un syndicat.

La case « Administrateur » (is_superuser) n'est proposée qu'aux superusers :
un redacteur_en_chef gestionnaire de comptes ne peut pas la cocher.
"""
from django import forms
from wagtail.users.forms import UserCreationForm, UserEditForm


class SyndicatFormMixin(forms.Form):
    syndicats = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Syndicats',
        help_text="Rattache ce compte à un ou plusieurs syndicats : un "
                  "rédacteur ne voit que le contenu de ces sites dans le CMS "
                  "et passe de l'un à l'autre par le sélecteur.",
    )

    def __init__(self, *args, **kwargs):
        self._request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        if 'is_superuser' in self.fields and (
                self._request_user is None
                or not self._request_user.is_superuser):
            del self.fields['is_superuser']
        from cms.models import SectionPage
        self.fields['syndicats'].queryset = SectionPage.objects.order_by('title')
        # « redacteur » (sans suffixe) est le gabarit dont chaque syndicat copie
        # ses permissions au provisionnement, pas un rôle : il n'a aucun droit
        # d'arbre. Un compte qui n'aurait que lui semblerait configuré et ne
        # pourrait rien publier — on ne le propose donc pas.
        if 'groups' in self.fields:
            self.fields['groups'].queryset = (
                self.fields['groups'].queryset.exclude(name='redacteur'))
        if getattr(self.instance, 'pk', None):
            self.fields['syndicats'].initial = self._current_sites_of(self.instance)

    @staticmethod
    def _current_sites_of(user):
        """Syndicats actuels du compte : ses groupes redacteur_<slug> d'abord
        (même ordre de priorité que cms.site_context), sinon Author.site."""
        from cms.site_context import _sites_du_compte
        return [site.pk for site in _sites_du_compte(user)]

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self._sync_author_profile(user)
            self._sync_section_group(user)
        return user

    def _sync_section_group(self, user):
        """Aligne l'appartenance aux groupes redacteur_<slug> sur le champ
        Syndicats. S'exécute après le save m2m : le champ fait foi, il
        corrige aussi un cochage manuel incohérent dans la liste des groupes."""
        from django.contrib.auth.models import Group
        # Groupe absent = setup_cms_permissions pas encore lancé pour ce
        # syndicat ; Author.site reste posé, rien à faire de plus ici.
        wanted = Group.objects.filter(name__in=[
            f'redacteur_{site.legacy_site_slug or site.slug}'
            for site in self.cleaned_data.get('syndicats') or []])
        # `redacteur` (gabarit) inclus : il ne doit rester sur aucun compte.
        stale = (user.groups.filter(name__startswith='redacteur')
                 .exclude(name='redacteur_en_chef')
                 .exclude(pk__in=wanted))
        user.groups.remove(*stale)
        user.groups.add(*wanted)

    def _sync_author_profile(self, user):
        from .models import Author
        syndicats = list(self.cleaned_data.get('syndicats') or [])
        profile = Author.objects.filter(user=user).first()
        # Author.site ne porte qu'un syndicat : on garde l'actuel s'il reste
        # coché, sinon le premier coché.
        if profile is not None and profile.site in syndicats:
            site = profile.site
        else:
            site = syndicats[0] if syndicats else None
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
