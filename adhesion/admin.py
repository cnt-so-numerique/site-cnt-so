from django.contrib import admin

from .models import Adhesion, ChampCustom, FormulaireAdhesion, ZoneGeographique


class ChampCustomInline(admin.TabularInline):
    model = ChampCustom
    extra = 0
    fields = ['label', 'field_type', 'is_required', 'order']


@admin.register(FormulaireAdhesion)
class FormulaireAdhesionAdmin(admin.ModelAdmin):
    list_display = ['site', 'is_active', 'price_mode', 'stripe_onboarding_complete']
    list_filter = ['is_active', 'price_mode']
    inlines = [ChampCustomInline]
    fieldsets = [
        (None, {'fields': ['site', 'is_active']}),
        ('Tarification', {'fields': ['price_mode', 'fixed_amount_cents', 'allow_monthly', 'allow_annual', 'allow_onetime']}),
        ('Champs activés', {'fields': [
            'field_nom', 'field_prenom', 'field_adresse', 'field_ville',
            'field_code_postal', 'field_secteur_activite', 'field_entreprise', 'field_telephone',
        ]}),
        ('Signature', {'fields': ['lieu_defaut']}),
        ('Emails', {'fields': ['email_from', 'email_contact']}),
        ('Stripe Connect', {'fields': ['stripe_account_id', 'stripe_onboarding_complete']}),
    ]


@admin.register(ZoneGeographique)
class ZoneGeographiqueAdmin(admin.ModelAdmin):
    list_display = ['code_prefix', 'label', 'site']
    search_fields = ['code_prefix', 'label', 'site__name']


@admin.register(Adhesion)
class AdhesionAdmin(admin.ModelAdmin):
    list_display = ['email', 'nom', 'prenom', 'site', 'status', 'payment_frequency', 'amount_euros', 'created_at']
    list_filter = ['status', 'payment_frequency', 'payment_method', 'site']
    search_fields = ['email', 'nom', 'prenom']
    readonly_fields = ['token', 'created_at', 'updated_at', 'actif_at', 'custom_data',
                       'stripe_customer_id', 'stripe_subscription_id',
                       'stripe_payment_intent_id', 'stripe_checkout_session_id']
    fieldsets = [
        (None, {'fields': ['site', 'formulaire', 'status', 'note_interne']}),
        ('Identité', {'fields': ['nom', 'prenom', 'email', 'telephone']}),
        ('Adresse', {'fields': ['adresse', 'ville', 'code_postal']}),
        ('Activité', {'fields': ['secteur_activite', 'entreprise']}),
        ('Signature', {'fields': ['lieu_signature', 'date_signature', 'certifie']}),
        ('Paiement', {'fields': ['payment_frequency', 'payment_method', 'amount_cents']}),
        ('Stripe', {'fields': ['stripe_customer_id', 'stripe_subscription_id',
                               'stripe_payment_intent_id', 'stripe_checkout_session_id']}),
        ('Newsletters', {'fields': ['newsletter_syndicat_done', 'newsletter_regional_done', 'newsletter_national_done']}),
        ('Méta', {'fields': ['token', 'ip_address', 'custom_data', 'created_at', 'updated_at', 'actif_at']}),
    ]
