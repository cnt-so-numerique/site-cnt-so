"""
Récupère depuis le vieux WordPress les fichiers media legacy manquants.

Les `content.Media` importés de WordPress portent un original_url du type
/media/uploads/[sites/N/]YYYY/MM/fichier.ext ; le fichier correspondant est
attendu sous MEDIA_ROOT/uploads/... (cf. Media.url). Beaucoup n'ont jamais
été copiés : cette commande les retélécharge depuis
https://cnt-so.org/wp-content/uploads/<même chemin> tant que le vieux
serveur est en ligne. Aucune écriture en base — les fichiers sont déposés
là où Media.url les attend déjà.

Usage :
    python manage.py recover_legacy_media --dry-run
    python manage.py recover_legacy_media
    python manage.py recover_legacy_media --limit 50
"""
import os
import time
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

WP_UPLOADS_BASE = 'https://cnt-so.org/wp-content/uploads/'
MEDIA_URL_PREFIX = '/media/uploads/'


class Command(BaseCommand):
    help = "Retélécharge les fichiers media legacy manquants depuis le vieux WordPress"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=0,
                            help='Nombre maximum de fichiers à télécharger (0 = tous)')

    def handle(self, *args, **options):
        from content.models import Media

        dry_run = options['dry_run']
        limit = options['limit']
        media_root = settings.MEDIA_ROOT

        missing = []
        for m in Media.objects.all().only('file', 'original_url'):
            if m.file:
                continue
            if not m.original_url.startswith(MEDIA_URL_PREFIX):
                continue
            rel = m.original_url[len('/media/'):]  # uploads/...
            local_path = os.path.join(media_root, rel)
            if not os.path.exists(local_path):
                missing.append((rel, local_path))

        self.stdout.write(f'{len(missing)} fichiers manquants')
        if dry_run:
            for rel, _ in missing[:10]:
                self.stdout.write(f'  ex : {rel}')
            self.stdout.write('=== DRY-RUN, rien téléchargé ===')
            return

        if limit:
            missing = missing[:limit]

        ok = errors = 0
        for i, (rel, local_path) in enumerate(missing, 1):
            url = WP_UPLOADS_BASE + rel[len('uploads/'):]
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'cntso-recover/1.0'})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(data)
                ok += 1
            except Exception as e:
                errors += 1
                self.stderr.write(f'  ERREUR {rel}: {e}')
            if i % 50 == 0:
                self.stdout.write(f'  ... {i}/{len(missing)} ({ok} ok, {errors} erreurs)')
            time.sleep(0.2)  # ménage le vieux serveur

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {ok} téléchargés, {errors} erreurs sur {len(missing)} manquants'
        ))
