import csv
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt

from cms.models import SectionPage
from content.admin_utils import WagtailChefRequiredMixin as ChefRequiredMixin, get_current_site_for_view as _get_current_site_for_view

from .emails import send_relance_email
from .forms import AdhesionForm
from .models import Adhesion, ChampCustom, FormulaireAdhesion

logger = logging.getLogger(__name__)

ADHESION_BASE_URL = getattr(settings, 'ADHESION_BASE_URL', 'https://adhesion.cnt-so.org')


# ── Vues publiques ─────────────────────────────────────────────────────────────

@method_decorator(xframe_options_exempt, name='dispatch')
class FormulaireView(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.site_obj = get_object_or_404(SectionPage, slug=kwargs['site_slug'], live=True)
        # Rediriger vers la nouvelle app cnt-adhesion si le formulaire est actif là-bas
        self.use_new_app = getattr(settings, 'ADHESION_USE_NEW_APP', False)
        if not self.use_new_app:
            self.formulaire = get_object_or_404(FormulaireAdhesion, site=self.site_obj, is_active=True)
        self.embed = request.GET.get('embed') == '1'
        self.template_name = 'adhesion/formulaire_embed.html' if self.embed else 'adhesion/formulaire.html'

    def get(self, request, site_slug):
        if getattr(self, 'use_new_app', False):
            url = f"{ADHESION_BASE_URL}/adherer/{site_slug}/"
            return redirect(url, permanent=False)
        form = AdhesionForm(formulaire=self.formulaire)
        return render(request, self.template_name, {
            'form': form,
            'site': self.site_obj,
            'formulaire': self.formulaire,
            'embed': self.embed,
        })

    def post(self, request, site_slug):
        if getattr(self, 'use_new_app', False):
            return redirect(f"{ADHESION_BASE_URL}/adherer/{site_slug}/", permanent=False)
        form = AdhesionForm(request.POST, formulaire=self.formulaire)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'site': self.site_obj,
                'formulaire': self.formulaire,
                'embed': self.embed,
            })

        cd = form.cleaned_data
        adhesion = Adhesion(
            site=self.site_obj,
            formulaire=self.formulaire,
            email=cd['email'],
            nom=cd.get('nom', ''),
            prenom=cd.get('prenom', ''),
            adresse=cd.get('adresse', ''),
            ville=cd.get('ville', ''),
            code_postal=cd.get('code_postal', ''),
            secteur_activite=cd.get('secteur_activite', ''),
            entreprise=cd.get('entreprise', ''),
            telephone=cd.get('telephone', ''),
            lieu_signature=cd.get('lieu_signature', ''),
            date_signature=timezone.now().date(),
            certifie=cd.get('certifie', False),
            custom_data=form.get_custom_data(self.formulaire),
            payment_frequency=cd.get('payment_frequency', 'monthly'),
            payment_method='stripe',
            amount_cents=form.get_amount_cents(self.formulaire),
            status='pending',
            ip_address=_get_client_ip(request),
        )
        adhesion.save()

        # Phase 4 : rediriger vers Stripe Checkout (pas encore implémenté)
        # Pour l'instant : page de succès directe
        return redirect('adhesion:paiement_succes', site_slug=self.site_obj.slug)


