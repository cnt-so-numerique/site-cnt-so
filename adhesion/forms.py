from django import forms


class AdhesionForm(forms.Form):
    # Champ toujours présent
    email = forms.EmailField(
        label='Adresse e-mail',
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'votre@email.fr'}),
    )

    def __init__(self, *args, formulaire=None, **kwargs):
        super().__init__(*args, **kwargs)
        if formulaire is None:
            return

        # Champs standards activables
        if formulaire.field_nom:
            self.fields['nom'] = forms.CharField(
                label='Nom',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Votre nom'}),
            )
        if formulaire.field_prenom:
            self.fields['prenom'] = forms.CharField(
                label='Prénom',
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Votre prénom'}),
            )
        if formulaire.field_adresse:
            self.fields['adresse'] = forms.CharField(
                label='Adresse',
                required=False,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '1 rue de la Paix'}),
            )
        if formulaire.field_ville:
            self.fields['ville'] = forms.CharField(
                label='Ville',
                required=False,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Paris'}),
            )
        if formulaire.field_code_postal:
            self.fields['code_postal'] = forms.CharField(
                label='Code postal',
                required=False,
                max_length=10,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '75001'}),
            )
        if formulaire.field_secteur_activite:
            self.fields['secteur_activite'] = forms.CharField(
                label="Secteur d'activité",
                required=False,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Bâtiment, Commerce…'}),
            )
        if formulaire.field_entreprise:
            self.fields['entreprise'] = forms.CharField(
                label='Entreprise / Employeur',
                required=False,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Nom de votre employeur'}),
            )
        if formulaire.field_telephone:
            self.fields['telephone'] = forms.CharField(
                label='Téléphone',
                required=False,
                max_length=30,
                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '06 12 34 56 78'}),
            )

        # Champs personnalisés du syndicat
        for champ in formulaire.champs_custom.all():
            field_key = f'custom_{champ.slug}'
            if champ.field_type == 'text':
                self.fields[field_key] = forms.CharField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.TextInput(attrs={'class': 'form-input'}),
                )
            elif champ.field_type == 'textarea':
                self.fields[field_key] = forms.CharField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4}),
                )
            elif champ.field_type == 'select':
                choices = [('', '— Choisir —')] + [(c, c) for c in champ.get_choices_list()]
                self.fields[field_key] = forms.ChoiceField(
                    label=champ.label,
                    required=champ.is_required,
                    choices=choices,
                    widget=forms.Select(attrs={'class': 'form-select'}),
                )
            elif champ.field_type == 'checkbox':
                self.fields[field_key] = forms.BooleanField(
                    label=champ.label,
                    required=champ.is_required,
                    widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
                )

        # Périodicité
        frequency_choices = []
        if formulaire.allow_monthly:
            frequency_choices.append(('monthly', 'Mensuelle (prélèvement automatique chaque mois)'))
        if formulaire.allow_annual:
            frequency_choices.append(('annual', 'Annuelle (prélèvement automatique chaque année)'))
        if formulaire.allow_onetime:
            frequency_choices.append(('onetime', 'Ponctuelle (paiement unique)'))

        if frequency_choices:
            self.fields['payment_frequency'] = forms.ChoiceField(
                label='Périodicité de la cotisation',
                choices=frequency_choices,
                initial=frequency_choices[0][0],
                widget=forms.RadioSelect(attrs={'class': 'form-radio'}),
            )

        # Montant
        if formulaire.price_mode == 'libre':
            self.fields['montant'] = forms.IntegerField(
                label='Montant de votre cotisation (€)',
                min_value=1,
                max_value=9999,
                widget=forms.NumberInput(attrs={
                    'class': 'form-input',
                    'placeholder': 'Ex: 10',
                    'min': '1',
                    'step': '1',
                }),
                help_text='Montant libre en euros entiers — saisissez ce que vous pouvez.',
            )

        # Signature
        self.fields['lieu_signature'] = forms.CharField(
            label='Fait à',
            initial=formulaire.lieu_defaut,
            widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Ville'}),
        )
        self.fields['certifie'] = forms.BooleanField(
            label="Je certifie l'exactitude des informations fournies et adhère aux statuts du syndicat.",
            widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        )

    def get_amount_cents(self, formulaire):
        if formulaire.price_mode == 'fixed':
            return formulaire.fixed_amount_cents
        montant = self.cleaned_data.get('montant')
        if montant:
            return montant * 100
        return None

    def get_custom_data(self, formulaire):
        data = {}
        for champ in formulaire.champs_custom.all():
            key = f'custom_{champ.slug}'
            value = self.cleaned_data.get(key)
            if value is not None:
                data[champ.slug] = value
        return data
