"""Le lanceur de tests du projet : parallèle par défaut.

La suite a passé les mille tests et tournait en près de cinq minutes sur un
seul cœur, alors que la machine en a douze. Personne ne relance volontiers une
suite de cinq minutes ; on finit par ne plus la lancer du tout, ce qui coûte
bien plus cher que le temps gagné.

Mesuré le 18/08/2026 : 1 061 tests en 290 s sur un cœur, 83 s sur huit. Au-delà
de huit, le gain devient nul (80 s sur douze) : la répartition se fait par
classe de test, et les plus grosses classes bornent le temps total.

`--parallel 1` reste possible pour déboguer : le parallélisme brouille l'ordre
des sorties et empêche `pdb`.

⚠️ **`tblib` est indispensable** (requirements.txt). Sans lui, Django ne sait
pas rapatrier la trace d'un échec depuis un processus fils : la suite entière
s'arrête sur un `TypeError: cannot pickle 'traceback' object` qui ne nomme
même pas le test fautif. Un seul test rouge devenait ainsi indéboguable sans
repasser cinq minutes en séquentiel — constaté le 26/08/2026.
"""

import os

from django.test.runner import DiscoverRunner


#: Au-delà, on paie la mise en place d'une base par processus sans rien gagner.
PROCESSUS_MAX = 8


class RunnerParallele(DiscoverRunner):

    def __init__(self, *args, parallel=0, **kwargs):
        if not parallel:
            parallel = min(os.cpu_count() or 1, PROCESSUS_MAX)
        super().__init__(*args, parallel=parallel, **kwargs)
