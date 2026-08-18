from django import forms
from hcaptcha.fields import hCaptchaField
from .models import ContactMessage, Comment, FormulaireContact


class ContactForm(forms.ModelForm):
    """Formulaire de contact"""

    captcha = hCaptchaField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'phone', 'city', 'sector', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre nom'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre adresse e-mail'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre numéro de téléphone'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre ville'
            }),
            'sector': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ex : Nettoyage, Restauration, Éducation…'
            }),
            'subject': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Objet de votre message'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-textarea',
                'placeholder': 'Votre message',
                'rows': 6
            }),
        }


class DynamicContactForm(forms.Form):
    """Formulaire de contact dynamique construit depuis FormulaireContact."""

    email = forms.EmailField(
        label='Adresse e-mail *',
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'votre@email.fr'}),
    )

    def __init__(self, *args, formulaire=None, **kwargs):
        super().__init__(*args, **kwargs)
        if formulaire is None:
            return

        if formulaire.field_nom:
            self.fields['nom'] = forms.CharField(
                label='Nom *',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Votre nom'}),
            )
        if formulaire.field_prenom:
            self.fields['prenom'] = forms.CharField(
                label='Prénom *',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Votre prénom'}),
            )
        if formulaire.field_telephone:
            self.fields['telephone'] = forms.CharField(
                label='Téléphone *',
                max_length=30,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '06 12 34 56 78'}),
            )
        if formulaire.field_ville:
            self.fields['ville'] = forms.CharField(
                label='Ville *',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Votre ville'}),
            )
        if formulaire.field_secteur:
            self.fields['secteur'] = forms.CharField(
                label='Secteur professionnel / Métier *',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Ex : Nettoyage, BTP…'}),
            )
        if formulaire.field_objet:
            self.fields['objet'] = forms.CharField(
                label='Objet *',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': "Objet de votre message"}),
            )

        for champ in formulaire.champs_custom.all():
            key = f'custom_{champ.slug}'
            if champ.field_type == 'text':
                self.fields[key] = forms.CharField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.TextInput(attrs={'class': 'form-input'}),
                )
            elif champ.field_type == 'textarea':
                self.fields[key] = forms.CharField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4}),
                )
            elif champ.field_type == 'select':
                choices = [('', '— Choisir —')] + [(c, c) for c in champ.get_choices_list()]
                self.fields[key] = forms.ChoiceField(
                    label=champ.label,
                    required=champ.is_required,
                    choices=choices,
                    widget=forms.Select(attrs={'class': 'form-select'}),
                )
            elif champ.field_type == 'checkbox':
                self.fields[key] = forms.BooleanField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
                )

        self.fields['message'] = forms.CharField(
            label='Message *',
            widget=forms.Textarea(attrs={'class': 'form-textarea', 'rows': 6, 'placeholder': 'Votre message'}),
        )
        self.fields['captcha'] = hCaptchaField()

    def get_custom_data(self, formulaire):
        data = {}
        for champ in formulaire.champs_custom.all():
            val = self.cleaned_data.get(f'custom_{champ.slug}')
            if val is not None:
                data[champ.slug] = val
        return data


class CommentForm(forms.ModelForm):
    """Formulaire de commentaire"""

    class Meta:
        model = Comment
        fields = ['author_name', 'author_email', 'content']
        widgets = {
            'author_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre nom'
            }),
            'author_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'Votre email (non publié)'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-textarea',
                'placeholder': 'Votre commentaire',
                'rows': 4
            }),
        }


class NewsletterSubscribeForm(forms.Form):
    """Première étape de l'inscription : l'adresse, et un champ piège.

    L'inscription acceptait auparavant n'importe quel POST : ni formulaire, ni
    captcha, ni limite. Un botnet s'en est servi du 24/07 au 17/08/2026 pour
    faire envoyer par nos serveurs près de 2 000 courriels de confirmation à
    des adresses tierces, une centaine par jour depuis 25 adresses IP.
    """

    email = forms.EmailField()
    name = forms.CharField(max_length=200, required=False)
    # Invisible pour un humain, et sans raison d'être rempli : un robot qui
    # remplit tous les champs qu'il trouve se signale en le renseignant.
    site_web = forms.CharField(required=False)

    def clean_site_web(self):
        if self.cleaned_data.get('site_web'):
            raise forms.ValidationError("Robot détecté.")
        return ''


class NewsletterUnsubscribeForm(forms.Form):
    """Désabonnement : l'adresse, et rien d'autre.

    Pas de captcha ici, à dessein. Chaque obstacle sur le chemin de la sortie
    se paie en signalements « courrier indésirable », et un signalement coûte
    bien plus cher à la délivrabilité qu'un désabonnement de trop.
    """

    email = forms.EmailField(label="Votre adresse e-mail")


class NewsletterCaptchaForm(forms.Form):
    """Deuxième étape : prouver qu'on est humain.

    Le formulaire d'inscription est inclus sur l'accueil et sur chaque article :
    y placer le hCaptcha chargerait son script sur tout le site, pour un champ
    unique. On le demande donc sur une page dédiée, à laquelle mène la première
    étape — et c'est cette page, et elle seule, qui crée l'abonné.
    """

    email = forms.EmailField(widget=forms.HiddenInput)
    name = forms.CharField(max_length=200, required=False,
                           widget=forms.HiddenInput)
    captcha = hCaptchaField()
