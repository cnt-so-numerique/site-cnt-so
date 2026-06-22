import django.db.models.deletion
from django.db import migrations, models


def remap_category_ids(apps, schema_editor):
    """
    Remplace les IDs content.Category par les IDs cms.CmsCategory correspondants.
    1. Supprime la contrainte FK (PostgreSQL uniquement) pour pouvoir écrire les nouveaux IDs
    2. Remappe par (slug, section_slug)
    L'AlterField qui suit recrée la contrainte vers cms_cmscategory.
    """
    db = schema_editor.connection
    vendor = db.vendor  # 'postgresql' ou 'sqlite'

    with db.cursor() as cursor:
        # PostgreSQL : supprimer la contrainte FK existante vers content_category
        if vendor == 'postgresql':
            cursor.execute("""
                ALTER TABLE content_menuitem
                DROP CONSTRAINT IF EXISTS content_menuitem_category_id_37ed9ade_fk_content_category_id
            """)

        # Créer 'actions/principal' si absent
        cursor.execute(
            "SELECT COUNT(*) FROM cms_cmscategory WHERE slug = 'actions' AND section_slug = 'principal'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO cms_cmscategory (name, slug, section_slug, description, legacy_id)"
                " VALUES ('Actions', 'actions', 'principal', '', NULL)"
            )

        # Récupère chaque menuitem avec une catégorie, le slug legacy et le slug du site
        cursor.execute("""
            SELECT mi.id, cc.slug, wp.slug AS site_slug
            FROM content_menuitem mi
            JOIN content_category cc ON mi.category_id = cc.id
            JOIN cms_sectionpage sp ON mi.site_id = sp.page_ptr_id
            JOIN wagtailcore_page wp ON sp.page_ptr_id = wp.id
        """)
        rows = cursor.fetchall()

        for mi_id, cat_slug, site_slug in rows:
            cursor.execute(
                "SELECT id FROM cms_cmscategory WHERE slug = %s AND section_slug = %s",
                [cat_slug, site_slug],
            )
            result = cursor.fetchone()
            if not result:
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
