from django.db import migrations


class Migration(migrations.Migration):
    """Supprime le modèle legacy Category (migré vers cms.CmsCategory)."""

    dependencies = [
        ('content', '0022_migrate_menuitem_article_page_to_wagtail'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='article',
            name='categories',
        ),
        migrations.DeleteModel(
            name='Category',
        ),
    ]
