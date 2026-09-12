"""Crée les comptes des rédacteurs à partir des auteurs hérités de WordPress.

Au 12/09/2026 le site tournait avec **un seul compte** — celui d'Arnaud. Les
fiches pratiques étaient écrites, les droits réglés, mais personne ne pouvait
s'en servir. WordPress avait laissé seize `Author` : des noms et des adresses,
aucun mot de passe (ils n'ont jamais été importés, et le modèle n'a pas le
champ). On ne « récupère » donc pas les anciens comptes : on recrée les comptes
des personnes que ces auteurs désignent, en gardant le lien avec ce qu'elles
ont écrit.

Qui, décidé par Arnaud le 12/09/2026 sur les chiffres d'activité mesurés :
`cursive` (743 articles) et `staa` ne sont plus actifs — pas de compte ;
`media` est rédacteur en chef ; les adresses de fonction sont conservées telles
quelles plutôt que d'être éclatées en comptes personnels.

**Le mot de passe est aléatoire et connu de personne.** Ce n'est pas une
négligence, c'est le seul chemin qui marche : la personne clique « Mot de passe
oublié ? » et choisit le sien, donc aucun secret ne transite par un tiers. Il
doit malgré tout être *utilisable* — `PasswordResetForm.get_users()` de Django
écarte les comptes sans mot de passe utilisable, si bien qu'un compte créé avec
`set_unusable_password()` ne recevrait JAMAIS le courriel de réinitialisation
et resterait inaccessible à vie, sans aucun message d'erreur.

Chaque compte est rattaché à son `Author` (les signatures déjà portées par
1 700 articles restent les siennes) et à son syndicat, ce qui lui donne son
groupe — donc ses droits.

Usage :
    python manage.py cree_comptes_redacteurs              # constat seul
    python manage.py cree_comptes_redacteurs --appliquer
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.crypto import get_random_string

GROUPE_CHEF = 'redacteur_en_chef'

# (identifiant, courriel, syndicat, chef ?, auteur hérité à rattacher)
#
# L'identifiant reprend celui de l'auteur WordPress, sauf pour Roberto : son
# auteur s'appelle « education », ce qui nomme un syndicat et non une personne.
#
# Le syndicat vient des articles eux-mêmes, pas d'une supposition : chaque
# signature n'écrit que dans un seul syndicat, à une exception près — `cntso`
# est le compte d'administration historique (wp_id 1), dispersé sur Poitiers
# (50 articles), la conf (7) et Rhône-Alpes (1), et sans publication depuis
# juin 2021. Il est rangé chez sa majorité, Poitiers, et c'est à revoir si le
# syndicat le dit.
COMPTES = [
    ('media',     'media@cnt-so.org',              'principal', True,  'media'),
    ('roberto',   'roberto.trozzo@gmail.com',      'education', False, 'education'),
    ('nicolas13', 'nicolasv690@gmail.com',         '13',        False, 'nicolas13'),
    ('felix86',   'haymark3t_1886@protonmail.com', 'poitiers',  False, 'felix86'),
    ('auvergne',  'contact03@cnt-so.org',          'auvergne',  False, 'auvergne'),
    ('cntso',     'ud69@cnt-so.org',               'poitiers',  False, 'cntso'),
]


class Command(BaseCommand):
    help = ("Crée les comptes des rédacteurs à partir des auteurs hérités de "
            "WordPress, les rattache à leur syndicat et à leur groupe")

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit en base. Sans ce drapeau, la commande n'affiche que ce "
                 "qu'elle ferait.")

    def handle(self, *args, **options):
        self.appliquer = options['appliquer']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Comptes des rédacteurs — "
            + ("ÉCRITURE EN BASE" if self.appliquer
               else "constat seul (--appliquer pour écrire)")))

        # On écrit POUR DE VRAI même en constat ; c'est le `rollback` de la fin
        # qui le rend blanc. Sinon un compte créé à l'étape d'avant resterait
        # invisible à celle d'après, et le constat annoncerait autre chose que
        # ce que l'écriture ferait (leçon du 12/09/2026).
        with transaction.atomic():
            crees, rattaches, refus = self._traiter()
            if not self.appliquer:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'\n{crees} compte(s) créé(s), {rattaches} rattaché(s) à leur auteur.'))
        for motif in refus:
            self.stdout.write(self.style.WARNING(f'   refusé : {motif}'))

    def _traiter(self):
        from django.contrib.auth.models import Group, User
        from cms.models import SectionPage
        from content.models import Author

        crees = rattaches = 0
        refus = []

        for identifiant, courriel, slug, chef, nom_auteur in COMPTES:
            section = SectionPage.objects.filter(slug=slug).first()
            if section is None:
                refus.append(f'{identifiant} : syndicat « {slug} » introuvable')
                continue

            # Groupe nommé d'après le slug WAGTAIL, comme le fait
            # `provision_section`. Prendre le slug hérité manquerait les deux
            # syndicats où ils divergent (Éducation « fter », Numérique
            # « stnum ») et donnerait un compte sans le moindre droit.
            nom_groupe = GROUPE_CHEF if chef else f'redacteur_{section.slug}'
            groupe = Group.objects.filter(name=nom_groupe).first()
            if groupe is None:
                refus.append(f'{identifiant} : groupe « {nom_groupe} » absent')
                continue

            compte = User.objects.filter(username=identifiant).first()
            if compte is None:
                # Mot de passe aléatoire ET utilisable : voir l'en-tête du
                # fichier — un mot de passe inutilisable interdirait à jamais
                # la réinitialisation par courriel.
                compte = User.objects.create_user(
                    username=identifiant, email=courriel,
                    password=get_random_string(50))
                crees += 1
                etat = 'créé'
            else:
                etat = 'existait déjà'

            compte.groups.add(groupe)

            auteur = Author.objects.filter(username=nom_auteur).first()
            lien = 'aucun auteur hérité'
            if auteur is not None:
                # Rattachement : les signatures déjà portées par ses articles
                # restent les siennes, et `Author.site` est ce qui range le
                # compte dans son syndicat pour les écrans du CMS.
                auteur.user = compte
                auteur.site = section
                auteur.save(update_fields=['user', 'site'])
                rattaches += 1
                lien = f'auteur « {nom_auteur} » ({auteur.articles.count()} articles)'

            self.stdout.write(
                f'   {identifiant:<11} {etat:<14} {nom_groupe:<22} {lien}')

        return crees, rattaches, refus
