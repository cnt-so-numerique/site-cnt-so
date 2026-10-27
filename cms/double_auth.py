"""Double authentification de /cms/ et /admin/ (remplace wagtail-2fa, 27/10/2026).

wagtail-2fa n'était plus maintenu et empêchait de passer à Wagtail 8. Ce module
garde django-otp, qui l'est, et n'en reprend que ce qui sert ici.

La règle tient en une phrase : une session DOIT donner son code si le compte a
au moins un téléphone enregistré, ou s'il est superutilisateur
(`settings.DOUBLE_AUTH_OBLIGATOIRE` : `'superutilisateurs'` ou `'tous'` ;
`'personne'` pendant les tests). Tant
qu'elle ne l'a pas fait, elle n'entre ni dans /cms/ ni dans /admin/, et elle
est ANONYME partout ailleurs. wagtail-2fa laissait deux trous que cette règle
referme : `/admin/` s'ouvrait au seul mot de passe, et une session à demi
connectée voyait les sites en test réservés aux rédacteurs.

Les comptes des syndicats sont souvent partagés : chaque personne y enregistre
SON téléphone, sous son nom, et on retire le sien sans toucher aux autres.
D'où deux écarts avec django-otp :

- la limitation des essais est par compte (`EchecsDoubleAuth`) et non par
  appareil : `django_otp.match_token` essaie le code sur chaque téléphone, et
  une connexion réussie avec l'un compterait comme un échec sur les autres ;
- le code de confirmation d'un nouveau téléphone est vérifié sans
  `TOTPDevice.verify_token`, qui ENREGISTRE l'appareil — confirmé — même
  quand le code est faux.

Les codes de secours n'existent qu'à côté d'un téléphone : retirer le dernier
les efface, et le compte redevient un compte à mot de passe seul.
"""

import base64
import time
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django_otp import devices_for_user, login as otp_login
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from .models import EchecsDoubleAuth

#: Nombre de codes de secours remis d'un coup.
NB_CODES_SECOURS = 10

#: Attente maximale entre deux essais après une série de codes faux.
ATTENTE_MAX = timedelta(minutes=15)

#: Pages permises à une session qui n'a pas encore donné son code.
PAGES_LIBRES = {
    'wagtailadmin_login', 'wagtailadmin_logout',
    'wagtailadmin_password_reset', 'wagtailadmin_password_reset_done',
    'wagtailadmin_password_reset_confirm', 'wagtailadmin_password_reset_complete',
    'wagtailadmin_javascript_catalog', 'wagtailadmin_sprite',
    'cms_double_auth_code', 'admin:login', 'admin:logout',
}

#: Pages permises en plus quand le compte n'a encore aucun téléphone.
PAGES_ENROLEMENT = {'cms_double_auth_ajouter'}


# ── La règle ──────────────────────────────────────────────────────────────────

def telephones(user):
    """Les téléphones enregistrés (confirmés) du compte."""
    return TOTPDevice.objects.devices_for_user(user, confirmed=True)


def est_obligatoire(user):
    """Le compte doit-il s'enrôler, même sans téléphone ?"""
    reglage = getattr(settings, 'DOUBLE_AUTH_OBLIGATOIRE', 'superutilisateurs')
    if reglage == 'tous':
        return user.is_superuser or user.has_perm('wagtailadmin.access_admin')
    if reglage == 'superutilisateurs':
        return user.is_superuser
    return False  # 'personne' : tests seulement (refusé en prod par settings.py)


def doit_donner_son_code(user):
    """La session de ce compte doit-elle être vérifiée par un code ?"""
    if not user.is_authenticated:
        return False
    return est_obligatoire(user) or telephones(user).exists()


def _anonyme():
    utilisateur = AnonymousUser()
    utilisateur.is_verified = lambda: False
    utilisateur.otp_device = None
    return utilisateur


def _nom_de_page(request):
    try:
        correspondance = resolve(request.path_info)
    except Resolver404:
        return None
    return correspondance.view_name


