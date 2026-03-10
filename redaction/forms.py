from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from content.models import Article, Category, Tag, Site, MenuItem, Page



class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = ['title', 'content', 'excerpt', 'site', 'categories', 'tags', 'featured_image', 'status', 'is_sticky']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Titre de l\'article'}),
            'content': forms.HiddenInput(attrs={'id': 'id_content'}),
            'excerpt': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4, 'placeholder': 'Extrait court'}),
            'site': forms.Select(attrs={'class': 'form-select'}),
            'categories': forms.CheckboxSelectMultiple(),
            'tags': forms.CheckboxSelectMultiple(),
            'featured_image': forms.HiddenInput(attrs={'id': 'id_featured_image'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'is_sticky': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, user=None, current_site=None, **kwargs):
        super().__init__(*args, **kwargs)
        is_chef = user and (user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists())

        # Déterminer le site effectif pour filtrer catégories et tags
        effective_site = current_site
        if user and not is_chef:
            try:
                effective_site = user.author_profile.site
            except Exception:
                effective_site = None

        if effective_site:
            self.fields['categories'].queryset = Category.objects.filter(site=effective_site).order_by('name')
            self.fields['tags'].queryset = Tag.objects.filter(site=effective_site).order_by('name')
        else:
            self.fields['categories'].queryset = Category.objects.select_related('site').order_by('site', 'name')
            self.fields['tags'].queryset = Tag.objects.select_related('site').order_by('site', 'name')

        if user and not is_chef:
            # Rédacteur simple : statuts limités
            self.fields['status'].choices = [
                ('draft', 'Brouillon'),
                ('pending', 'Soumettre pour relecture'),
            ]
            # Site : champ caché limité au site du rédacteur
            if effective_site:
                self.fields['site'].queryset = Site.objects.filter(pk=effective_site.pk)
                self.fields['site'].initial = effective_site
            else:
                self.fields['site'].queryset = Site.objects.none()
            self.fields['site'].widget = forms.HiddenInput()


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'site', 'parent', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'site': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3}),
        }

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site:
            self.fields['site'].widget = forms.HiddenInput()
            self.fields['site'].initial = site
            self.fields['parent'].queryset = Category.objects.filter(site=site).order_by('name')
        else:
            self.fields['parent'].queryset = Category.objects.select_related('site').order_by('site', 'name')
        self.fields['parent'].required = False


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name', 'site']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'site': forms.HiddenInput(),
        }

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site:
            self.fields['site'].initial = site
        self.fields['site'].required = False


def get_redaction_groups():
    return Group.objects.filter(name__in=['redacteur_en_chef', 'redacteur'])


class UserCreateForm(UserCreationForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=get_redaction_groups(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Rôles',
    )
    site = forms.ModelChoiceField(
        queryset=Site.objects.filter(is_active=True),
        required=False,
        label='Site assigné',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2', 'groups', 'site']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data['groups'])
        return user


class UserEditForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=get_redaction_groups(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Rôles',
    )
    site = forms.ModelChoiceField(
        queryset=Site.objects.filter(is_active=True),
        required=False,
        label='Site assigné',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'groups', 'site']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['groups'].initial = self.instance.groups.filter(
                name__in=['redacteur_en_chef', 'redacteur']
            )
            try:
                self.fields['site'].initial = self.instance.author_profile.site
            except Exception:
                pass

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            # Retirer les 2 groupes redac, puis remettre les sélectionnés
            redac_groups = Group.objects.filter(name__in=['redacteur_en_chef', 'redacteur'])
            user.groups.remove(*redac_groups)
            user.groups.add(*self.cleaned_data['groups'])
        return user


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = [
            'menu', 'link_type', 'title', 'url',
            'category', 'target_site', 'article', 'page',
            'parent', 'order', 'opens_new_tab', 'is_active',
        ]
        widgets = {
            'menu':        forms.Select(attrs={'class': 'form-select'}),
            'link_type':   forms.Select(attrs={'class': 'form-select', 'id': 'id_link_type'}),
            'title':       forms.TextInput(attrs={'class': 'form-input'}),
            'url':         forms.TextInput(attrs={'class': 'form-input'}),
            'category':    forms.Select(attrs={'class': 'form-select'}),
            'target_site': forms.Select(attrs={'class': 'form-select'}),
            'article':     forms.Select(attrs={'class': 'form-select'}),
            'page':        forms.Select(attrs={'class': 'form-select'}),
            'parent':      forms.Select(attrs={'class': 'form-select'}),
            'order':       forms.NumberInput(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site:
            self.fields['category'].queryset = Category.objects.filter(site=site).order_by('name')
            self.fields['article'].queryset = Article.objects.filter(site=site).order_by('title')
            self.fields['page'].queryset = Page.objects.filter(site=site).order_by('title')
            self.fields['parent'].queryset = MenuItem.objects.filter(site=site).order_by('menu', 'order')
        else:
            self.fields['category'].queryset = Category.objects.none()
            self.fields['article'].queryset = Article.objects.none()
            self.fields['page'].queryset = Page.objects.none()
            self.fields['parent'].queryset = MenuItem.objects.none()
        self.fields['target_site'].queryset = Site.objects.filter(is_active=True).order_by('name')
        self.fields['category'].required = False
        self.fields['target_site'].required = False
        self.fields['article'].required = False
        self.fields['page'].required = False
        self.fields['parent'].required = False
        self.fields['url'].required = False
