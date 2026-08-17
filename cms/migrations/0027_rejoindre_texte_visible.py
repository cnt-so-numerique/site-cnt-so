import uuid

from django.db import migrations


CARTE_POURQUOI = (
    '<h3>Pourquoi adhérer à {nom} ?</h3>'
    '<p>La CNT-SO est un syndicat autogestionnaire, sans permanents rémunérés, '
    'qui organise les travailleur·ses de ce secteur.</p>'
    '<ul>'
    "<li>Défense individuelle en cas de litige avec l'employeur</li>"
    '<li>Rapport de force collectif dans le secteur</li>'
    '<li>Syndicat autogestionnaire, sans permanents rémunérés</li>'
    '<li>Cotisation libre et solidaire</li>'
    '<li>Réseau national CNT-SO</li>'
    '</ul>'
)

CARTE_COMMENT = (
    '<h3>Comment ça marche ?</h3>'
    "<p>Clique sur « Adhérer maintenant » ci-dessus pour remplir le formulaire "
    "d'adhésion en ligne. Un·e militant·e te contactera pour finaliser.</p>"
    '<p>La cotisation est libre — nous suggérons environ '
    '<b>1 % de ton salaire net mensuel</b>.</p>'
)


def corps_par_defaut(nom):
    """Les deux encadrés que le gabarit affichait en dur, devenus du contenu."""
    return [
        {'type': 'contenu', 'id': str(uuid.uuid4()),
         'value': CARTE_POURQUOI.format(nom=nom or 'la CNT-SO')},
        {'type': 'contenu', 'id': str(uuid.uuid4()), 'value': CARTE_COMMENT},
    ]


def semer_le_corps(apps, schema_editor):
    """Rendre modifiable un texte qui ne l'était pas.

    La page « Nous rejoindre » affichait deux encadrés écrits dans le gabarit,
    remplacés d'un bloc — et sans prévenir — dès qu'un rédacteur touchait à
    `rejoindre_text`. Il ne voyait donc jamais ce qu'il était en train
    d'effacer. On recopie ce texte dans le champ : rien ne change à l'écran,
    mais il existe désormais dans /cms/.

    La révision la plus récente est corrigée en même temps : c'est elle que
    l'éditeur Wagtail ouvre, et une révision restée vide aurait effacé le texte
    à la première modification de la fiche.
    """
    SectionPage = apps.get_model('cms', 'SectionPage')

    for page in SectionPage.objects.all():
        if page.rejoindre_text:
            continue
        blocs = corps_par_defaut(page.title)
        page.rejoindre_text = blocs
        page.save(update_fields=['rejoindre_text'])

        revision = page.latest_revision
        if revision is not None and isinstance(revision.content, dict):
            revision.content['rejoindre_text'] = blocs
            revision.save(update_fields=['content'])


def vider_le_corps(apps, schema_editor):
    """Retour en arrière : on ne retire que ce que la migration a semé.

    Un texte réécrit depuis par un syndicat ne ressemble plus au gabarit
    d'origine ; il est donc laissé intact.
    """
    SectionPage = apps.get_model('cms', 'SectionPage')

    for page in SectionPage.objects.all():
        valeurs = [bloc.get('value', '') for bloc in (page.rejoindre_text or [])]
        if not any('Pourquoi adhérer' in v for v in valeurs):
            continue
        page.rejoindre_text = []
        page.save(update_fields=['rejoindre_text'])

        revision = page.latest_revision
        if revision is not None and isinstance(revision.content, dict):
            revision.content['rejoindre_text'] = []
            revision.save(update_fields=['content'])


class Migration(migrations.Migration):

    dependencies = [('cms', '0026_sectionpage_rejoindre_accroche_and_more')]

    operations = [migrations.RunPython(semer_le_corps, vider_le_corps)]