class DoubleAuthMiddleware:
    """Applique la règle à chaque requête. À placer après `OTPMiddleware`."""

    PREFIXES_ADMIN = ('/cms/', '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_verified() and doit_donner_son_code(user):
            if not request.path_info.startswith(self.PREFIXES_ADMIN):
                request.user = _anonyme()
            else:
                reponse = self._aiguiller(request, user)
                if reponse is not None:
                    return reponse
        return self.get_response(request)

    @staticmethod
    def _aiguiller(request, user):
        a_un_telephone = telephones(user).exists()
        page = _nom_de_page(request)
        if page in PAGES_LIBRES or (not a_un_telephone and page in PAGES_ENROLEMENT):
            return None
        cible = 'cms_double_auth_code' if a_un_telephone else 'cms_double_auth_ajouter'
        suite = request.get_full_path() if request.method == 'GET' else ''
        url = reverse(cible)
        if suite:
            url += '?' + urlencode({'next': suite})
        return HttpResponseRedirect(url)


# ── Limitation des essais, par compte ─────────────────────────────────────────

def attente_restante(user):
    """Temps à attendre avant le prochain essai (`timedelta` nul si aucun)."""
    echecs = EchecsDoubleAuth.objects.filter(user=user).first()
    if not echecs or not echecs.nombre or not echecs.dernier:
        return timedelta(0)
    attente = min(timedelta(seconds=2 ** (echecs.nombre - 1)), ATTENTE_MAX)
    return max(echecs.dernier + attente - timezone.now(), timedelta(0))


def _noter_echec(user):
    echecs, _ = EchecsDoubleAuth.objects.get_or_create(user=user)
    echecs.nombre += 1
    echecs.dernier = timezone.now()
    echecs.save()


def verifier_code(user, code):
    """L'appareil qui accepte `code` (téléphone ou code de secours), ou None.

    L'appelant vérifie `attente_restante` d'abord : ici, on essaie toujours.
    """
    code = ''.join(code.split()).lower()
    with transaction.atomic():
        for appareil in devices_for_user(user, for_verify=True):
            if appareil.verify_token(code):
                EchecsDoubleAuth.objects.filter(user=user).delete()
                return appareil
    _noter_echec(user)
    return None


# ── Téléphones et codes de secours ────────────────────────────────────────────

def code_valide_pour_cle(cle_hex, code):
    """Le code donné correspond-il à cette clé, sans rien enregistrer ?"""
    try:
        code = int(''.join(code.split()))
    except ValueError:
        return False
    totp = TOTP(bytes.fromhex(cle_hex), step=30, t0=0, digits=6, drift=0)
    totp.time = time.time()
    return totp.verify(code, tolerance=1)


def nouveaux_codes_de_secours(user):
    """Remplace les codes de secours du compte ; renvoie les nouveaux, en clair."""
    appareil, _ = StaticDevice.objects.get_or_create(
        user=user, defaults={'name': 'Codes de secours'})
    appareil.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(NB_CODES_SECOURS)]
    StaticToken.objects.bulk_create(StaticToken(device=appareil, token=c) for c in codes)
    return codes


def codes_de_secours_restants(user):
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def retirer_telephone(appareil):
    """Retire un téléphone ; avec le dernier partent les codes de secours."""
    user = appareil.user
    appareil.delete()
    if not telephones(user).exists():
        StaticDevice.objects.filter(user=user).delete()
        EchecsDoubleAuth.objects.filter(user=user).delete()


def qr_code_svg(url):
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    tampon = BytesIO()
    image.save(tampon)
    svg = tampon.getvalue().decode()
    return mark_safe(svg[svg.index('<svg'):])


def _cle_lisible(cle_hex):
    """La clé en base32, par groupes de quatre, pour la saisie à la main."""
    b32 = base64.b32encode(bytes.fromhex(cle_hex)).decode().rstrip('=')
    return ' '.join(b32[i:i + 4] for i in range(0, len(b32), 4))


# ── Formulaires ───────────────────────────────────────────────────────────────