@method_decorator(xframe_options_exempt, name='dispatch')
class PaiementSuccesView(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.site_obj = get_object_or_404(SectionPage, slug=kwargs['site_slug'])

    def get(self, request, site_slug):
        return render(request, 'adhesion/paiement_succes.html', {
            'site': self.site_obj,
        })


@method_decorator(xframe_options_exempt, name='dispatch')
class PaiementAnnuleView(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.site_obj = get_object_or_404(SectionPage, slug=kwargs['site_slug'])

    def get(self, request, site_slug):
        return render(request, 'adhesion/paiement_annule.html', {
            'site': self.site_obj,
        })


# ── Vues redaction ─────────────────────────────────────────────────────────────

class AdhesionListView(ChefRequiredMixin, View):
    def get(self, request):
        current_site = _get_current_site_for_view(request)
        if current_site:
            adhesions = Adhesion.objects.filter(site=current_site).select_related('site')
        else:
            adhesions = Adhesion.objects.select_related('site').all()

        status_filter = request.GET.get('status')
        if status_filter:
            adhesions = adhesions.filter(status=status_filter)

        q = request.GET.get('q', '').strip()
        if q:
            adhesions = adhesions.filter(email__icontains=q) | adhesions.filter(nom__icontains=q)

        return render(request, 'adhesion/redaction/adhesion_list.html', {
            'adhesions': adhesions,
            'current_site': current_site,
            'status_choices': Adhesion.STATUS_CHOICES,
            'status_filter': status_filter,
            'q': q,
        })


class AdhesionDetailView(ChefRequiredMixin, View):
    def _get_adhesion(self, request, pk):
        """Retourne l'adhésion en appliquant le scoping par site (prévention IDOR)."""
        current_site = _get_current_site_for_view(request)
        qs = Adhesion.objects.select_related('site', 'formulaire')
        if current_site:
            qs = qs.filter(site=current_site)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        adhesion = self._get_adhesion(request, pk)
        sites = SectionPage.objects.filter(live=True).order_by('title')
        return render(request, 'adhesion/redaction/adhesion_detail.html', {
            'adhesion': adhesion,
            'sites': sites,
            'status_choices': Adhesion.STATUS_CHOICES,
        })

    def post(self, request, pk):
        adhesion = self._get_adhesion(request, pk)
        action = request.POST.get('action')

        if action == 'changer_syndicat':
            new_site_id = request.POST.get('site_id')
            try:
                new_site = SectionPage.objects.get(pk=new_site_id)
                adhesion.site = new_site
                adhesion.save(update_fields=['site', 'updated_at'])
                messages.success(request, f'Syndicat modifié : {new_site.title}')
            except SectionPage.DoesNotExist:
                messages.error(request, 'Syndicat introuvable.')

        elif action == 'changer_statut':
            new_status = request.POST.get('status')
            valid = [s[0] for s in Adhesion.STATUS_CHOICES]
            if new_status in valid:
                if new_status in ('actif', 'manuel') and not adhesion.actif_at:
                    adhesion.actif_at = timezone.now()
                adhesion.status = new_status
                adhesion.save(update_fields=['status', 'actif_at', 'updated_at'])
                messages.success(request, f'Statut mis à jour : {adhesion.get_status_display()}')
            else:
                messages.error(request, 'Statut invalide.')

        elif action == 'note_interne':
            adhesion.note_interne = request.POST.get('note_interne', '')
            adhesion.save(update_fields=['note_interne', 'updated_at'])
            messages.success(request, 'Note enregistrée.')

        return redirect(f'/cms/adhesions/{pk}/')


class AdhesionExportView(ChefRequiredMixin, View):
    def get(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('/cms/adhesions/')

        adhesions = Adhesion.objects.filter(site=current_site).order_by('-created_at')

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="adhesions-{current_site.slug}.csv"'
        response.write('﻿')  # BOM UTF-8 pour Excel

        writer = csv.writer(response)
        writer.writerow([
            'nom', 'prenom', 'email', 'telephone',
            'adresse', 'code_postal', 'ville',
            'secteur_activite', 'entreprise',
            'periodicite', 'montant_euros', 'moyen_paiement',
            'statut', 'date_adhesion',
        ])
        for a in adhesions:
            writer.writerow([
                a.nom, a.prenom, a.email, a.telephone,
                a.adresse, a.code_postal, a.ville,
                a.secteur_activite, a.entreprise,
                a.get_payment_frequency_display(),
                str(a.amount_euros) if a.amount_euros else '',
                a.get_payment_method_display(),
                a.get_status_display(),
                a.created_at.strftime('%d/%m/%Y'),
            ])

        return response


class AdhesionRelanceView(ChefRequiredMixin, View):
    def get(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('/cms/adhesions/')
        seuil = timezone.now() - timedelta(days=7)
        pending = Adhesion.objects.filter(
            site=current_site, status='pending', created_at__lte=seuil
        )
        return render(request, 'adhesion/redaction/adhesion_relance_confirm.html', {
            'adhesions': pending,
            'current_site': current_site,
        })

    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            return redirect('/cms/adhesions/')
        seuil = timezone.now() - timedelta(days=7)
        pending = Adhesion.objects.filter(
            site=current_site, status='pending', created_at__lte=seuil
        )
        sent = 0
        delay = getattr(__import__('django.conf', fromlist=['settings']).settings, 'NEWSLETTER_SEND_DELAY', 0)
        import time
        for adhesion in pending:
            try:
                send_relance_email(adhesion)
                sent += 1
                if delay:
                    time.sleep(delay)
            except Exception:
                logger.exception("Échec relance pour %s", adhesion.email)
        messages.success(request, f'{sent} e-mail(s) de relance envoyé(s).')
        return redirect('/cms/adhesions/')


class FormulaireConfigView(ChefRequiredMixin, View):
    template_name = 'adhesion/redaction/formulaire_config.html'

    def _get_or_create_formulaire(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            return None, None
        formulaire, _ = FormulaireAdhesion.objects.get_or_create(site=current_site)
        return current_site, formulaire

    def get(self, request):
        current_site, formulaire = self._get_or_create_formulaire(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('/cms/')
        champs = formulaire.champs_custom.all()
        fixed_amount_euros = formulaire.fixed_amount_cents // 100 if formulaire.fixed_amount_cents else ''
        return render(request, self.template_name, {
            'formulaire': formulaire,
            'current_site': current_site,
            'champs': champs,
            'fixed_amount_euros': fixed_amount_euros,
        })

    def post(self, request):
        current_site, formulaire = self._get_or_create_formulaire(request)
        if not current_site:
            return redirect('/cms/')

        POST = request.POST
        formulaire.is_active = 'is_active' in POST
        formulaire.price_mode = POST.get('price_mode', 'libre')
        try:
            fc = POST.get('fixed_amount_euros', '')
            formulaire.fixed_amount_cents = int(fc) * 100 if fc else None
        except ValueError:
            formulaire.fixed_amount_cents = None

        formulaire.allow_monthly = 'allow_monthly' in POST
        formulaire.allow_annual = 'allow_annual' in POST
        formulaire.allow_onetime = 'allow_onetime' in POST

        for field in ['field_nom', 'field_prenom', 'field_adresse', 'field_ville',
                      'field_code_postal', 'field_secteur_activite', 'field_entreprise', 'field_telephone']:
            setattr(formulaire, field, field in POST)

        formulaire.lieu_defaut = POST.get('lieu_defaut', '')

        # Validation des adresses email avant enregistrement
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError
        for field_name in ('email_from', 'email_contact'):
            value = POST.get(field_name, '').strip()
            if value:
                try:
                    validate_email(value)
                    setattr(formulaire, field_name, value)
                except DjangoValidationError:
                    messages.error(request, f'Adresse e-mail invalide : {value}')
                    return redirect('/cms/adhesion-config/')
            else:
                setattr(formulaire, field_name, '')

        formulaire.save()

        messages.success(request, 'Configuration enregistrée.')
        return redirect('/cms/adhesion-config/')


class ChampCustomCreateView(ChefRequiredMixin, View):
    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            return redirect('/cms/adhesion-config/')
        formulaire = get_object_or_404(FormulaireAdhesion, site=current_site)
        label = request.POST.get('label', '').strip()
        if not label:
            messages.error(request, 'Le libellé est obligatoire.')
            return redirect('/cms/adhesion-config/')
        ChampCustom.objects.create(
            formulaire=formulaire,
            label=label,
            field_type=request.POST.get('field_type', 'text'),
            choices_text=request.POST.get('choices_text', ''),
            is_required='is_required' in request.POST,
            order=formulaire.champs_custom.count(),
        )
        messages.success(request, 'Champ ajouté.')
        return redirect('/cms/adhesion-config/')


class ChampCustomEditView(ChefRequiredMixin, View):
    def post(self, request, pk):
        champ = get_object_or_404(ChampCustom, pk=pk)
        champ.label = request.POST.get('label', champ.label).strip()
        champ.field_type = request.POST.get('field_type', champ.field_type)
        champ.choices_text = request.POST.get('choices_text', '')
        champ.is_required = 'is_required' in request.POST
        champ.save()
        messages.success(request, 'Champ modifié.')
        return redirect('/cms/adhesion-config/')


class ChampCustomDeleteView(ChefRequiredMixin, View):
    def post(self, request, pk):
        champ = get_object_or_404(ChampCustom, pk=pk)
        champ.delete()
        messages.success(request, 'Champ supprimé.')
        return redirect('/cms/adhesion-config/')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
