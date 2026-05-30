import django.db.models.deletion
from django.db import migrations, models


def _ensure_principal_section_page():
    """Crée le SectionPage 'principal' s'il n'existe pas encore (DB de dev incomplète)."""
    from django.db.models import Q
    from cms.models import SectionPage, HomePage
    if SectionPage.objects.filter(Q(slug='principal') | Q(legacy_site_slug='principal')).exists():
        return
    home = HomePage.objects.filter(slug='home').first()
    if not home:
        return
    home.add_child(instance=SectionPage(
        title='CNT-SO confédération',
        slug='principal',
        section_type='main',
        live=True,
        legacy_site_slug='principal',
    ))


def migrate_site_ids_to_section_page(apps, schema_editor):
    _ensure_principal_section_page()
    SectionPage = apps.get_model('cms', 'SectionPage')
    Site = apps.get_model('content', 'Site')

    sp_cache = {}
    for sp in SectionPage.objects.all():
        for slug in (sp.slug, sp.legacy_site_slug):
            if slug and slug not in sp_cache:
                sp_cache[slug] = sp.pk

    def sp_pk_for_old_id(old_id):
        try:
            site = Site.objects.get(pk=old_id)
            return sp_cache.get(site.slug)
        except Site.DoesNotExist:
            return None

    for app_label, model_name, field_id in [
        ('adhesion', 'FormulaireAdhesion', 'site_id'),
        ('adhesion', 'ZoneGeographique', 'site_id'),
        ('adhesion', 'Adhesion', 'site_id'),
    ]:
        Model = apps.get_model(app_label, model_name)
        mapping = {}
        to_nullify = []
        for obj in Model.objects.filter(**{f'{field_id}__isnull': False}):
            new_pk = sp_pk_for_old_id(getattr(obj, field_id))
            if new_pk is not None:
                mapping[obj.pk] = new_pk
            else:
                to_nullify.append(obj.pk)
        all_pks = list(mapping.keys()) + to_nullify
        if all_pks:
            Model.objects.filter(pk__in=all_pks).update(**{field_id: None})
        for obj_pk, new_pk in mapping.items():
            Model.objects.filter(pk=obj_pk).update(**{field_id: new_pk})


class Migration(migrations.Migration):

    dependencies = [
        ('adhesion', '0001_initial'),
        ('cms', '0002_sectionpage_contact_email_wp_blog_id_path'),
        ('content', '0019_migrate_site_fks_to_sectionpage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='formulaireadhesion',
            name='fixed_amount_cents',
            field=models.PositiveIntegerField(blank=True, help_text='Stocké en centimes en interne', null=True, verbose_name='Montant fixe'),
        ),

        # ── A : sans contrainte DB ─────────────────────────────────────────────
        migrations.AlterField(
            model_name='adhesion', name='site',
            field=models.ForeignKey('cms.sectionpage', on_delete=django.db.models.deletion.PROTECT,
                related_name='adhesions', verbose_name='Syndicat',
                null=True, blank=True, db_constraint=False),
        ),
        migrations.AlterField(
            model_name='formulaireadhesion', name='site',
            field=models.OneToOneField('cms.sectionpage', on_delete=django.db.models.deletion.CASCADE,
                related_name='formulaire_adhesion', verbose_name='Syndicat',
                null=True, blank=True, db_constraint=False),
        ),
        migrations.AlterField(
            model_name='zonegeographique', name='site',
            field=models.ForeignKey('cms.sectionpage', on_delete=django.db.models.deletion.CASCADE,
                related_name='zones_geographiques', verbose_name='Site régional',
                null=True, blank=True, db_constraint=False),
        ),

        # ── B : migration de données ───────────────────────────────────────────
        migrations.RunPython(migrate_site_ids_to_section_page, migrations.RunPython.noop),

        # ── C : restaurer les contraintes FK ──────────────────────────────────
        migrations.AlterField(
            model_name='adhesion', name='site',
            field=models.ForeignKey('cms.sectionpage', on_delete=django.db.models.deletion.PROTECT,
                related_name='adhesions', verbose_name='Syndicat'),
        ),
        migrations.AlterField(
            model_name='formulaireadhesion', name='site',
            field=models.OneToOneField('cms.sectionpage', on_delete=django.db.models.deletion.CASCADE,
                related_name='formulaire_adhesion', verbose_name='Syndicat'),
        ),
        migrations.AlterField(
            model_name='zonegeographique', name='site',
            field=models.ForeignKey('cms.sectionpage', on_delete=django.db.models.deletion.CASCADE,
                related_name='zones_geographiques', verbose_name='Site régional'),
        ),
    ]
