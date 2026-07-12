"""
Bascule les articles de newsletter du modèle legacy content.Article
vers cms.ArticlePage. Les liens existants sont remappés via
ArticlePage.legacy_article_id ; ceux sans correspondance sont supprimés
(seules des newsletters de test existaient au moment de la bascule).
"""
import django.db.models.deletion
from django.db import migrations, models


def remap_articles(apps, schema_editor):
    NewsletterArticle = apps.get_model('content', 'NewsletterArticle')
    ArticlePage = apps.get_model('cms', 'ArticlePage')
    for na in NewsletterArticle.objects.all():
        page = ArticlePage.objects.filter(legacy_article_id=na.article_id).first()
        if page is None:
            na.delete()
        else:
            na.article_page_id = page.pk
            na.save(update_fields=['article_page'])


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0025_formulairecontact_featured_image'),
        ('cms', '0001_initial'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='newsletterarticle',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='newsletterarticle',
            name='article_page',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+', to='cms.articlepage',
            ),
        ),
        migrations.RunPython(remap_articles, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='newsletterarticle',
            name='article',
        ),
        migrations.RenameField(
            model_name='newsletterarticle',
            old_name='article_page',
            new_name='article',
        ),
        migrations.AlterField(
            model_name='newsletterarticle',
            name='article',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+', to='cms.articlepage', verbose_name='Article',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='newsletterarticle',
            unique_together={('newsletter', 'article')},
        ),
        migrations.AlterField(
            model_name='newsletter',
            name='articles',
            field=models.ManyToManyField(
                blank=True, through='content.NewsletterArticle',
                to='cms.articlepage', verbose_name='Articles sélectionnés',
            ),
        ),
    ]
