"""Recopie dans le CMS le texte de « Qui sommes-nous ».

Jusqu'au 05/10/2026, ce texte était écrit en dur dans
`templates/content/qui_sommes_nous.html` : personne ne pouvait le modifier
depuis /cms/. La vue lit désormais la page de contenu « qui-sommes-nous » de
la confédération ; cette commande y recopie le texte d'alors, pour que rien ne
change à l'écran le jour de la bascule.

À lancer une fois, au déploiement. Précautions :

- elle crée la page si elle n'existe pas ;
- elle **refuse** d'écraser un corps déjà rempli ou un brouillon en attente
  (`--force` pour passer outre) : une fois la page reprise par quelqu'un,
  le texte d'origine n'a plus à revenir ;
- elle publie une révision, pour que la recopie figure dans l'historique de
  la page et puisse être annulée depuis le CMS.

Les deux images du gabarit pointaient vers d'anciennes adresses WordPress, en
404 en production. L'affiche « On ne se rend pas » est reprise de la banque
d'images si elle s'y trouve ; l'autre a disparu, elle n'est pas recopiée.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cms.models import ContentPage, HomePage

SLUG = 'qui-sommes-nous'

ACCROCHE = (
    "Un syndicalisme d'industrie, de lutte des classes et de transformation "
    "sociale. Une organisation construite par et pour les travailleuses et "
    "travailleurs, fondée sur l'action directe et l'autogestion."
)

PRINCIPES = [
    ('groupe', "Refus du corporatisme",
     "Syndicalisme d'industrie : les travailleurs d'une même branche, quels que "
     "soient leurs métiers, statuts ou employeurs, adhèrent au même syndicat à "
     "un échelon géographique donné."),
    ('horloge', "Indépendance et autogestion",
     "Fonctionnement exclusivement par cotisations — zéro subvention de l'État "
     "ou du patronat. Indépendance de tout groupement politique ou religieux. "
     "Les décisions se prennent en Assemblée Générale."),
    ('croix', "Refus du clientélisme",
     "C'est toujours l'intérêt collectif des travailleurs-euses qui prime. Nous "
     "refusons les petits arrangements « entre amis » et toute complicité avec "
     "les employeurs."),
    ('bouclier', "Un outil au service des travailleurs",
     "Conseils juridiques, aide sur les conditions de travail, espace de "
     "formation pour s'émanciper. Le syndicat est un outil concret pour "
     "défendre vos droits au quotidien."),
    ('cadenas', "Un outil de coordination des luttes",
     "Syndicalisme de lutte des classes : tout est question de rapport de "
     "force. C'est par les luttes syndicales, sous toutes leurs formes, que "
     "nous faisons avancer nos intérêts contre ceux des patrons."),
    ('etoile', "Un syndicalisme révolutionnaire",
     "Nous revendiquons un autre projet de société : transformation sociale "
     "révolutionnaire basée sur la gestion directe par les travailleur-euses, "
     "sans intermédiaires parasites, de l'économie et de la société."),
]


def corps_d_origine():
    """Le texte du gabarit d'avant le 05/10/2026, en blocs du CMS."""
    from wagtail.images import get_image_model

    base = settings.MAIN_SITE_BASE_URL.rstrip('/')
    corps = [
        {'type': 'quote', 'value': {
            'text': "<p>Le syndicalisme reste l'arme la plus efficace dans le "
                    "combat collectif pour les travailleur-euses. Choisir la "
                    "CNT Solidarité Ouvrière c'est développer une alternative "
                    "syndicale.</p>",
            'citation': ''}},
        {'type': 'rich_text', 'value':
            "<p>Le syndicalisme a été le moteur de la plupart de nos conquêtes "
            "sociales, pourtant il semble aujourd'hui très éloigné du quotidien "
            "d'un grand nombre de travailleur-euses. Nous partageons les "
            "critiques à l'encontre des syndicats institutionnels — "
            "bureaucratisation et éloignement du terrain, impuissance face à la "
            "dégradation de nos droits et conditions de travail, compromissions "
            "— mais pour nous le syndicalisme reste l'arme la plus efficace "
            "dans le combat collectif.</p>"
            "<p>Il est temps de développer, à la base, un modèle alternatif et "
            "combatif qui revient aux fondamentaux du syndicalisme. C'est le "
            "sens de l'engagement quotidien des militant-e-s de la CNT "
            "Solidarité Ouvrière.</p>"
            "<h2>Nos principes</h2>"},
        {'type': 'cartes', 'value': {'cartes': [
            {'pictogramme': p, 'titre': t, 'texte': x} for p, t, x in PRINCIPES]}},
    ]
    affiche = get_image_model().objects.filter(
        file__icontains='on_ne_se_rend_pas').order_by('pk').first()
    if affiche:
        corps.append({'type': 'image', 'value': {
            'image': affiche.pk, 'alignment': 'center', 'largeur': '100',
            'caption': ''}})
    corps += [
        {'type': 'encadre', 'value': {
            'titre': "Nous rejoindre / nous contacter",
            'texte': "<p>Rejoindre la CNT-SO, c'est intégrer un réseau de "
                     "militant·e·s qui agissent au quotidien pour défendre les "
                     "travailleuses et travailleurs. Que tu sois salarié·e, "
                     "précaire, indépendant·e ou sans emploi, tu as ta place "
                     "ici.</p>",
            'couleur': '#E81C24', 'fond': 'gris'}},
        {'type': 'boutons', 'value': {'boutons': [
            {'libelle': "Nous contacter / Adhérer", 'url': f'{base}/contact/',
             'style': 'plein', 'couleur': '#E81C24', 'nouvel_onglet': False},
            {'libelle': "Nous soutenir", 'url': f'{base}/souscription/',
             'style': 'plein', 'couleur': '#1A1A1A', 'nouvel_onglet': False},
        ]}},
    ]
    return corps


class Command(BaseCommand):
    help = "Recopie dans le CMS le texte d'origine de « Qui sommes-nous »."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, dit ce qui serait fait.")
        parser.add_argument('--force', action='store_true',
                            help="Écrase un corps déjà rempli ou un brouillon.")

    @transaction.atomic
    def handle(self, *args, dry_run=False, force=False, **options):
        page = ContentPage.objects.filter(slug=SLUG, section_slug='principal').first()
        if page is None:
            parent = HomePage.objects.first()
            if parent is None:
                raise CommandError("Aucune page d'accueil où créer la page.")
            self.stdout.write(f"Page absente : création sous « {parent.title} ».")
            if dry_run:
                return
            page = ContentPage(title="Qui sommes-nous ?", slug=SLUG,
                               section_slug='principal')
            parent.add_child(instance=page)
        elif not force and (len(page.body) or page.has_unpublished_changes):
            self.stdout.write(self.style.WARNING(
                f"Page {page.pk} déjà remplie ou en brouillon : rien n'est "
                "écrit (--force pour écraser)."))
            return

        corps = corps_d_origine()
        self.stdout.write(
            f"Page {page.pk or '(nouvelle)'} : {len(corps)} blocs"
            + ("" if any(b['type'] == 'image' for b in corps)
               else " — affiche introuvable dans la banque, non reprise") + ".")
        if dry_run:
            return
        page.body = corps
        page.excerpt = ACCROCHE
        page.save_revision().publish()
        self.stdout.write(self.style.SUCCESS(f"Publiée : page {page.pk}."))
