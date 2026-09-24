"""Statistiques de fréquentation dans /cms/, sans cookie ni bandeau.

Le rapport est produit chaque heure sur le serveur par GoAccess, à partir des
journaux nginx (timer systemd `cntso-stats`) : aucun script dans les pages,
aucun cookie, aucune donnée confiée à un tiers. Les IP sont anonymisées et le
panneau des visiteurs par IP est retiré à la génération.

Ces vues ne font que servir le fichier. Il vit hors du dépôt et hors de
`media/` (qui est public) : `settings.STATS_RAPPORT`.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from content.admin_utils import WagtailChefRequiredMixin


def _rapport():
    return Path(settings.STATS_RAPPORT)


class StatistiquesView(WagtailChefRequiredMixin, View):
    """La page d'admin : le rapport dans un cadre, ou l'explication de son absence."""

    def get(self, request):
        return render(request, 'cms/statistiques.html', {
            'disponible': _rapport().is_file(),
        })


class RapportStatistiquesView(WagtailChefRequiredMixin, View):
    """Le rapport GoAccess brut, chargé dans le cadre de la page ci-dessus.

    Servi par Django et non par nginx : l'accès reste soumis à la connexion
    et au rôle, comme le reste de /cms/.

    Mis en bac à sable (`sandbox allow-scripts`) : le rapport recopie des
    chaînes choisies par les visiteurs (adresses, navigateurs, provenances),
    et GoAccess a déjà connu des failles XSS. Sans bac à sable, un rapport
    piégé tournerait sur l'origine de /cms/, avec la session d'un chef. Ici il
    s'exécute dans une origine opaque, sans cookie ni accès à l'admin.
    """

    def get(self, request):
        try:
            contenu = _rapport().read_bytes()
        except OSError:
            return HttpResponse('Rapport indisponible.', status=404,
                                content_type='text/plain; charset=utf-8')
        reponse = HttpResponse(contenu, content_type='text/html; charset=utf-8')
        reponse['Content-Security-Policy'] = 'sandbox allow-scripts'
        return reponse
