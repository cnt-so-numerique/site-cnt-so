from django.db import migrations


def allumer_la_conf(apps, schema_editor):
    """Seule la confédération diffuse une newsletter publique.

    Le champ arrive à False pour tout le monde : on rallume la conf, qui est
    le seul site à avoir des listes de diffusion (news, news2, news3). Les
    autres listes OVH sont des listes de travail internes, réservées aux
    adhérent·es (arbitrage d'Arnaud, 17/08/2026) — leurs encarts d'inscription
    menaient à une base que personne n'utilise.
    """
    SectionPage = apps.get_model('cms', 'SectionPage')
    SectionPage.objects.filter(slug='principal').update(newsletter_active=True)
    SectionPage.objects.exclude(slug='principal').update(
        newsletter_active=False, ovh_mailing_list='', ovh_liste_inscription='')


def rallumer_tout(apps, schema_editor):
    """Retour en arrière : on ne restitue que l'interrupteur.

    Les noms de listes effacés ne sont pas récupérables ici ; ils figurent
    dans `tasks/chantier-newsletter-antispam.md` si besoin.
    """
    SectionPage = apps.get_model('cms', 'SectionPage')
    SectionPage.objects.update(newsletter_active=True)


class Migration(migrations.Migration):

    dependencies = [('cms', '0024_sectionpage_newsletter_active')]

    operations = [migrations.RunPython(allumer_la_conf, rallumer_tout)]
