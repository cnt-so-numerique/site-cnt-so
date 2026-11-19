"""Tout fichier tiré d'un CDN à version figée porte son empreinte `integrity=`.

Défaut réel, trouvé le 27/10/2026 : l'éditeur de menus de l'admin chargeait
SortableJS depuis jsDelivr sans empreinte. Un CDN compromis — ou un paquet npm
republié — aurait exécuté son code dans une session d'administration. Leaflet,
lui, était protégé. Les scripts non versionnés (hCaptcha, Bluesky) changent
sans préavis : une empreinte les casserait, ils ne sont pas concernés.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CDN = re.compile(r'https://(cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)/')
BALISE = re.compile(r'<(script|link)\b[^>]*>', re.IGNORECASE)


class LesFichiersDeCDNPortentLeurEmpreinte(SimpleTestCase):

    def test_chaque_balise_cdn_a_integrity_et_crossorigin(self):
        sans = []
        for gabarit in Path(settings.BASE_DIR, 'templates').rglob('*.html'):
            for balise in BALISE.finditer(gabarit.read_text()):
                texte = balise.group(0)
                if CDN.search(texte) and not ('integrity=' in texte and 'crossorigin' in texte):
                    sans.append(f'{gabarit.relative_to(settings.BASE_DIR)} : {texte}')
        self.assertEqual(sans, [], 'balises CDN sans empreinte')

    def test_chaque_empreinte_a_la_bonne_longueur(self):
        """Défaut réel, trouvé le 15/11/2026 : l'empreinte de leaflet.js était
        tronquée (43 caractères au lieu de 44). Le navigateur refusait le
        fichier et la carte de l'agenda public ne s'est jamais affichée.
        Une empreinte sha256/384/512 décodée fait 32/48/64 octets, pas autre chose."""
        import base64
        tailles = {'sha256': 32, 'sha384': 48, 'sha512': 64}
        fausses = []
        for gabarit in Path(settings.BASE_DIR, 'templates').rglob('*.html'):
            for algo, valeur in re.findall(r'integrity="(sha\d+)-([^"]*)"', gabarit.read_text()):
                try:
                    bonne = len(base64.b64decode(valeur, validate=True)) == tailles.get(algo)
                except ValueError:
                    bonne = False
                if not bonne:
                    fausses.append(f'{gabarit.relative_to(settings.BASE_DIR)} : {algo}-{valeur}')
        self.assertEqual(fausses, [], 'empreintes mal formées')
