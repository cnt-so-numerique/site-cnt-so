"""Une seule graphie inclusive dans les noms de catégorie : le point médian.

Le même mot s'écrivait de six façons, relevées en production le 01/09/2026 :

    travailleur·euses      point médian     (STUCS)
    Travailleur.euse.s     points           (STAA)
    Travailleurs.euses     points, avec s   (sans-papiers)
    travailleurs.euses     points, minuscule (plateformes)
    Travailleur-euses      trait d'union    (de la terre)
    salarié.e.s            points           (13, plateformes)

Aucune n'est fautive : ce sont des conventions concurrentes. Elles cohabitaient,
et la liste des catégories donnait à voir un syndicat hésitant sur sa propre
façon d'écrire. Arbitrage d'Arnaud le 01/09/2026 : **le point médian partout**,
celui que le STUCS emploie pour se nommer lui-même.

**Portée volontairement étroite : on ne change que le séparateur.**
« Livreurs » et « Artistes » restent au masculin, et « Auteur.e.s » devient
« Auteur·es » et non « auteur·ices » : passer d'un mot à un autre est un choix
éditorial distinct, qui n'a pas été fait. Seule exception assumée, la casse de
« des Travailleur.euse.s » qui devient « des travailleur·euses » — c'est la
même construction que le STUCS, à deux lignes d'écart dans la même liste.

**Aucun slug ne change**, donc aucune adresse ne bouge et aucun lien ne casse :
c'est l'étiquette affichée, et elle seule.

Une table explicite plutôt qu'une expression régulière : huit noms se relisent,
une regex sur des noms propres se relit mal et abîme en silence. La commande
signale tout nom attendu qu'elle ne trouve pas, plutôt que de le passer sous
silence.

Usage :
    python manage.py harmonise_ecriture_inclusive              # constat seul
    python manage.py harmonise_ecriture_inclusive --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction


# (section_slug, nom actuel) → nom voulu
RENOMMAGES = {
    ('13', 'Livreurs et salarié.e.s des plateformes'):
        'Livreurs et salarié·es des plateformes',
    ('auvergne', 'Artistes et Auteur.e.s'):
        'Artistes et Auteur·es',
    ('auvergne', 'Livreurs & travailleurs.euses des plateformes'):
        'Livreurs & travailleur·euses des plateformes',
    ('principal', 'Livreurs & travailleurs.euses des plateformes'):
        'Livreurs & travailleur·euses des plateformes',
    ('principal', 'Syndicat des Travailleur.euse.s Artistes-Auteurs (STAA)'):
        'Syndicat des travailleur·euses Artistes-Auteurs (STAA)',
    ('principal', 'Travailleur-euses de la terre'):
        'Travailleur·euses de la terre',
    ('principal', 'Travailleurs.euses sans-papiers'):
        'Travailleur·euses sans-papiers',
    ('principal', 'Étudiant-es'):
        'Étudiant·es',
}


class Command(BaseCommand):
    help = ("Uniformise l'écriture inclusive des noms de catégorie sur le "
            "point médian (les slugs ne changent pas)")

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit en base. Sans ce drapeau, la commande n'affiche que ce "
                 "qu'elle ferait.")

    def handle(self, *args, **options):
        from cms.models import CmsCategory

        appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Écriture inclusive des catégories — "
            + ("ÉCRITURE EN BASE" if appliquer else
               "constat seul (--appliquer pour écrire)")))

        a_faire, absents, deja = [], [], []
        for (site, ancien), nouveau in sorted(RENOMMAGES.items()):
            categorie = CmsCategory.objects.filter(
                section_slug=site, name=ancien).first()
            if categorie is not None:
                a_faire.append((categorie, ancien, nouveau))
            elif CmsCategory.objects.filter(section_slug=site, name=nouveau).exists():
                deja.append(f'{site} : « {nouveau} »')
            else:
                absents.append(f'{site} : « {ancien} » introuvable')

        for categorie, ancien, nouveau in a_faire:
            self.stdout.write(
                f'  • {categorie.section_slug:10} « {ancien} »\n'
                f'    {"":12}→ « {nouveau} »   (slug « {categorie.slug} » inchangé)')
        for texte in deja:
            self.stdout.write(f'  · déjà au point médian — {texte}')
        for texte in absents:
            self.stdout.write(self.style.WARNING(f'  ⚠ {texte}'))

        # Ce qui porte encore une graphie concurrente et n'est pas dans la table :
        # une catégorie créée depuis, ou un nom que j'ai mal relevé.
        restants = [
            c for c in CmsCategory.objects.all()
            if ('.e' in c.name or '-es' in c.name or '.euse' in c.name)
            and (c.section_slug, c.name) not in RENOMMAGES
            and c.name not in {n for n in RENOMMAGES.values()}
        ]
        for c in restants:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ hors table : {c.section_slug} « {c.name} »'))

        if not a_faire:
            self.stdout.write(self.style.SUCCESS('Rien à renommer.'))
            return
        if not appliquer:
            self.stdout.write(self.style.NOTICE(
                f'\n{len(a_faire)} renommage(s) — relancer avec --appliquer.'))
            return

        with transaction.atomic():
            slugs_avant = {c.pk: c.slug for c, _, _ in a_faire}
            for categorie, _, nouveau in a_faire:
                categorie.name = nouveau
                categorie.save(update_fields=['name'])
            for categorie, _, _ in a_faire:
                categorie.refresh_from_db()
                if categorie.slug != slugs_avant[categorie.pk]:
                    raise RuntimeError(
                        f'ARRÊT : le slug de « {categorie.name} » a changé '
                        f'({slugs_avant[categorie.pk]} → {categorie.slug}). '
                        f'Toutes les adresses de cette catégorie casseraient.')
        self.stdout.write(self.style.SUCCESS(
            f'Appliqué : {len(a_faire)} nom(s) renommé(s), aucun slug touché.'))
