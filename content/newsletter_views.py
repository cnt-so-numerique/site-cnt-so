"""
Vues pour l'envoi de newsletter et la gestion des abonnés.
Anciennement dans redaction/views.py — maintenant exposées via Wagtail admin URLs.
"""
import csv
import time

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views import View

from content.admin_utils import WagtailSyndicatRequiredMixin, get_current_site_for_view, is_chef
from content.courriel import destinataire_de_reponse
from content.models import Newsletter, Subscriber


from content.ovh_sync import lists_for_site as _ovh_list_names


def _annotate_image_urls(articles, site_url):
    """Pose na.image_url et na.link_url en URLs absolues.

    any_image_url et get_absolute_url peuvent être relatives ou déjà absolues
    (image legacy, article d'une section à domaine autonome)."""
    base = site_url.rstrip('/')
    for na in articles:
        img = na.article.any_image_url
        if img and not img.startswith('http'):
            img = base + img
        na.image_url = img
        link = na.article.get_absolute_url()
        na.link_url = link if link.startswith('http') else base + link


def _corps_texte(newsletter, articles, unsubscribe_url):
    """Version texte de la newsletter, rubriques comprises.

    Elle suit le même découpage que le HTML : un lecteur en texte brut doit
    recevoir le même sommaire, pas une liste à plat qui perdrait le sens des
    sections.
    """
    lignes = [newsletter.title, '', newsletter.intro, '']
    for libelle, groupe in newsletter.par_rubrique(articles):
        if libelle:
            lignes += ['', libelle.upper(), '-' * len(libelle)]
        lignes += [f'- {na.article.title} : {na.link_url}' for na in groupe]
    lignes += ['', f'Gérer votre abonnement : {unsubscribe_url}']
    return '\n'.join(lignes)


