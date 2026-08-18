"""La rubrique devient un bloc qui porte ses articles.

Chaque article portait jusqu'ici le nom de sa rubrique : mettre cinq articles
en « Campagnes » obligeait à choisir « Campagnes » cinq fois, et rien ne
montrait le sommaire tel qu'il serait lu. Les lettres existantes sont
converties, pas effacées.

⚠️ **Non réversible une fois des lettres converties.** La fonction `revenir`
remet bien le nom de la rubrique sur chaque article, mais Django recrée la
colonne `newsletter_id` en NOT NULL *avant* de la rappeler, et le retour
arrière échoue sur une table peuplée. Le sens aller est éprouvé ; un retour en
arrière passerait par une restauration de sauvegarde.
"""

import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


#: L'ordre historique des sections, figé dans le code jusqu'à cette migration.
#: Il sert une dernière fois, à ranger les blocs créés à partir de l'existant.
ORDRE_HISTORIQUE = ['', 'campagne', 'actu-syndicale', 'actu-generale',
                    'droits', 'international']

CHOIX = [
    ('', 'Sans titre — en tête de la lettre'),
    ('campagne', 'Campagnes'),
    ('actu-syndicale', 'Actu syndicale'),
    ('actu-generale', 'Actu générale'),
    ('droits', 'Nos droits'),
    ('international', 'International'),
]


def convertir(apps, schema_editor):
    Newsletter = apps.get_model('content', 'Newsletter')
    Article = apps.get_model('content', 'NewsletterArticle')
    Rubrique = apps.get_model('content', 'NewsletterRubrique')

    for lettre in Newsletter.objects.all():
        lignes = list(Article.objects.filter(newsletter=lettre).order_by('order', 'id'))
        if not lignes:
            continue
        rang = 0
        connues = set()
        for code in ORDRE_HISTORIQUE:
            dedans = [l for l in lignes if (l.rubrique or '') == code]
            if not dedans:
                continue
            bloc = Rubrique.objects.create(newsletter=lettre, rubrique=code, sort_order=rang)
            rang += 1
            connues.add(code)
            for i, ligne in enumerate(dedans):
                ligne.bloc = bloc
                ligne.sort_order = i
                ligne.save(update_fields=['bloc', 'sort_order'])

        # Une valeur de rubrique hors liste (import, essai) ne doit pas faire
        # disparaître l'article : elle atterrit dans une section sans titre.
        restants = [l for l in lignes if (l.rubrique or '') not in connues]
        if restants:
            bloc = Rubrique.objects.create(newsletter=lettre, rubrique='', sort_order=rang)
            for i, ligne in enumerate(restants):
                ligne.bloc = bloc
                ligne.sort_order = i
                ligne.save(update_fields=['bloc', 'sort_order'])

    # Sans rubrique d'accueil, une ligne serait orpheline et empêcherait la
    # colonne de devenir obligatoire. Le cas ne devrait pas se produire.
    Article.objects.filter(bloc__isnull=True).delete()


def revenir(apps, schema_editor):
    """Remet le nom de la rubrique sur chaque article, et l'ordre à plat."""
    Article = apps.get_model('content', 'NewsletterArticle')
    for ligne in Article.objects.select_related('bloc__newsletter').all():
        ligne.newsletter = ligne.bloc.newsletter
        ligne.rubrique = ligne.bloc.rubrique
        ligne.order = ligne.sort_order or 0
        ligne.save(update_fields=['newsletter', 'rubrique', 'order'])


class Migration(migrations.Migration):

    dependencies = [('content', '0034_alter_newsletterarticle_order_and_more')]

    operations = [
        migrations.CreateModel(
            name='NewsletterRubrique',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('rubrique', models.CharField(
                    blank=True, choices=CHOIX, max_length=30,
                    verbose_name='Rubrique',
                    help_text="Le titre de section affiché dans l'e-mail. Sans "
                              "titre, les articles ouvrent la lettre, avant "
                              "toute section.")),
                ('newsletter', modelcluster.fields.ParentalKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rubriques', to='content.newsletter')),
            ],
            options={
                'verbose_name': 'Rubrique de la newsletter',
                'verbose_name_plural': 'Rubriques de la newsletter',
                'ordering': ['sort_order'],
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='newsletterarticle', name='sort_order',
            field=models.IntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='newsletterarticle', name='bloc',
            field=modelcluster.fields.ParentalKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='articles', to='content.newsletterrubrique'),
        ),
        migrations.AlterUniqueTogether(name='newsletterarticle', unique_together=set()),
        migrations.RunPython(convertir, revenir),
        migrations.RemoveField(model_name='newsletter', name='articles'),
        migrations.RemoveField(model_name='newsletterarticle', name='newsletter'),
        migrations.RemoveField(model_name='newsletterarticle', name='rubrique'),
        migrations.RemoveField(model_name='newsletterarticle', name='order'),
        migrations.AlterField(
            model_name='newsletterarticle', name='bloc',
            field=modelcluster.fields.ParentalKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='articles', to='content.newsletterrubrique'),
        ),
        migrations.AlterModelOptions(
            name='newsletterarticle',
            options={'ordering': ['sort_order'], 'abstract': False,
                     'verbose_name': 'Article de la newsletter',
                     'verbose_name_plural': 'Articles de la newsletter'},
        ),
    ]
