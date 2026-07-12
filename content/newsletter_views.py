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

from content.admin_utils import WagtailChefRequiredMixin, get_current_site_for_view
from content.models import Newsletter, Subscriber


def _ovh_list_names(site):
    """Noms des listes OVH du syndicat (champ multi-valeurs, séparées par des virgules)."""
    raw = getattr(site, 'ovh_mailing_list', '') if site else ''
    return [n.strip() for n in (raw or '').split(',') if n.strip()]


def _annotate_image_urls(articles, site_url):
    """Pose na.image_url en URL absolue (any_image_url peut être relative ou legacy absolue)."""
    base = site_url.rstrip('/')
    for na in articles:
        img = na.article.any_image_url
        if img and not img.startswith('http'):
            img = base + img
        na.image_url = img


class NewsletterSendView(WagtailChefRequiredMixin, View):
    """Confirmation puis envoi de la newsletter."""

    def _get_newsletter(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = get_current_site_for_view(request)
        if current_site and newsletter.site != current_site:
            raise PermissionDenied
        return newsletter

    def get(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.error(request, 'Newsletter déjà envoyée.')
            return redirect('/cms/snippets/content/newsletter/')

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

        mode = request.POST.get('mode', 'send')
        articles = list(
            newsletter.newsletter_articles.select_related('article__featured_image').order_by('order')
        )
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
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:newsletter_unsubscribe', args=['00000000-0000-0000-0000-000000000000'])
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'newsletter_articles': articles,
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
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:site_newsletter_subscribe', args=[site_slug])
                if site_slug else reverse('content:newsletter_subscribe')
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'newsletter_articles': articles,
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'is_preview': False,
            }, request=request)
            text_body = (
                f"{newsletter.title}\n\n{newsletter.intro}\n\n"
                + "\n".join(
                    f"- {na.article.title}: {site_url.rstrip('/')}{na.article.get_absolute_url()}"
                    for na in articles
                )
                + f"\n\nGérer votre abonnement : {unsubscribe_url}"
            )

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
                    )
                    msg.extra_headers['List-Unsubscribe'] = (
                        f'<mailto:{list_name}-unsubscribe@{ovh_domain}>'
                    )
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
                'newsletter_articles': articles,
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'subscriber': subscriber,
                'is_preview': False,
            }, request=request)
            text_body = f"{newsletter.title}\n\n{newsletter.intro}\n\n" + "\n".join(
                f"- {na.article.title}: {site_url.rstrip('/')}{na.article.get_absolute_url()}"
                for na in articles
            ) + f"\n\nSe désabonner : {unsubscribe_url}"
            try:
                msg = EmailMultiAlternatives(
                    subject=newsletter.title,
                    body=text_body,
                    from_email=None,
                    to=[subscriber.email],
                )
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


class SubscriberExportView(WagtailChefRequiredMixin, View):
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
