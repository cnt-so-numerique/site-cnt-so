"""Crée (ou met à jour) la fiche pratique « Forfait jours » du syndicat Numérique.

Le texte venait d'une page HTML autonome, écrite hors du site. Plutôt que de
la déposer telle quelle dans un bloc « HTML brut » — illisible et intouchable
pour un rédacteur —, elle est découpée en blocs du CMS : titres, listes,
encadrés. Seul le tableau des positions reste en HTML, le texte riche du site
ne connaissant pas les tableaux.

Idempotente : relancée, elle met à jour l'article existant au lieu d'en créer
un second. Le contenu écrit depuis dans /cms/ serait donc écrasé — d'où
l'option --dry-run pour regarder avant d'agir.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from cms.models import ArticlePage, CmsCategory, HomePage, SectionPage


SLUG_ARTICLE = 'forfait-jours-syntec'
SECTION = 'numerique'
CATEGORIE = ('droit', 'Nos droits')

TITRE = "Forfait jours : et si le tien était illégal ?"

EXTRAIT = (
    "Dans nos métiers, le forfait jours est presque automatique dès qu'on passe "
    "cadre. Il n'est pourtant légal que sous des conditions strictes — et quand "
    "elles manquent, il tombe : retour aux 35 heures et rappel de trois ans "
    "d'heures supplémentaires."
)

# Le tableau des positions : le texte riche du site n'a pas de tableau, et le
# transformer en liste perdrait la lecture en colonnes. C'est exactement le cas
# d'usage du bloc « HTML brut ».
TABLEAU_POSITIONS = """<table class="tableau-article">
  <thead>
    <tr><th>Position</th><th>Profil type (logique d'expérience)</th><th>Forfait ?</th></tr>
  </thead>
  <tbody>
    <tr><td>1.1 – 1.2</td><td>Cadre débutant·e (jeune diplômé·e)</td><td>Non</td></tr>
    <tr><td>2.1 – 2.2</td><td>Cadre confirmé·e (env. 2 à 6 ans)</td><td>Non</td></tr>
    <tr><td><strong>2.3 · coef 150</strong></td><td>Cadre confirmé·e expérimenté·e — seuil d'accès depuis 2022</td><td><strong>Oui</strong></td></tr>
    <tr><td><strong>3.1 · coef 170</strong></td><td>Cadre « expert » (env. 6 ans et +)</td><td><strong>Oui</strong></td></tr>
    <tr><td><strong>3.2 – 3.3</strong></td><td>Cadre, hautes responsabilités</td><td><strong>Oui</strong></td></tr>
  </tbody>
</table>"""

ROUGE = '#E81C24'


def corps():
    """Le corps de l'article, bloc par bloc."""
    return [
        ('rich_text',
         "<p><b>Dans nos métiers, le forfait jours est presque automatique dès "
         "qu'on passe cadre.</b> On te le vend comme de « l'autonomie ». En "
         "pratique, il sert surtout à <b>effacer tes heures supplémentaires</b> : "
         "tu fais 45 heures, tu es payé·e pour 35, et la boîte encaisse la "
         "différence.</p>"
         "<p>Sauf que le forfait jours n'est légal que sous des conditions "
         "<b>strictes</b>. Et dans énormément d'entreprises Syntec, elles ne sont "
         "pas réunies. Quand c'est le cas, le forfait <b>tombe</b> : tu repasses "
         "aux 35 heures, et l'employeur te doit un rappel de toutes tes heures "
         "supplémentaires sur trois ans. Ce guide t'explique quand ton forfait "
         "tient — et quand tu peux le faire sauter.</p>"),

        ('rich_text',
         "<h2>Comment ça marche, et où ça coince</h2>"
         "<p>Au forfait jours, ton temps de travail se compte en jours sur "
         "l'année, pas en heures. Tu n'es plus soumis·e à la durée légale des "
         "35 heures, ni aux durées maximales, ni au régime des heures "
         "supplémentaires. Le plafond est de <b>218 jours travaillés par an</b>, "
         "journée de solidarité comprise.</p>"
         "<p>La contrepartie, imposée par la loi et par les juges, c'est un "
         "<b>encadrement strict de ta charge de travail</b>, pour protéger ta "
         "santé. C'est là que se joue tout le rapport de force : dès qu'une de "
         "ces protections manque, le forfait est fragile — et attaquable.</p>"),

        ('rich_text',
         "<h2>Ton forfait n'est valable que si tout est réuni</h2>"
         "<p>Ces conditions sont <b>cumulatives</b>. Il suffit qu'une seule "
         "manque pour que le forfait puisse être annulé ou privé d'effet :</p>"
         "<ul>"
         "<li><b>Une convention écrite et signée</b> — une clause dans ton "
         "contrat ou un avenant. Pas d'écrit, pas de forfait : tu relèves des "
         "35 heures.</li>"
         "<li><b>Une autonomie réelle</b> — tu organises vraiment ton emploi du "
         "temps. Si on t'impose un planning, des horaires fixes ou une présence "
         "obligatoire, le forfait est incompatible.</li>"
         "<li><b>Une classification suffisante</b> — au minimum position 2.3 "
         "(coef. 150) depuis l'avenant de 2022, ou une rémunération supérieure à "
         "2× le plafond Sécu (≈ 96 000 € par an).</li>"
         "<li><b>Une rémunération au niveau du minimum majoré</b> — le minimum "
         "conventionnel de ta catégorie, majoré de 120 % (position 3) ou 122 % "
         "(position 2.3).</li>"
         "<li><b>Un suivi effectif de ta charge</b> — entretien annuel tracé, "
         "décompte des jours, repos contrôlés, dispositif d'alerte, droit à la "
         "déconnexion.</li>"
         "</ul>"
         "<h3>Repère-toi dans la grille des positions</h3>"),

        ('html', TABLEAU_POSITIONS),

        ('rich_text',
         "<p>Ta position et ton coefficient sont sur ton bulletin de paie "
         "(lignes « Position » et « Coefficient »). À titre indicatif, pour une "
         "position 2.3, le minimum de base est d'environ 3 275 € brut/mois, soit "
         "≈ 3 995 € une fois majoré à 122 % (grille en vigueur au 1<sup>er</sup> "
         "janvier 2025, accord du 26 juin 2024). Grille officielle : "
         "<a href=\"https://www.legifrance.gouv.fr/conv_coll/id/KALICONT000005635173/\">"
         "Légifrance, CCN Syntec/Betic</a>.</p>"),

        ('rich_text',
         "<h2>Six cas où tu peux le faire sauter</h2>"
         "<ol>"
         "<li><b>Aucun écrit signé</b> — le forfait est inopposable, tu relèves "
         "des 35 heures.</li>"
         "<li><b>Pas d'autonomie réelle</b> — planning imposé, horaires fixes, "
         "présence obligatoire.</li>"
         "<li><b>Classification ou rémunération insuffisante</b> — en dessous de "
         "2.3 sans atteindre 2× le plafond Sécu.</li>"
         "<li><b>Salaire sous le minimum conventionnel</b> — en dessous du "
         "minimum de base de ton coefficient.</li>"
         "<li><b>Suivi inexistant</b> — pas d'entretien tracé, pas de décompte, "
         "pas de dispositif d'alerte.</li>"
         "<li><b>Charge déraisonnable</b> — journées à rallonge, repos non "
         "respectés, déconnexion impossible.</li>"
         "</ol>"),

        ('encadre', {
            'titre': "Ce que tu récupères : trois ans",
            'texte': (
                "<p>Si le forfait tombe, tu repasses aux 35 heures et tu peux "
                "réclamer le <b>rappel de toutes tes heures supplémentaires "
                "majorées</b> sur les trois dernières années, plus les congés "
                "payés afférents. Souvent plusieurs milliers d'euros.</p>"),
            'couleur': ROUGE,
            'fond': 'teinte',
        }),

        ('rich_text',
         "<p>La prescription pour réclamer des salaires est de trois ans. Tu "
         "restes recevable à contester la validité du forfait tant que ta demande "
         "de rappel d'heures n'est pas prescrite — peu importe depuis combien de "
         "temps le vice existe. Dans certains cas, une indemnité pour travail "
         "dissimulé (six mois de salaire) peut s'ajouter, mais elle n'est pas "
         "automatique et se plaide avec prudence.</p>"),

        ('encadre', {
            'titre': "Accord d'entreprise : ce qui saute, ce qui ne saute jamais",
            'texte': (
                "<p>Depuis les ordonnances de 2017, l'accord d'entreprise prime "
                "souvent sur la branche. Mais pas sur tout.</p>"
                "<p><b>Ce qu'un accord d'entreprise peut changer</b> (durée du "
                "travail, « bloc 3 ») : les positions qui ouvrent droit au "
                "forfait, le nombre de jours, les modalités de suivi. Il peut "
                "donc étendre le forfait à des positions plus basses que 2.3.</p>"
                "<p><b>Ce qu'il ne peut jamais faire</b> : te payer sous le "
                "minimum de salaire de ta position (« bloc 1 », protégé), ni "
                "écarter les protections légales d'ordre public — autonomie "
                "réelle, suivi de la charge, repos, droit à la déconnexion. La "
                "seule zone vraiment discutée est la majoration forfait "
                "(120 %/122 %).</p>"
                "<p>Autrement dit : un accord d'entreprise déplace <i>qui</i> "
                "peut être au forfait, jamais le niveau de protection. Tes angles "
                "d'attaque sur l'autonomie et le suivi restent valables quel que "
                "soit l'accord.</p>"),
            'couleur': ROUGE,
            'fond': 'gris',
        }),

        ('encadre', {
            'titre': "Un tournant récent à connaître (mars 2025)",
            'texte': (
                "<p>Depuis deux arrêts de la Cour de cassation du 11 mars 2025, "
                "la nullité ou la privation d'effet du forfait <b>n'ouvre plus, à "
                "elle seule, droit à des dommages-intérêts distincts</b>. Le "
                "rappel d'heures supplémentaires, lui, reste dû. Toute "
                "indemnisation supplémentaire suppose désormais de prouver un "
                "préjudice concret (atteinte à la santé, surcharge). À intégrer "
                "dans la stratégie : le gain reste réel, mais il faut le chiffrer "
                "honnêtement.</p>"),
            'couleur': ROUGE,
            'fond': 'gris',
        }),

        ('rich_text',
         "<h2>Quoi faire concrètement</h2>"
         "<ul>"
         "<li><b>Garde tes preuves</b> d'horaires : mails horodatés, agendas, "
         "badges, connexions.</li>"
         "<li><b>Réclame par écrit</b> tes comptes rendus d'entretien annuel et "
         "le décompte de tes jours. Leur absence est un indice précieux.</li>"
         "<li><b>N'attends pas</b> la rupture du contrat : la prescription court "
         "(trois ans).</li>"
         "<li><b>Parles-en au syndicat</b> : ces failles concernent souvent toute "
         "une catégorie de collègues, ce qui ouvre la voie à des actions "
         "collectives.</li>"
         "</ul>"),

        ('rich_text',
         "<h2>Sources</h2>"
         "<p><b>Textes.</b> Code du travail, art. L. 3121-58 à L. 3121-66 "
         "(forfait jours), L. 3121-60, L. 3121-62 à L. 3121-65 ; L. 3171-4 "
         "(preuve des heures) ; L. 3245-1 (prescription) ; L. 8223-1 (travail "
         "dissimulé) ; L. 2253-1 à L. 2253-3 (articulation accord d'entreprise / "
         "branche, ordonnance n° 2017-1385 du 22 septembre 2017). CCN "
         "Syntec/Betic (IDCC 1486) : accord du 22 juin 1999 ; avenant du "
         "1<sup>er</sup> avril 2014 ; avenant n° 2 du 13 décembre 2022, étendu "
         "par arrêté du 12 juin 2024, applicable au 1<sup>er</sup> juillet 2024 ; "
         "accord salaires du 26 juin 2024 (étendu le 8 novembre 2024).</p>"
         "<p><b>Jurisprudence.</b> Cass. soc. 29 juin 2011, n° 09-71.107 · "
         "24 avril 2013, n° 11-28.398 (invalidation de l'accord Syntec de 1999) · "
         "27 mars 2019, n° 17-31.715 (autonomie réelle) · 2 février 2022, "
         "n° 20-15.744 · 9 novembre 2022, n° 21-13.389 (contrôle effectif des "
         "repos) · 27 mars 2019, n° 17-23.314 (recevabilité de la contestation) · "
         "11 mars 2025, n° 23-19.669 et n° 24-10.452 (préjudice non automatique). "
         "CE, 7 octobre 2021 (salaires minima hiérarchiques).</p>"
         "<p><i>Cet article est une information syndicale à visée pratique, à "
         "jour du 1<sup>er</sup> semestre 2026. Il ne préjuge pas de l'issue d'un "
         "litige et ne remplace pas l'examen d'un dossier individuel par un "
         "défenseur syndical ou un avocat. Chaque situation s'apprécie au cas par "
         "cas.</i></p>"),
    ]


class Command(BaseCommand):
    help = "Crée la fiche « Forfait jours » dans les ressources du syndicat Numérique."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien, montre ce qui serait fait.")

    def handle(self, *args, **options):
        sec = options['dry_run']

        section = SectionPage.objects.filter(slug=SECTION).first()
        if section is None:
            self.stderr.write(self.style.ERROR(
                f"Syndicat « {SECTION} » introuvable."))
            return

        parent = HomePage.objects.first()
        if parent is None:
            self.stderr.write(self.style.ERROR("Aucune HomePage : rien à quoi rattacher."))
            return

        categorie = CmsCategory.objects.filter(
            section_slug=SECTION, slug=CATEGORIE[0]).first()
        existant = ArticlePage.objects.filter(
            section_slug=SECTION, slug=SLUG_ARTICLE).first()

        self.stdout.write(f"Syndicat  : {section.title}")
        self.stdout.write(f"Parent    : {parent.title}")
        self.stdout.write(
            f"Catégorie : {CATEGORIE[1]} ({CATEGORIE[0]}) — "
            + ("existante" if categorie else "à créer"))
        self.stdout.write(
            f"Article   : {SLUG_ARTICLE} — "
            + ("MISE À JOUR" if existant else "création")
            + f" — {len(corps())} blocs")

        if sec:
            self.stdout.write(self.style.WARNING("--dry-run : rien n'a été écrit."))
            return

        with transaction.atomic():
            if categorie is None:
                categorie = CmsCategory.objects.create(
                    name=CATEGORIE[1], slug=CATEGORIE[0], section_slug=SECTION)
                self.stdout.write(self.style.SUCCESS(
                    f"  catégorie créée : {categorie.name}"))

            if existant is None:
                article = parent.add_child(instance=ArticlePage(
                    title=TITRE,
                    slug=SLUG_ARTICLE,
                    section_slug=SECTION,
                    excerpt=EXTRAIT,
                    body=corps(),
                    publication_date=timezone.now().date(),
                    live=True,
                ))
            else:
                article = existant
                article.title = TITRE
                article.excerpt = EXTRAIT
                article.body = corps()
                article.save()

            article.cms_categories.set([categorie])
            article.save()
            # La révision publiée est ce que l'éditeur ouvrira : sans elle, le
            # texte serait en ligne mais invisible dans /cms/.
            article.save_revision().publish()

        self.stdout.write(self.style.SUCCESS(
            f"OK — {article.get_absolute_url()}"))
