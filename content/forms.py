from django import forms
from .models import ContactMessage, Comment


class ContactForm(forms.ModelForm):
    """Formulaire de contact"""

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
