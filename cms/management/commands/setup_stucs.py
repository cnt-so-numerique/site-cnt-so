"""
Configure le sous-site STUCS : catégories + champs SectionPage.

Usage :
    python manage.py setup_stucs
    python manage.py setup_stucs --linkstack https://linkstack.fr/@stucs_cntso
    python manage.py setup_stucs --framaform https://framaforms.org/adherer-au-stucs-...
"""
from django.core.management.base import BaseCommand

STUCS_CATEGORIES = [
    ('communiques', 'Communiqués'),
    ('videos', 'Vidéos'),
    ('visuels', 'Visuels à télécharger'),
    ('greve', 'Grève'),
    ('antifascisme', 'Antifascisme'),
    ('fanzine', 'Fanzine'),
    ('revue-de-presse', 'Revue de presse'),
]


class Command(BaseCommand):
    help = "Configure le sous-site STUCS (catégories, champs SectionPage)"

    def add_arguments(self, parser):
        parser.add_argument('--linkstack', default='https://linkstack.fr/@stucs_cntso')
        parser.add_argument('--framaform', default='https://framaforms.org/adherer-au-stucs-1733747573')

    def handle(self, *args, **options):
        from cms.models import SectionPage, CmsCategory

        stucs = SectionPage.objects.filter(slug='stucs').first()
        if not stucs:
            self.stderr.write('SectionPage "stucs" introuvable.')
            return

        # Mettre à jour les champs
        stucs.linkstack_url = options['linkstack']
        stucs.framaform_url = options['framaform']
        stucs.save(update_fields=['linkstack_url', 'framaform_url'])
        self.stdout.write(f'  SectionPage STUCS mise à jour')
        self.stdout.write(f'    linkstack_url = {stucs.linkstack_url}')
        self.stdout.write(f'    framaform_url = {stucs.framaform_url}')

        # Créer les catégories
        self.stdout.write('Catégories :')
        for slug, name in STUCS_CATEGORIES:
            obj, created = CmsCategory.objects.get_or_create(
                slug=slug, section_slug='stucs',
                defaults={'name': name},
            )
            status = 'créée' if created else 'existante'
            self.stdout.write(f'  {status} : {name}')

        self.stdout.write(self.style.SUCCESS('STUCS configuré.'))
