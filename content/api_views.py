"""
Endpoints API pour les uploads Editor.js (image et fichier)
et l'intégration cnt-adhesion (newsletter sync).
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

from content.admin_utils import WagtailLoginRequiredMixin
from content.models import Media, Subscriber

logger = logging.getLogger(__name__)

# Taille max : 10 Mo images, 20 Mo fichiers
MAX_IMAGE_SIZE = getattr(settings, 'MAX_IMAGE_UPLOAD_SIZE', 10 * 1024 * 1024)
MAX_FILE_SIZE = getattr(settings, 'MAX_FILE_UPLOAD_SIZE', 20 * 1024 * 1024)

# Signatures magic bytes → type MIME attendu
_IMAGE_MAGIC = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # vérification partielle, suffisante
}

# SVG intentionnellement exclu : peut contenir du JavaScript
_ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

_ALLOWED_FILE_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/zip',
}


def _verify_image_magic(file_obj):
    """Vérifie les magic bytes du fichier pour confirmer le type image."""
    header = file_obj.read(12)
    file_obj.seek(0)
    for magic, mime in _IMAGE_MAGIC.items():
        if header.startswith(magic):
            return mime
    return None


class ImageUploadView(WagtailLoginRequiredMixin, View):
    """Endpoint pour Editor.js et l'image mise en avant."""

    def post(self, request):
        image = request.FILES.get('image')
        if not image:
            return JsonResponse({'success': 0, 'message': 'Aucun fichier reçu.'})

        if image.size > MAX_IMAGE_SIZE:
            return JsonResponse({'success': 0, 'message': 'Fichier trop volumineux (max 10 Mo).'})

        # Vérification double : Content-Type déclaré + magic bytes réels
        if image.content_type not in _ALLOWED_IMAGE_TYPES:
            return JsonResponse({'success': 0, 'message': 'Type de fichier non autorisé.'})

        detected = _verify_image_magic(image)
        if detected is None:
            return JsonResponse({'success': 0, 'message': 'Fichier non reconnu comme image valide.'})

        media = Media.objects.create(
            title=image.name,
            file=image,
            mime_type=detected,
        )
        return JsonResponse({
            'success': 1,
            'file': {
                'url': request.build_absolute_uri(media.file.url),
                'id': media.id,
            },
        })


class FileUploadView(WagtailLoginRequiredMixin, View):
    """Endpoint pour l'upload de fichiers (PDF, doc…) depuis FileTool."""

    def post(self, request):
        f = request.FILES.get('file')
        if not f:
            return JsonResponse({'success': 0, 'message': 'Aucun fichier reçu.'})

        if f.size > MAX_FILE_SIZE:
            return JsonResponse({'success': 0, 'message': 'Fichier trop volumineux (max 20 Mo).'})

        if f.content_type not in _ALLOWED_FILE_TYPES:
            return JsonResponse({'success': 0, 'message': 'Type de fichier non autorisé.'})

        media = Media.objects.create(
            title=f.name,
            file=f,
            mime_type=f.content_type,
        )
        return JsonResponse({
            'success': 1,
            'file': {
                'url': request.build_absolute_uri(media.file.url),
                'name': f.name,
            },
        })


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
        updated = Subscriber.objects.filter(site=site, email=email).update(is_active=False)
        return 'unsubscribed' if updated else 'noop'


@method_decorator(csrf_exempt, name='dispatch')
class NewsletterSyncView(View):
    """
    Reçoit les préférences newsletter depuis cnt-adhesion.

    POST /api/newsletter/sync/
    Header: X-Webhook-Secret: <hmac-sha256 du body>
    Body JSON: {
        "email": "...",
        "newsletter_conf": true,
        "newsletter_synd": false,
        "syndicat_slug": "paris"
    }

    L'adhésion vaut consentement — pas de double opt-in pour ces abonnés.
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

        newsletter_conf = bool(data.get('newsletter_conf', False))
        newsletter_synd = bool(data.get('newsletter_synd', False))
        syndicat_slug = data.get('syndicat_slug', '')

        result = {}
        result['conf'] = _sync_sub(email, site=None, actif=newsletter_conf)

        if syndicat_slug:
            section = _get_section_page(syndicat_slug)
            if section:
                result['synd'] = _sync_sub(email, site=section, actif=newsletter_synd)
            else:
                result['synd'] = f'section introuvable: {syndicat_slug}'
                logger.warning("SectionPage introuvable pour slug '%s'", syndicat_slug)

        logger.info("Sync newsletter adhesion %s : %s", email, result)
        return JsonResponse({'ok': True, 'result': result})