class FormulaireCode(forms.Form):
    code = forms.CharField(
        label="Code", max_length=32, strip=True,
        help_text="Les 6 chiffres affichés par l'application, ou un code de secours.",
        widget=forms.TextInput(attrs={
            'autofocus': True, 'autocomplete': 'one-time-code', 'inputmode': 'text',
            'autocapitalize': 'off', 'spellcheck': 'false'}),
    )


class FormulaireTelephone(forms.Form):
    nom = forms.CharField(
        label="Nom du téléphone", max_length=64,
        help_text="Pour le reconnaître dans la liste : « téléphone de Sam », par exemple.",
    )
    mot_de_passe = forms.CharField(
        label="Votre mot de passe actuel", widget=forms.PasswordInput,
        help_text="Par précaution : il faut le mot de passe pour ajouter un téléphone.",
    )
    code = forms.CharField(
        label="Code affiché par l'application", max_length=16,
        widget=forms.TextInput(attrs={'autocomplete': 'one-time-code', 'inputmode': 'numeric'}),
    )

    def __init__(self, *args, request, cle_hex, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.cle_hex = cle_hex

    def clean_mot_de_passe(self):
        mot_de_passe = self.cleaned_data['mot_de_passe']
        user = self.request.user
        if authenticate(self.request, username=user.get_username(), password=mot_de_passe) != user:
            raise forms.ValidationError("Ce n'est pas le bon mot de passe.")
        return mot_de_passe

    def clean_code(self):
        code = self.cleaned_data['code']
        if not code_valide_pour_cle(self.cle_hex, code):
            raise forms.ValidationError(
                "Ce code ne correspond pas. Vérifiez que l'heure du téléphone est à "
                "l'heure, puis tapez le code affiché en ce moment.")
        return code


# ── Vues ──────────────────────────────────────────────────────────────────────

def _suite_sure(request):
    suite = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return suite
    return reverse('wagtailadmin_home')


@method_decorator([never_cache, sensitive_post_parameters()], name='dispatch')
class CodeView(View):
    """La page du code, entre le mot de passe et l'admin."""

    gabarit = 'cms/double_auth/code.html'

    def _rendre(self, request, form, attente=None):
        return render(request, self.gabarit, {
            'form': form, 'next': _suite_sure(request), 'attente': attente,
        })

    def get(self, request):
        if request.user.is_verified() or not telephones(request.user).exists():
            return HttpResponseRedirect(_suite_sure(request))
        return self._rendre(request, FormulaireCode())

    def post(self, request):
        user = request.user
        if not telephones(user).exists():
            return HttpResponseRedirect(_suite_sure(request))
        form = FormulaireCode(request.POST)
        attente = attente_restante(user)
        if attente:
            secondes = int(attente.total_seconds()) + 1
            form.is_valid()
            form.add_error(None, f"Trop de codes faux : réessayez dans {secondes} s.")
            return self._rendre(request, form, attente=secondes)
        if form.is_valid():
            appareil = verifier_code(user, form.cleaned_data['code'])
            if appareil is not None:
                otp_login(request, appareil)
                if isinstance(appareil, StaticDevice):
                    restants = codes_de_secours_restants(user)
                    messages.warning(request, f"Code de secours utilisé : il vous en reste "
                                              f"{restants}. Pensez à en générer de nouveaux.")
                return HttpResponseRedirect(_suite_sure(request))
            form.add_error('code', "Ce code n'est pas bon, ou il a déjà servi.")
        return self._rendre(request, form)


@method_decorator([never_cache, sensitive_post_parameters()], name='dispatch')
class AjouterTelephoneView(View):
    """Enregistrer un téléphone : QR code, nom, mot de passe, code de confirmation.

    La clé vit dans la session tant que le téléphone n'est pas confirmé : aucun
    appareil n'existe en base avant que le bon code ait été tapé. Elle ne change
    qu'après un succès : pendant l'enrôlement forcé, les requêtes de fond de
    l'admin (`current-site-fragment`…) sont renvoyées ici, et une clé tirée à
    chaque affichage remplaçait celle que la personne venait de scanner.
    """

    gabarit = 'cms/double_auth/ajouter.html'
    CLE_SESSION = 'double_auth_cle_en_cours'

    def _cle(self, request):
        if self.CLE_SESSION not in request.session:
            request.session[self.CLE_SESSION] = random_hex(20)
        return request.session[self.CLE_SESSION]

    def _rendre(self, request, form, cle_hex):
        apercu = TOTPDevice(user=request.user, key=cle_hex)
        return render(request, self.gabarit, {
            'form': form,
            'qr_code': qr_code_svg(apercu.config_url),
            'cle_lisible': _cle_lisible(cle_hex),
            'premier': not telephones(request.user).exists(),
            'next': _suite_sure(request),
            # Enrôlement forcé : pas de menu, dont chaque lien ramènerait ici.
            'parent': ('wagtailadmin/base.html' if request.user.is_verified()
                       else 'cms/double_auth/sans_menu.html'),
        })

    def get(self, request):
        cle_hex = self._cle(request)
        return self._rendre(request, FormulaireTelephone(request=request, cle_hex=cle_hex), cle_hex)

    def post(self, request):
        cle_hex = self._cle(request)
        form = FormulaireTelephone(request.POST, request=request, cle_hex=cle_hex)
        if not form.is_valid():
            return self._rendre(request, form, cle_hex)
        premier = not telephones(request.user).exists()
        appareil = TOTPDevice.objects.create(
            user=request.user, name=form.cleaned_data['nom'], key=cle_hex, confirmed=True)
        del request.session[self.CLE_SESSION]
        if not request.user.is_verified():
            otp_login(request, appareil)
        if premier:
            # Premier téléphone : les codes de secours viennent avec, d'office.
            return render(request, 'cms/double_auth/codes_secours.html', {
                'codes': nouveaux_codes_de_secours(request.user),
                'premier': True,
                'next': _suite_sure(request),
            })
        messages.success(request, f"Téléphone « {appareil.name} » ajouté.")
        return HttpResponseRedirect(reverse('cms_double_auth'))


class AppareilsView(View):
    """Les téléphones d'un compte : le sien, ou celui d'un autre pour un superutilisateur."""

    def get(self, request, user_id=None):
        compte = self._compte(request, user_id)
        if compte is None:
            return HttpResponseForbidden("Réservé aux superutilisateurs.")
        return render(request, 'cms/double_auth/appareils.html', {
            'compte': compte,
            'le_mien': compte == request.user,
            'telephones': telephones(compte).order_by('created_at'),
            'codes_restants': codes_de_secours_restants(compte),
            'obligatoire': est_obligatoire(compte),
        })

    @staticmethod
    def _compte(request, user_id):
        if user_id is None or int(user_id) == request.user.pk:
            return request.user
        if not request.user.is_superuser:
            return None
        return get_object_or_404(get_user_model(), pk=user_id)


class RetirerTelephoneView(View):
    def post(self, request, pk):
        appareil = get_object_or_404(TOTPDevice, pk=pk, confirmed=True)
        compte = appareil.user
        if compte != request.user and not request.user.is_superuser:
            return HttpResponseForbidden("Réservé aux superutilisateurs.")
        retirer_telephone(appareil)
        messages.success(request, f"Téléphone « {appareil.name} » retiré.")
        if compte == request.user:
            return HttpResponseRedirect(reverse('cms_double_auth'))
        return HttpResponseRedirect(reverse('cms_double_auth_compte', args=[compte.pk]))

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])


@method_decorator(never_cache, name='dispatch')
class CodesSecoursView(View):
    """Génère de nouveaux codes de secours (les anciens cessent de marcher)."""

    def post(self, request):
        if not telephones(request.user).exists():
            return HttpResponseRedirect(reverse('cms_double_auth'))
        return render(request, 'cms/double_auth/codes_secours.html', {
            'codes': nouveaux_codes_de_secours(request.user),
            'premier': False,
            'next': reverse('cms_double_auth'),
        })

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])
