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
