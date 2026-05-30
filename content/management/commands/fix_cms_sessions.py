"""
Corrige les sessions Django dont le site_id pointe vers un PK inexistant.

À lancer après chaque `python manage.py migrate` sur un environnement
qui avait des sessions actives avant la migration content.Site → cms.SectionPage.

Usage:
    python manage.py fix_cms_sessions          # corrige + rapport
    python manage.py fix_cms_sessions --dry-run # rapport sans modifier
"""
from django.core.management.base import BaseCommand
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.utils import timezone


SESSION_KEYS = ('cms_current_site_id', 'redac_current_site_id')


class Command(BaseCommand):
    help = 'Corrige les sessions CMS avec des site_id obsolètes (post-migration SectionPage)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Affiche ce qui serait corrigé sans modifier les sessions',
        )

    def handle(self, *args, **options):
        from cms.models import SectionPage
        dry_run = options['dry_run']

        valid_pks = set(SectionPage.objects.values_list('pk', flat=True))
        active_sessions = Session.objects.filter(expire_date__gt=timezone.now())

        checked = fixed = cleared = errors = 0

        for record in active_sessions:
            checked += 1
            try:
                store = SessionStore(session_key=record.session_key)
                data = store.load()

                stale_keys = [
                    k for k in SESSION_KEYS
                    if data.get(k) is not None and data[k] not in valid_pks
                ]
                if not stale_keys:
                    continue

                user_id = data.get('_auth_user_id', '?')
                for k in stale_keys:
                    old_pk = data[k]
                    self.stdout.write(
                        f'  session ...{record.session_key[-8:]} '
                        f'user={user_id} {k}={old_pk} → supprimé'
                    )
                    data.pop(k, None)

                if not dry_run:
                    encoded = store.encode(data)
                    Session.objects.filter(session_key=record.session_key).update(
                        session_data=encoded
                    )

                cleared += len(stale_keys)
                fixed += 1

            except Exception as e:
                errors += 1
                self.stderr.write(f'  Erreur session {record.session_key[:8]}: {e}')

        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefix}{checked} sessions analysées — '
            f'{fixed} corrigées, {cleared} clés supprimées, {errors} erreurs'
        ))
        if fixed and dry_run:
            self.stdout.write('  (relancez sans --dry-run pour appliquer)')
