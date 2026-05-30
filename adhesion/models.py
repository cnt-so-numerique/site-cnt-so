import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

class FormulaireAdhesion(models.Model):
    PRICE_MODE_CHOICES = [
        ('libre', 'Prix libre'),
        ('fixed', 'Montant fixe'),
    ]

    site = models.OneToOneField(
        'cms.SectionPage', on_delete=models.CASCADE,
        related_name='formulaire_adhesion', verbose_name='Syndicat'
    )
    is_active = models.BooleanField(default=False, verbose_name='Actif')

    # Stripe Connect
    stripe_account_id = models.CharField(
        max_length=100, blank=True, verbose_name='ID compte Stripe Connect'
    )
    stripe_onboarding_complete = models.BooleanField(
        default=False, verbose_name='Onboarding Stripe terminé'
    )

    # Prix
    price_mode = models.CharField(
        max_length=10, choices=PRICE_MODE_CHOICES, default='libre',
        verbose_name='Mode de tarification'
    )
    fixed_amount_cents = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='Montant fixe',
        help_text='Stocké en centimes en interne'
    )

    # Fréquences autorisées
    allow_monthly = models.BooleanField(default=True, verbose_name='Autoriser mensuel')
    allow_annual = models.BooleanField(default=True, verbose_name='Autoriser annuel')
    allow_onetime = models.BooleanField(default=True, verbose_name='Autoriser ponctuel')

    # Champs standards activables (email toujours obligatoire)
    field_nom = models.BooleanField(default=True, verbose_name='Champ Nom')
    field_prenom = models.BooleanField(default=True, verbose_name='Champ Prénom')
    field_adresse = models.BooleanField(default=False, verbose_name='Champ Adresse')
    field_ville = models.BooleanField(default=False, verbose_name='Champ Ville')
    field_code_postal = models.BooleanField(default=False, verbose_name='Champ Code postal')
    field_secteur_activite = models.BooleanField(default=False, verbose_name="Champ Secteur d'activité")
    field_entreprise = models.BooleanField(default=False, verbose_name='Champ Entreprise')
    field_telephone = models.BooleanField(default=False, verbose_name='Champ Téléphone')

    # Signature
    lieu_defaut = models.CharField(
        max_length=200, blank=True, verbose_name='Lieu pré-rempli',
        help_text='Lieu pré-rempli dans la zone signature (ex: Paris)'
    )

    # Email
    email_from = models.EmailField(
        blank=True, verbose_name='Adresse expéditeur',
        help_text='Adresse From pour les e-mails de confirmation (laissez vide pour utiliser la conf)'
    )
    email_contact = models.EmailField(
        blank=True, verbose_name='Adresse de contact',
        help_text='Adresse Reply-To dans les e-mails (adresse du syndicat)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Formulaire d'adhésion"
        verbose_name_plural = "Formulaires d'adhésion"

    def __str__(self):
        return f"Formulaire – {self.site.name}"

    @property
    def fixed_amount_euros(self):
        if self.fixed_amount_cents:
            return Decimal(self.fixed_amount_cents) / 100
        return None


class ChampCustom(models.Model):
    FIELD_TYPE_CHOICES = [
        ('text', 'Texte court'),
        ('textarea', 'Texte long'),
        ('select', 'Liste déroulante'),
        ('checkbox', 'Case à cocher'),
    ]

    formulaire = models.ForeignKey(
        FormulaireAdhesion, on_delete=models.CASCADE,
        related_name='champs_custom', verbose_name='Formulaire'
    )
    label = models.CharField(max_length=200, verbose_name='Libellé')
    slug = models.SlugField(
        max_length=200, verbose_name='Identifiant interne',
        help_text='Auto-généré depuis le libellé'
    )
    field_type = models.CharField(
        max_length=20, choices=FIELD_TYPE_CHOICES, default='text',
        verbose_name='Type de champ'
    )
    choices_text = models.TextField(
        blank=True, verbose_name='Options',
        help_text='Pour type "liste déroulante" : une option par ligne'
    )
    is_required = models.BooleanField(default=False, verbose_name='Obligatoire')
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')

    class Meta:
        ordering = ['order']
        unique_together = [['formulaire', 'slug']]
        verbose_name = 'Champ personnalisé'
        verbose_name_plural = 'Champs personnalisés'

    def __str__(self):
        return f"{self.label} ({self.formulaire.site.name})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.label)
            slug = base
            n = 1
            while ChampCustom.objects.filter(formulaire=self.formulaire, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_choices_list(self):
        return [c.strip() for c in self.choices_text.splitlines() if c.strip()]


class ZoneGeographique(models.Model):
    site = models.ForeignKey(
        'cms.SectionPage', on_delete=models.CASCADE,
        related_name='zones_geographiques', verbose_name='Site régional'
    )
    code_prefix = models.CharField(
        max_length=5, unique=True, verbose_name='Préfixe code postal',
        help_text='Ex: 69 pour le Rhône, 75 pour Paris'
    )
    label = models.CharField(max_length=200, blank=True, verbose_name='Libellé')

    class Meta:
        verbose_name = 'Zone géographique'
        verbose_name_plural = 'Zones géographiques'
        ordering = ['code_prefix']

    def __str__(self):
        return f"{self.code_prefix} → {self.site.name}"


class Adhesion(models.Model):
    PAYMENT_FREQUENCY_CHOICES = [
        ('monthly', 'Mensuelle'),
        ('annual', 'Annuelle'),
        ('onetime', 'Unique'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('stripe', 'Carte bancaire'),
        ('wero', 'Wero'),
        ('manuel', 'Manuel / Virement'),
    ]
    STATUS_CHOICES = [
        ('pending', 'En attente de paiement'),
        ('actif', 'Actif'),
        ('annule', 'Annulé'),
        ('expire', 'Expiré'),
        ('manuel', 'Actif (manuel)'),
    ]

    site = models.ForeignKey(
        'cms.SectionPage', on_delete=models.PROTECT,
        related_name='adhesions', verbose_name='Syndicat'
    )
    formulaire = models.ForeignKey(
        FormulaireAdhesion, on_delete=models.PROTECT,
        null=True, blank=True, related_name='adhesions'
    )

    # Infos personnelles
    nom = models.CharField(max_length=200, blank=True, verbose_name='Nom')
    prenom = models.CharField(max_length=200, blank=True, verbose_name='Prénom')
    email = models.EmailField(verbose_name='Adresse e-mail')
    telephone = models.CharField(max_length=30, blank=True, verbose_name='Téléphone')
    adresse = models.CharField(max_length=300, blank=True, verbose_name='Adresse')
    ville = models.CharField(max_length=200, blank=True, verbose_name='Ville')
    code_postal = models.CharField(max_length=10, blank=True, verbose_name='Code postal')
    secteur_activite = models.CharField(max_length=200, blank=True, verbose_name="Secteur d'activité")
    entreprise = models.CharField(max_length=200, blank=True, verbose_name='Entreprise')

    # Signature
    lieu_signature = models.CharField(max_length=200, blank=True, verbose_name='Lieu de signature')
    date_signature = models.DateField(null=True, blank=True, verbose_name='Date de signature')
    certifie = models.BooleanField(default=False, verbose_name='Certifié exact')

    # Champs custom (dict slug→valeur)
    custom_data = models.JSONField(default=dict, blank=True, verbose_name='Réponses champs custom')

    # Paiement
    payment_frequency = models.CharField(
        max_length=20, choices=PAYMENT_FREQUENCY_CHOICES, default='monthly',
        verbose_name='Périodicité'
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default='stripe',
        verbose_name='Moyen de paiement'
    )
    amount_cents = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Montant (centimes)'
    )

    # Stripe
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=100, blank=True)
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True)

    # Statut
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name='Statut'
    )

    # Newsletters
    newsletter_syndicat_done = models.BooleanField(default=False)
    newsletter_regional_done = models.BooleanField(default=False)
    newsletter_national_done = models.BooleanField(default=False)

    # Méta
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    note_interne = models.TextField(blank=True, verbose_name='Note interne')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    actif_at = models.DateTimeField(null=True, blank=True, verbose_name='Date de première activation')

    class Meta:
        verbose_name = 'Adhésion'
        verbose_name_plural = 'Adhésions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.prenom} {self.nom} – {self.site.name} ({self.get_status_display()})"

    @property
    def amount_euros(self):
        if self.amount_cents:
            return Decimal(self.amount_cents) / 100
        return None

    def marquer_actif(self):
        self.status = 'actif'
        if not self.actif_at:
            self.actif_at = timezone.now()
        self.save(update_fields=['status', 'actif_at', 'updated_at'])
