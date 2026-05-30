import django.forms as dj_forms
from django.urls import path
from wagtail import hooks
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, FieldRowPanel, TabbedInterface, ObjectList

from .models import Adhesion, FormulaireAdhesion, ChampCustom, ZoneGeographique


class FormulaireAdhesionAdminForm(WagtailAdminModelForm):
    """Form Wagtail qui expose le montant fixe en euros (entiers) plutôt qu'en centimes."""
    fixed_amount_euros = dj_forms.IntegerField(
        required=False,
        min_value=1,
        max_value=9999,
        label='Montant fixe (€)',
        help_text='Entrez le montant en euros entiers (ex : 5 pour 5€)',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('fixed_amount_cents', None)
        instance = kwargs.get('instance')
        if instance and instance.pk and instance.fixed_amount_cents:
            self.fields['fixed_amount_euros'].initial = instance.fixed_amount_cents // 100

    def save(self, commit=True):
        instance = super().save(commit=False)
        euros = self.cleaned_data.get('fixed_amount_euros')
        instance.fixed_amount_cents = euros * 100 if euros else None
        if commit:
            instance.save()
            self.save_m2m()
        return instance


FormulaireAdhesion.base_form_class = FormulaireAdhesionAdminForm


# ── Formulaires d'adhésion ────────────────────────────────────────────────────

class FormulaireAdhesionViewSet(SnippetViewSet):
    model = FormulaireAdhesion
    icon = 'form'
    menu_label = "Formulaires d'adhésion"
    menu_order = 100
    list_display = ['site', 'is_active', 'price_mode']
    list_filter = ['is_active', 'price_mode']
    search_fields = ['site__name']

    panels = [
        TabbedInterface([
            ObjectList([
                FieldPanel('site'),
                FieldPanel('is_active'),
            ], heading='Général'),
            ObjectList([
                FieldPanel('price_mode'),
                FieldPanel('fixed_amount_euros'),
                FieldRowPanel([
                    FieldPanel('allow_monthly'),
                    FieldPanel('allow_annual'),
                    FieldPanel('allow_onetime'),
                ]),
            ], heading='Paiement'),
            ObjectList([
                FieldRowPanel([
                    FieldPanel('field_nom'),
                    FieldPanel('field_prenom'),
                ]),
                FieldRowPanel([
                    FieldPanel('field_adresse'),
                    FieldPanel('field_ville'),
                ]),
                FieldRowPanel([
                    FieldPanel('field_code_postal'),
                    FieldPanel('field_telephone'),
                ]),
                FieldRowPanel([
                    FieldPanel('field_secteur_activite'),
                    FieldPanel('field_entreprise'),
                ]),
                FieldPanel('lieu_defaut'),
            ], heading='Champs'),
            ObjectList([
                FieldPanel('stripe_account_id'),
                FieldPanel('stripe_onboarding_complete'),
                FieldPanel('email_from'),
                FieldPanel('email_contact'),
            ], heading='Configuration'),
        ])
    ]

    def get_queryset(self, request):
        from cms.site_context import scope_qs
        return scope_qs(FormulaireAdhesion.objects.all(), request, site_field='site')


# ── Adhésions ──────────────────────────────────────────────────────────────────

class AdhesionViewSet(SnippetViewSet):
    model = Adhesion
    icon = 'group'
    menu_label = 'Adhésions'
    menu_order = 200
    list_display = ['nom', 'prenom', 'email', 'site', 'status', 'payment_frequency', 'created_at']
    list_filter = ['site', 'status', 'payment_frequency', 'payment_method']
    search_fields = ['nom', 'prenom', 'email', 'ville']
    ordering = ['-created_at']

    panels = [
        TabbedInterface([
            ObjectList([
                FieldRowPanel([
                    FieldPanel('site'),
                    FieldPanel('status'),
                ]),
                FieldRowPanel([
                    FieldPanel('nom'),
                    FieldPanel('prenom'),
                ]),
                FieldPanel('email'),
                FieldRowPanel([
                    FieldPanel('telephone'),
                    FieldPanel('ville'),
                ]),
                FieldPanel('adresse'),
                FieldPanel('code_postal'),
                FieldRowPanel([
                    FieldPanel('secteur_activite'),
                    FieldPanel('entreprise'),
                ]),
            ], heading='Personne'),
            ObjectList([
                FieldRowPanel([
                    FieldPanel('payment_frequency'),
                    FieldPanel('payment_method'),
                ]),
                FieldPanel('amount_cents'),
                FieldPanel('stripe_customer_id'),
                FieldPanel('stripe_subscription_id'),
                FieldPanel('stripe_payment_intent_id'),
            ], heading='Paiement'),
            ObjectList([
                FieldPanel('note_interne'),
                FieldPanel('custom_data'),
                FieldPanel('lieu_signature'),
                FieldPanel('date_signature'),
            ], heading='Divers'),
        ])
    ]

    def get_queryset(self, request):
        from cms.site_context import scope_qs
        return scope_qs(Adhesion.objects.all(), request, site_field='site')


# ── Zones géographiques ───────────────────────────────────────────────────────

class ZoneGeographiqueViewSet(SnippetViewSet):
    model = ZoneGeographique
    icon = 'site'
    menu_label = 'Zones géographiques'
    menu_order = 300
    list_display = ['label', 'code_prefix', 'site']
    list_filter = ['site']
    search_fields = ['label', 'code_prefix']

    panels = [
        FieldPanel('site'),
        FieldPanel('code_prefix'),
        FieldPanel('label'),
    ]


# ── Champs custom ─────────────────────────────────────────────────────────────

class ChampCustomViewSet(SnippetViewSet):
    model = ChampCustom
    icon = 'edit'
    menu_label = 'Champs personnalisés'
    menu_order = 400
    list_display = ['label', 'formulaire', 'field_type', 'is_required', 'order']
    list_filter = ['field_type', 'is_required']
    search_fields = ['label']

    panels = [
        FieldPanel('formulaire'),
        FieldPanel('label'),
        FieldPanel('slug'),
        FieldPanel('field_type'),
        FieldPanel('choices_text'),
        FieldPanel('is_required'),
        FieldPanel('order'),
    ]


# ── Groupe Adhésions ──────────────────────────────────────────────────────────

class AdhesionsGroup(SnippetViewSetGroup):
    menu_label = 'Adhésions'
    menu_icon = 'group'
    menu_order = 500
    items = (AdhesionViewSet, FormulaireAdhesionViewSet, ChampCustomViewSet, ZoneGeographiqueViewSet)


register_snippet(AdhesionsGroup)


# ── URLs admin adhésions (list, detail, export, relance, config) ──────────────

@hooks.register('register_admin_urls')
def register_adhesion_admin_urls():
    from adhesion.views import (
        AdhesionListView, AdhesionDetailView,
        AdhesionExportView, AdhesionRelanceView,
        FormulaireConfigView, ChampCustomCreateView,
        ChampCustomEditView, ChampCustomDeleteView,
    )
    return [
        path('adhesions/', AdhesionListView.as_view(), name='adhesion_list'),
        path('adhesions/export/', AdhesionExportView.as_view(), name='adhesion_export'),
        path('adhesions/relance/', AdhesionRelanceView.as_view(), name='adhesion_relance'),
        path('adhesions/<int:pk>/', AdhesionDetailView.as_view(), name='adhesion_detail'),
        path('adhesion-config/', FormulaireConfigView.as_view(), name='formulaire_config'),
        path('adhesion-config/champ/ajouter/', ChampCustomCreateView.as_view(), name='champ_custom_create'),
        path('adhesion-config/champ/<int:pk>/modifier/', ChampCustomEditView.as_view(), name='champ_custom_edit'),
        path('adhesion-config/champ/<int:pk>/supprimer/', ChampCustomDeleteView.as_view(), name='champ_custom_delete'),
    ]
