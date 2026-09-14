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
import re

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


NOM_LISTE_OVH = re.compile(r'^[a-z0-9][a-z0-9._-]{0,99}$')


def _listes_confederales() -> set:
    from cms.models import SectionPage
    principal = SectionPage.objects.filter(slug='principal').first()
    noms = {principal.ovh_mailing_list, principal.ovh_liste_inscription} if principal else set()
    return {n.strip() for champ in noms if champ for n in champ.split(',') if n.strip()}


def _sync_listes_internes(email: str, demande: dict) -> dict:
    """Inscrit à — ou retire de — les listes de travail internes d'un syndicat.

    Ce ne sont pas des newsletters : aucune ligne `Subscriber`, qui les ferait
    passer pour un consentement à une lettre. cnt-adhesion nomme les listes ;
    on n'accepte qu'un nom de liste OVH, et jamais une liste de la
    confédération — une erreur de réglage ne doit pas pouvoir y toucher par
    ce chemin. Une panne OVH est rapportée, pas levée : elle ne doit pas faire
    échouer la synchronisation de la lettre confédérale.
    """
    from cms import ovh_client

    inscrire = bool(demande.get('inscrire'))
    confederales = _listes_confederales()
    resultat = {'faites': [], 'refusees': [], 'erreurs': {}}
    for nom in demande.get('listes') or []:
        nom = str(nom).strip().lower()
        if not NOM_LISTE_OVH.match(nom) or nom in confederales:
            resultat['refusees'].append(nom)
            continue
        try:
            if inscrire:
                ovh_client.add_subscriber(nom, email)
            else:
                ovh_client.remove_subscriber(nom, email)
            resultat['faites'].append(nom)
        except Exception as e:
            logger.warning("Liste interne %s (%s) pour %s : %s",
                           nom, 'inscription' if inscrire else 'retrait', email, e)
            resultat['erreurs'][nom] = str(e)[:200]
    return resultat


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
        "syndicat_slug": "paris",
        "listes_internes": {          // facultatif
            "inscrire": true, "listes": ["numerique"]
        }
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

        listes_internes = data.get('listes_internes')
        if isinstance(listes_internes, dict):
            result['listes_internes'] = _sync_listes_internes(email, listes_internes)

        logger.info("Sync newsletter adhesion %s : %s", email, result)
        return JsonResponse({'ok': True, 'result': result})
