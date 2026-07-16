from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.utils.text import slugify

# Outils gérés en autonomie par chaque syndicat (décision 2026-07-16) :
# accessibles aux rédacteurs de syndicat, scoppés par get_current_site_for_view.
from content.admin_utils import WagtailSyndicatRequiredMixin as ChefRequiredMixin
from content.admin_utils import get_current_site_for_view as _get_current_site
from content.models import ContactMessage, FormulaireContact, ChampContactCustom


class ContactSubmissionListView(ChefRequiredMixin, View):
    def get(self, request):
        current_site = _get_current_site(request)
        q = request.GET.get('q', '')
        status_filter = request.GET.get('status', '')

        qs = ContactMessage.objects.select_related('site')
        if current_site:
            qs = qs.filter(site=current_site)

        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q))
        if status_filter == 'unread':
            qs = qs.filter(is_read=False)
        elif status_filter == 'read':
            qs = qs.filter(is_read=True)

        return render(request, 'cms/contact/submission_list.html', {
            'submissions': qs[:200],
            'current_site': current_site,
            'q': q,
            'status_filter': status_filter,
        })


class ContactSubmissionDetailView(ChefRequiredMixin, View):
    def _get_submission(self, request, pk):
        current_site = _get_current_site(request)
        qs = ContactMessage.objects.select_related('site', 'formulaire')
        if current_site:
            qs = qs.filter(site=current_site)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        sub = self._get_submission(request, pk)
        if not sub.is_read:
            sub.is_read = True
            sub.save(update_fields=['is_read'])
        return render(request, 'cms/contact/submission_detail.html', {'submission': sub})

    def post(self, request, pk):
        sub = self._get_submission(request, pk)
        action = request.POST.get('action')
        if action == 'toggle_read':
            sub.is_read = not sub.is_read
            sub.save(update_fields=['is_read'])
        elif action == 'delete':
            sub.delete()
            messages.success(request, 'Message supprimé.')
            return redirect('/cms/contact/')
        return redirect(f'/cms/contact/{pk}/')


class FormulaireContactConfigView(ChefRequiredMixin, View):
    template_name = 'cms/contact/formulaire_config.html'

    def _get_or_create(self, request):
        current_site = _get_current_site(request)
        if not current_site:
            return None, None
        formulaire, _ = FormulaireContact.objects.get_or_create(site=current_site)
        return current_site, formulaire

    def get(self, request):
        current_site, formulaire = self._get_or_create(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('/cms/')
        return render(request, self.template_name, {
            'formulaire': formulaire,
            'current_site': current_site,
            'champs': formulaire.champs_custom.all(),
        })

    def post(self, request):
        current_site, formulaire = self._get_or_create(request)
        if not current_site:
            return redirect('/cms/')
        POST = request.POST
        formulaire.is_active = 'is_active' in POST
        formulaire.intro_text = POST.get('intro_text', '')
        formulaire.email_subject_prefix = POST.get('email_subject_prefix', '')
        formulaire.field_nom = 'field_nom' in POST
        formulaire.field_telephone = 'field_telephone' in POST
        formulaire.field_ville = 'field_ville' in POST
        formulaire.field_secteur = 'field_secteur' in POST
        formulaire.field_objet = 'field_objet' in POST

        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError
        email_val = POST.get('email_destination', '').strip()
        if email_val:
            try:
                validate_email(email_val)
                formulaire.email_destination = email_val
            except DjangoValidationError:
                messages.error(request, f'Adresse e-mail invalide : {email_val}')
                return redirect('/cms/contact-config/')
        else:
            formulaire.email_destination = ''

        formulaire.save()
        messages.success(request, 'Configuration enregistrée.')
        return redirect('/cms/contact-config/')


class ChampContactCreateView(ChefRequiredMixin, View):
    def post(self, request):
        current_site = _get_current_site(request)
        if not current_site:
            return redirect('/cms/contact-config/')
        formulaire = get_object_or_404(FormulaireContact, site=current_site)
        label = request.POST.get('label', '').strip()
        if not label:
            return redirect('/cms/contact-config/')
        slug = slugify(label)
        if not slug:
            return redirect('/cms/contact-config/')
        # Évite les doublons de slug
        base_slug = slug
        counter = 1
        while formulaire.champs_custom.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        ChampContactCustom.objects.create(
            formulaire=formulaire,
            label=label,
            slug=slug,
            field_type=request.POST.get('field_type', 'text'),
            choices_text=request.POST.get('choices_text', ''),
            is_required='is_required' in request.POST,
            order=formulaire.champs_custom.count(),
        )
        return redirect('/cms/contact-config/')


class ChampContactDeleteView(ChefRequiredMixin, View):
    def post(self, request, pk):
        current_site = _get_current_site(request)
        if not current_site:
            return redirect('/cms/contact-config/')
        champ = get_object_or_404(ChampContactCustom, pk=pk, formulaire__site=current_site)
        champ.delete()
        return redirect('/cms/contact-config/')
