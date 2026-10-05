"""« Actions » devient « Actions et actualités » (Arnaud, 05/10/2026).

La rubrique du bas de l'accueil de la confédération porte désormais ce nom,
et la catégorie qu'elle affiche le prend avec son adresse :
/categorie/actions/ → /categorie/actions-et-actualites/. L'ancienne adresse
redirige en 301 (`CATEGORIES_CONF_RENOMMEES`, cms/models.py).
"""
from django.db import migrations

ANCIEN = ('actions', "Actions")
NOUVEAU = ('actions-et-actualites', "Actions et actualités")


def renommer(apps, de, vers):
    CmsCategory = apps.get_model('cms', 'CmsCategory')
    CmsCategory.objects.filter(slug=de[0], section_slug='principal').update(
        slug=vers[0], name=vers[1])


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0045_carte_image_personnelle'),
        # Celle-ci crée « actions » si elle manque : sans cet ordre, la base
        # de test la recréait après le renommage.
        ('content', '0021_migrate_menuitem_category_to_cmscategory'),
    ]

    operations = [migrations.RunPython(
        lambda apps, se: renommer(apps, ANCIEN, NOUVEAU),
        lambda apps, se: renommer(apps, NOUVEAU, ANCIEN),
    )]
