"""« Actions » devient « Actions et actualités » (Arnaud, 05/10/2026).

La rubrique du bas de l'accueil de la confédération porte désormais ce nom ;
la catégorie qu'elle affiche le prend aussi. Le slug `actions` ne change pas :
/categorie/actions/ est cité dans les gabarits et a pu être partagé.
"""
from django.db import migrations

ANCIEN, NOUVEAU = "Actions", "Actions et actualités"


def renommer(apps, de, vers):
    CmsCategory = apps.get_model('cms', 'CmsCategory')
    CmsCategory.objects.filter(slug='actions', section_slug='principal', name=de).update(name=vers)


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0045_carte_image_personnelle'),
    ]

    operations = [migrations.RunPython(
        lambda apps, se: renommer(apps, ANCIEN, NOUVEAU),
        lambda apps, se: renommer(apps, NOUVEAU, ANCIEN),
    )]
