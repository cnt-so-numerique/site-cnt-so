from django.db import migrations


def cleanup_menu_items(apps, schema_editor):
    MenuItem = apps.get_model('content', 'MenuItem')
    SectionPage = apps.get_model('cms', 'SectionPage')

    section_ids = SectionPage.objects.filter(
        section_type__in=['sectoral', 'regional'],
    ).values_list('id', flat=True)

    qs = MenuItem.objects.filter(menu='main', site_id__in=list(section_ids))
    for item in qs:
        matches_contact_link_type = item.link_type == 'contact'
        matches_url = item.url in (
            '/contact/',
            f'/{item.site.slug}/contact/',
            f'/{item.site.slug}/rejoindre/',
        )
        if matches_contact_link_type or matches_url:
            item.delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0026_newsletter_articles_vers_articlepage'),
        ('cms', '0018_sectionpage_social_linkedin'),
    ]

    operations = [
        migrations.RunPython(cleanup_menu_items, noop),
    ]
