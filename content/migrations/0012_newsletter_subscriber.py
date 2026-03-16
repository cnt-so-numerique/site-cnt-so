import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0011_add_external_url_to_site'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscriber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, verbose_name='Adresse e-mail')),
                ('name', models.CharField(blank=True, max_length=200, verbose_name='Nom')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('is_active', models.BooleanField(default=False, verbose_name='Confirmé')),
                ('subscribed_at', models.DateTimeField(auto_now_add=True)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subscribers', to='content.site', verbose_name='Site')),
            ],
            options={
                'verbose_name': 'Abonné',
                'verbose_name_plural': 'Abonnés',
                'ordering': ['-subscribed_at'],
                'unique_together': {('site', 'email')},
            },
        ),
        migrations.CreateModel(
            name='Newsletter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300, verbose_name="Sujet de l'e-mail")),
                ('intro', models.TextField(verbose_name="Texte d'introduction")),
                ('status', models.CharField(choices=[('draft', 'Brouillon'), ('sent', 'Envoyée')], default='draft', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('sent_count', models.IntegerField(default=0)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='newsletters', to='content.site', verbose_name='Site')),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sent_newsletters', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Newsletter',
                'verbose_name_plural': 'Newsletters',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='NewsletterArticle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField(default=0)),
                ('newsletter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='newsletter_articles', to='content.newsletter')),
                ('article', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='content.article')),
            ],
            options={
                'ordering': ['order'],
                'unique_together': {('newsletter', 'article')},
            },
        ),
        migrations.AddField(
            model_name='newsletter',
            name='articles',
            field=models.ManyToManyField(blank=True, through='content.NewsletterArticle', to='content.article', verbose_name='Articles sélectionnés'),
        ),
    ]
