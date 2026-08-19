"""Endpoint API du webhook cnt-adhesion (synchronisation newsletter).

Les endpoints d'upload d'Editor.js ont été retirés le 01/08/2026 : l'éditeur a
disparu avec l'app `redaction/`, plus aucun client ne les appelait, et ils
acceptaient un téléversement de tout compte connecté sans contrôle de rôle ni
rattachement à un syndicat.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from content.models import Subscriber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intégration cnt-adhesion : sync newsletter
# ---------------------------------------------------------------------------

def _verify_adhesion_signature(request) -> bool:
    secret = getattr(settings, 'ADHESION_WEBHOOK_SECRET', '')
    if not secret:
        logger.warning("ADHESION_WEBHOOK_SECRET non configuré — webhook refusé.")
        return False
    sig = request.headers.get('X-Webhook-Secret', '')
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _get_section_page(slug: str):
    try:
        from cms.models import SectionPage
        from django.db.models import Q
        return SectionPage.objects.filter(Q(slug=slug) | Q(legacy_site_slug=slug)).first()
    except Exception:
        return None


def _sync_sub(email: str, site, actif: bool) -> str:
    # La répercussion vers les listes OVH passe par le signal post_save
    # de cms/apps.py — d'où les save() unitaires plutôt qu'un .update().
    if actif:
        sub, created = Subscriber.objects.get_or_create(
            site=site, email=email,
            defaults={'is_active': True, 'confirmed_at': timezone.now()},
        )
        if not created and not sub.is_active:
            sub.is_active = True
            sub.confirmed_at = timezone.now()
            sub.save(update_fields=['is_active', 'confirmed_at'])
        return 'subscribed' if created else 'updated'
    else:
        updated = 0
        for sub in Subscriber.objects.filter(site=site, email=email):
            sub.is_active = False
            sub.save(update_fields=['is_active'])
            updated += 1
        return 'unsubscribed' if updated else 'noop'


@method_decorator(csrf_exempt, name='dispatch')
class NewsletterSyncView(View):
    """
    Reçoit les préférences newsletter depuis cnt-adhesion.

    POST /api/newsletter/sync/
    Header: X-Webhook-Secret: <hmac-sha256 du body>
    Body JSON: {
        "email": "...",
        "newsletter_conf": true,      // facultatif
        "newsletter_synd": false,     // facultatif
        "syndicat_slug": "paris"
    }

    L'adhésion vaut consentement — pas de double opt-in pour ces abonnés.

    **Une clé absente laisse la liste correspondante inchangée.** Elle valait
    auparavant « désabonne » : cnt-adhesion, qui pousse ses préférences à
    chaque encaissement, réinscrivait donc à la lettre confédérale ceux qui
    s'en étaient retirés par le lien de désinscription — leur sortie tenait
    jusqu'au prélèvement suivant.
    """

    def post(self, request):
        if not _verify_adhesion_signature(request):
            return JsonResponse({'error': 'signature invalide'}, status=403)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON invalide'}, status=400)

        email = data.get('email', '').strip().lower()
        if not email:
            return JsonResponse({'error': 'email manquant'}, status=400)

        newsletter_conf = data.get('newsletter_conf')
        newsletter_synd = data.get('newsletter_synd')
        syndicat_slug = data.get('syndicat_slug', '')

        result = {}
        if newsletter_conf is None:
            result['conf'] = 'inchangé'
        else:
            result['conf'] = _sync_sub(email, site=None, actif=bool(newsletter_conf))

        if syndicat_slug:
            section = _get_section_page(syndicat_slug)
            if section is None:
                result['synd'] = f'section introuvable: {syndicat_slug}'
                logger.warning("SectionPage introuvable pour slug '%s'", syndicat_slug)
            elif newsletter_synd is None:
                result['synd'] = 'inchangé'
            else:
                result['synd'] = _sync_sub(email, site=section,
                                           actif=bool(newsletter_synd))

        logger.info("Sync newsletter adhesion %s : %s", email, result)
        return JsonResponse({'ok': True, 'result': result})
