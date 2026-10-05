"""Les trois syndicats de Rhône-Alpes étaient typés « union régionale ».

Ils portent le nom d'une région, mais ce sont des syndicats : on y adhère
(l'Interpro RA est ouvert dans l'application d'adhésion). Une union régionale
ou départementale — 13, 34, Rhône-Alpes — ne prend pas d'adhésions depuis le
05/10/2026 (`SectionPage.peut_adherer`) : laissés en `regional`, ils perdaient
leur bouton « Adhérer ».

La dernière révision est corrigée avec la page : c'est elle que le CMS charge
dans le formulaire, et le prochain « Publier » aurait remis `regional`.
"""
from django.db import migrations

SYNDICATS = ['cnt-interpro-ra', 'cnt-nettoyage-ra', 'cnt-shrcs-ra']


def retyper(apps, de, vers):
    SectionPage = apps.get_model('cms', 'SectionPage')
    for page in SectionPage.objects.filter(slug__in=SYNDICATS, section_type=de):
        page.section_type = vers
        page.save(update_fields=['section_type'])
        revision = page.latest_revision
        if revision and revision.content.get('section_type') == de:
            revision.content['section_type'] = vers
            revision.save(update_fields=['content'])


def en_syndicats(apps, schema_editor):
    retyper(apps, 'regional', 'sectoral')


def en_unions(apps, schema_editor):
    retyper(apps, 'sectoral', 'regional')


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0042_aide_diaporama_sans_complement'),
        ('wagtailcore', '0001_initial'),
    ]

    operations = [migrations.RunPython(en_syndicats, en_unions)]