class NewsletterSendView(WagtailSyndicatRequiredMixin, View):
    """Confirmation puis envoi de la newsletter."""

    def _get_newsletter(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = get_current_site_for_view(request)
        if current_site is None:
            # Un chef confédéral sans syndicat sélectionné garde la main ; pour
            # tout autre compte, l'absence de syndicat doit refuser et non
            # laisser passer — le mixin le garantit déjà, mais la garde doit
            # tenir seule.
            if not is_chef(request.user):
                raise PermissionDenied
        elif newsletter.site != current_site:
            raise PermissionDenied
        return newsletter

    def _refus_si_newsletter_coupee(self, request, newsletter):
        """Refuse l'envoi si le syndicat ne propose pas de newsletter.

        Sans ce garde-fou, un syndicat dont la newsletter est coupée pouvait
        malgré tout composer et « envoyer » une lettre : elle ne partait à
        personne, ses listes étant vides, sans que rien ne le dise.
        """
        site = newsletter.site
        if site is not None and not site.newsletter_active:
            messages.error(request, (
                f"La newsletter n'est pas activée pour « {site.title} ». "
                f"Seule la confédération en diffuse une ; les autres listes "
                f"sont internes. Pour la rendre à ce syndicat, cochez "
                f"« Proposer la newsletter sur ce site » dans sa fiche."
            ))
            return redirect('/cms/snippets/content/newsletter/')
        return None

    def get(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.error(request, 'Newsletter déjà envoyée.')
            return redirect('/cms/snippets/content/newsletter/')
        refus = self._refus_si_newsletter_coupee(request, newsletter)
        if refus:
            return refus

        site = newsletter.site
        list_names = _ovh_list_names(site)
        if list_names:
            from django.conf import settings as _s
            ovh_domain = getattr(_s, 'OVH_DOMAIN', 'cnt-so.info')
            ovh_list_email = ', '.join(f'{n}@{ovh_domain}' for n in list_names)
            try:
                from cms.ovh_client import get_subscribers
                nb_subscribers = sum(len(get_subscribers(n)) for n in list_names)
            except Exception:
                nb_subscribers = None
        else:
            ovh_list_email = None
            nb_subscribers = Subscriber.objects.filter(site=site, is_active=True).count()

        return render(request, 'content/newsletter_send.html', {
            'newsletter': newsletter,
            'nb_subscribers': nb_subscribers,
            'ovh_list_email': ovh_list_email,
        })

    def post(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.error(request, 'Newsletter déjà envoyée.')
            return redirect('/cms/snippets/content/newsletter/')
        refus = self._refus_si_newsletter_coupee(request, newsletter)
        if refus:
            return refus

        mode = request.POST.get('mode', 'send')
        # Les articles pendent désormais à une rubrique : on remet la liste à
        # plat pour l'annoter d'URLs absolues, `par_rubrique` la regroupe après.
        articles = newsletter.articles_a_plat()
        site_url = request.build_absolute_uri('/')
        _annotate_image_urls(articles, site_url)

        if mode == 'test':
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            test_email = request.POST.get('test_email', '').strip()
            if not test_email:
                messages.error(request, 'Adresse e-mail de test manquante.')
                return redirect(f'/cms/newsletter/{pk}/envoyer/')
            try:
                validate_email(test_email)
            except DjangoValidationError:
                messages.error(request, 'Adresse e-mail de test invalide.')
                return redirect(f'/cms/newsletter/{pk}/envoyer/')
            # L'aperçu doit montrer le lien que les destinataires recevront.
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:newsletter_desabonnement')
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'groupes': newsletter.par_rubrique(articles),
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'is_preview': True,
            }, request=request)
            try:
                msg = EmailMultiAlternatives(
                    subject=f"[TEST] {newsletter.title}",
                    body=f"[TEST] {newsletter.title}\n\n{newsletter.intro}",
                    from_email=None,
                    to=[test_email],
                    reply_to=destinataire_de_reponse(),
                )
                msg.attach_alternative(html_body, 'text/html')
                msg.send()
                messages.success(request, f'E-mail de test envoyé à {test_email}.')
            except Exception as e:
                messages.error(request, f'Erreur lors de l\'envoi : {e}')
            return redirect(f'/cms/newsletter/{pk}/envoyer/')

        from django.conf import settings as django_settings

        site = newsletter.site
        list_names = _ovh_list_names(site)

        if list_names:
            # ── Envoi via liste(s) OVH — un e-mail par liste ──────────────────
            ovh_domain = getattr(django_settings, 'OVH_DOMAIN', 'cnt-so.info')
            site_slug = (site.legacy_site_slug or site.slug) if site else ''
            # Un message unique part pour toute la liste : pas de jeton par
            # destinataire, donc pas de lien personnalisé. La page de
            # désabonnement demande l'adresse. Elle pointait auparavant vers
            # l'inscription, une vue en POST seul qui répondait 405 : le lien
            # « Se désabonner » de chaque newsletter menait à une erreur.
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:site_newsletter_desabonnement', args=[site_slug])
                if site_slug else reverse('content:newsletter_desabonnement')
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'groupes': newsletter.par_rubrique(articles),
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'is_preview': False,
            }, request=request)
            text_body = _corps_texte(newsletter, articles, unsubscribe_url)

            sent_lists = []
            failed = []
            for list_name in list_names:
                list_email = f'{list_name}@{ovh_domain}'
                try:
                    msg = EmailMultiAlternatives(
                        subject=newsletter.title,
                        body=text_body,
                        from_email=None,
                        to=[list_email],
                        reply_to=destinataire_de_reponse(),
                    )
                    # Uniquement l'URL : l'adresse « <liste>-unsubscribe@ »
                    # annoncée jusqu'ici est une convention Mailman, non
                    # vérifiée chez OVH. Un bouton « Se désabonner » qui échoue
                    # en silence renvoie le lecteur vers « indésirable ».
                    msg.extra_headers['List-Unsubscribe'] = f'<{unsubscribe_url}>'
                    msg.attach_alternative(html_body, 'text/html')
                    msg.send()
                    sent_lists.append(list_name)
                except Exception as e:
                    failed.append(f'{list_email} ({e})')

            if not sent_lists:
                messages.error(request, f'Erreur lors de l\'envoi : {" ; ".join(failed)}')
                return redirect(request.path)

            sent_count = 0
            for list_name in sent_lists:
                try:
                    from cms.ovh_client import get_subscribers
                    sent_count += len(get_subscribers(list_name))
                except Exception:
                    pass

            newsletter.status = 'sent'
            newsletter.sent_at = timezone.now()
            newsletter.sent_by = request.user
            newsletter.sent_count = sent_count
            newsletter.save(update_fields=['status', 'sent_at', 'sent_by', 'sent_count'])
            sent_emails = ', '.join(f'{n}@{ovh_domain}' for n in sent_lists)
            messages.success(request, f'Newsletter envoyée à {sent_emails} ({sent_count} abonné(s) OVH).')
            if failed:
                messages.warning(request, f'Échec pour : {" ; ".join(failed)}')
            return redirect('/cms/snippets/content/newsletter/')

        # ── Envoi direct abonné par abonné (fallback sans liste OVH) ─────────
        subscribers = list(Subscriber.objects.filter(site=site, is_active=True))
        if not subscribers:
            messages.warning(request, 'Aucun abonné actif pour ce site.')
            return redirect('/cms/snippets/content/newsletter/')

        sent = 0
        errors = 0
        delay = getattr(django_settings, 'NEWSLETTER_SEND_DELAY', 0)

        for subscriber in subscribers:
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:newsletter_unsubscribe', args=[subscriber.token])
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'groupes': newsletter.par_rubrique(articles),
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'subscriber': subscriber,
                'is_preview': False,
            }, request=request)
            text_body = _corps_texte(newsletter, articles, unsubscribe_url)
            try:
                msg = EmailMultiAlternatives(
                    subject=newsletter.title,
                    body=text_body,
                    from_email=None,
                    to=[subscriber.email],
                    reply_to=destinataire_de_reponse(),
                )
                msg.extra_headers['List-Unsubscribe'] = f'<{unsubscribe_url}>'
                msg.attach_alternative(html_body, 'text/html')
                msg.send()
                sent += 1
                if delay:
                    time.sleep(delay)
            except Exception:
                errors += 1

        newsletter.status = 'sent'
        newsletter.sent_at = timezone.now()
        newsletter.sent_by = request.user
        newsletter.sent_count = sent
        newsletter.save(update_fields=['status', 'sent_at', 'sent_by', 'sent_count'])

        if errors:
            messages.warning(request, f'Envoyée à {sent} abonné(s). {errors} erreur(s).')
        else:
            messages.success(request, f'Newsletter envoyée à {sent} abonné(s).')
        return redirect('/cms/snippets/content/newsletter/')


class SubscriberExportView(WagtailSyndicatRequiredMixin, View):
    """Export CSV des abonnés actifs du site courant."""

    def get(self, request):
        current_site = get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('/cms/snippets/content/subscriber/')
        subscribers = Subscriber.objects.filter(site=current_site, is_active=True).order_by('email')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="abonnes-{current_site.slug}.csv"'
        response.write('﻿')
        writer = csv.writer(response)
        writer.writerow(['email', 'nom', 'date_inscription'])
        for s in subscribers:
            writer.writerow([s.email, s.name, s.subscribed_at.strftime('%d/%m/%Y')])
        return response
