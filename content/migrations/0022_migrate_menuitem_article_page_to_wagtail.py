import django.db.models.deletion
from django.db import migrations, models


def remap_page_ids(apps, schema_editor):
    """
    Remappe MenuItem.page_id depuis content_page vers cms_contentpage.
    - Supprime les contraintes FK PostgreSQL avant mise à jour
    - Remappe page par slug (53/55 slugs identiques)
    - MenuItem.article: 0 items non-null → rien à migrer
    """
    db = schema_editor.connection
    vendor = db.vendor

    with db.cursor() as cursor:
        if vendor == 'postgresql':
            cursor.execute("""
                ALTER TABLE content_menuitem
                DROP CONSTRAINT IF EXISTS
                content_menuitem_article_id_12b36c79_fk_content_article_id
            """)
            cursor.execute("""
                ALTER TABLE content_menuitem
                DROP CONSTRAINT IF EXISTS
                content_menuitem_page_id_ec70806b_fk_content_page_id
            """)

        # Remap page : content_page.slug → wagtailcore_page.id (via cms_contentpage)
        cursor.execute("""
            SELECT mi.id, cp.slug
            FROM content_menuitem mi
            JOIN content_page cp ON mi.page_id = cp.id
            WHERE mi.page_id IS NOT NULL
        """)
        rows = cursor.fetchall()

        for mi_id, page_slug in rows:
            cursor.execute("""
                SELECT wp.id
                FROM wagtailcore_page wp
                JOIN cms_contentpage ccp ON wp.id = ccp.page_ptr_id
                WHERE wp.slug = %s AND wp.live = TRUE
                LIMIT 1
            """, [page_slug])
            result = cursor.fetchone()

            if result:
                cursor.execute(
                    "UPDATE content_menuitem SET page_id = %s WHERE id = %s",
                    [result[0], mi_id],
                )
            else:
                cursor.execute(
                    "UPDATE content_menuitem SET page_id = NULL WHERE id = %s",
                    [mi_id],
                )

        # article: 0 items non-null — reset au cas où
        cursor.execute(
            "UPDATE content_menuitem SET article_id = NULL WHERE article_id IS NOT NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0015_sectionpage_ovh_mailing_list'),
        ('content', '0021_migrate_menuitem_category_to_cmscategory'),
    ]

    operations = [
        migrations.RunPython(remap_page_ids, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='menuitem',
            name='article',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='cms.articlepage',
            ),
        ),
        migrations.AlterField(
            model_name='menuitem',
            name='page',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='cms.contentpage',
            ),
        ),
    ]
