"""Répare deux entrées du menu du syndicat Éducation.

Relevé sur les données de PRODUCTION le 03/09/2026, et seulement ce qui est
certain — le reste du menu demande un arbitrage du syndicat.

1. **« Liens CNT-SO » envoie sur une erreur.** Il pointe `https://cnt-so.org`
   en dur, c'est-à-dire l'ancien WordPress, qui rend un **HTTP 500** depuis
   juillet. Un visiteur qui clique tombe sur une page d'erreur.

   Remplacé par `/` — relatif, donc juste dans les deux mondes : aujourd'hui il
   mène à la confédération sur `newsite.cnt-so.org`, et après la bascule DNS il
   y mènera sur `cnt-so.org`. Le pied de page utilise déjà cette forme pour
   « Site confédéral ».

2. **« Rejoindre la CNT-SO » mène au formulaire de contact**
   (`/education/contact/`) alors que la page d'adhésion existe et répond
   (`/education/rejoindre/`). Une entrée qui annonce l'adhésion doit ouvrir la
   porte de l'adhésion — laquelle, depuis le correctif du 02/09, présente le
   message « adhésion en ligne à venir » et propose d'écrire. Le visiteur
   arrive donc au même endroit, mais par la bonne porte et avec le bon message.

Ne touche à RIEN d'autre. Deux entrées restent sans cible — « Textes
officiels » et « Supérieur – Recherche », toutes deux à `#` — mais je ne sais
pas ce qu'elles devaient contenir : c'est au syndicat de le dire.

Usage :
    python manage.py repare_menu_education              # constat seul
    python manage.py repare_menu_education --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# (pk, titre attendu, url actuelle attendue, url voulue)
REPARATIONS = [
    (394, 'Liens CNT-SO', 'https://cnt-so.org', '/'),
    (413, 'Rejoindre la CNT-SO', '/education/contact/', '/education/rejoindre/'),
]


class Command(BaseCommand):
    help = ("Répare « Liens CNT-SO » (pointe l'ancien serveur en panne) et "
            "« Rejoindre la CNT-SO » (mène au contact au lieu de l'adhésion)")

    def add_arguments(self, parser):
        parser.add_argument('--appliquer', action='store_true',
                            help="Écrit en base. Sans ce drapeau, constat seul.")

    def handle(self, *args, **options):
        from content.models import MenuItem

        appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Menu du syndicat Éducation — "
            + ("ÉCRITURE EN BASE" if appliquer else "constat seul (--appliquer pour écrire)")))

        a_faire, ignores = [], []
        for pk, titre, url_attendue, url_voulue in REPARATIONS:
            entree = MenuItem.objects.filter(pk=pk).first()
            if entree is None:
                ignores.append(f"pk={pk} « {titre} » introuvable")
                continue
            # Le titre ET l'URL doivent correspondre : sans ce contrôle, un
            # `pk` réattribué ou une entrée déjà modifiée à la main se ferait
            # écraser en silence.
            if entree.title != titre:
                ignores.append(f"pk={pk} s'appelle « {entree.title} » et non « {titre} » — non touchée")
                continue
            if entree.url == url_voulue:
                ignores.append(f"pk={pk} « {titre} » déjà réparée")
                continue
            if entree.url != url_attendue:
                ignores.append(
                    f"pk={pk} « {titre} » pointe « {entree.url} » et non "
                    f"« {url_attendue} » — modifiée depuis, non touchée")
                continue
            a_faire.append((entree, url_voulue))
            self.stdout.write(
                f"  • « {titre} »\n"
                f"      {entree.url}\n"
                f"    → {url_voulue}")

        for texte in ignores:
            self.stdout.write(self.style.WARNING(f"  ⚠ {texte}"))

        if not a_faire:
            self.stdout.write(self.style.SUCCESS("Rien à faire."))
            return
        if not appliquer:
            self.stdout.write(self.style.NOTICE(
                f"\n{len(a_faire)} réparation(s) — relancer avec --appliquer."))
            return

        with transaction.atomic():
            for entree, url_voulue in a_faire:
                entree.url = url_voulue
                entree.save(update_fields=['url'])
        self.stdout.write(self.style.SUCCESS(f"Appliqué : {len(a_faire)} entrée(s)."))
