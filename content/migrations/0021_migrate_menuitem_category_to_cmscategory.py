import django.db.models.deletion
from django.db import migrations, models


def remap_category_ids(apps, schema_editor):
    """
    Remplace les IDs content.Category par les IDs cms.CmsCategory correspondants,
    en faisant correspondre par (slug, section_slug du site).
    Doit tourner AVANT l'AlterField pour que category_id soit déjà correct.
    """
    db = schema_editor.connection
    with db.cursor() as cursor:
        # S'assurer que les CmsCategory manquantes sont créées avant le remappage
        # (ex: 'actions' sur principal, créé localement mais peut-être absent en prod)
        cursor.execute(
            "SELECT COUNT(*) FROM cms_cmscategory WHERE slug = 'actions' AND section_slug = 'principal'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO cms_cmscategory (name, slug, section_slug, description, legacy_id) VALUES ('Actions', 'actions', 'principal', '', NULL)"
            )
        # Récupère chaque menuitem avec une catégorie, le slug de la catégorie legacy,
        # et le slug du site pour trouver le bon CmsCategory
        cursor.execute("""
            SELECT mi.id, cc.slug, wp.slug AS site_slug
            FROM content_menuitem mi
            JOIN content_category cc ON mi.category_id = cc.id
            JOIN cms_sectionpage sp ON mi.site_id = sp.page_ptr_id
            JOIN wagtailcore_page wp ON sp.page_ptr_id = wp.id
        """)
        rows = cursor.fetchall()

        for mi_id, cat_slug, site_slug in rows:
            # Cherche d'abord par (slug, section_slug)
            cursor.execute(
                "SELECT id FROM cms_cmscategory WHERE slug = %s AND section_slug = %s",
                [cat_slug, site_slug],
            )
            result = cursor.fetchone()
            if not result:
                # Fallback : slug seul (devrait couvrir les cas résiduels)
                cursor.execute(
                    "SELECT id FROM cms_cmscategory WHERE slug = %s LIMIT 1",
                    [cat_slug],
                )
                result = cursor.fetchone()

            if result:
                cursor.execute(
                    "UPDATE content_menuitem SET category_id = %s WHERE id = %s",
                    [result[0], mi_id],
                )
            else:
                cursor.execute(
                    "UPDATE content_menuitem SET category_id = NULL WHERE id = %s",
                    [mi_id],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0015_sectionpage_ovh_mailing_list'),
        ('content', '0020_delete_site'),
    ]

    operations = [
        # 1. Remappe les IDs en base avant de changer la FK
        migrations.RunPython(remap_category_ids, reverse_code=migrations.RunPython.noop),
        # 2. Déclare la nouvelle FK (le contenu est déjà correct)
        migrations.AlterField(
            model_name='menuitem',
            name='category',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='cms.cmscategory',
            ),
        ),
    ]
