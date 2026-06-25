#!/usr/bin/env bash
# sync_from_prod.sh — Resynchronise la DB locale (SQLite) depuis la prod (PostgreSQL).
# Usage: ./sync_from_prod.sh
# Prérequis : ssh debian@51.91.242.64 sans mot de passe (clé SSH configurée)
#
# Tables synchronisées :
#   cms_cmscategory              — catégories (DELETE + INSERT)
#   content_menuitem             — menu (DELETE + INSERT, après catégories)
#   cms_articlepage_cms_categories — associations article↔catégorie (DELETE + INSERT)
#   wagtailimages_image          — métadonnées images (INSERT OR IGNORE, pas les fichiers)
#   cms_sectionpage              — config syndicats : logos, réseaux sociaux, emails, textes (UPDATE)
#   cms_carouselarticle          — articles du diaporama homepage (DELETE + INSERT)
#   cms_homepage                 — texte d'intro homepage (UPDATE)

set -euo pipefail

PROD_HOST="debian@51.91.242.64"
SSH_KEY="${HOME}/.ssh/id_ed25519"
TUNNEL_PORT=5433
PGPASSWORD_PROD='gtNalZ@U7&r@%s3hJ@'
PGUSER="cntso"
PGDB="cntso"
TMP_DIR="$(mktemp -d)"
export SYNC_TMP="$TMP_DIR"

close_tunnel() {
    [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null && echo "✔ Tunnel SSH fermé." || true
    rm -rf "$TMP_DIR"
}
trap close_tunnel EXIT

# ── 1. Tunnel SSH ─────────────────────────────────────────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":${TUNNEL_PORT}"; then
    echo "▶ Tunnel SSH déjà actif sur le port ${TUNNEL_PORT}, réutilisation."
    TUNNEL_PID=""
else
    echo "▶ Ouverture du tunnel SSH (port ${TUNNEL_PORT})..."
    ssh -f -N -i "$SSH_KEY" -L "${TUNNEL_PORT}:127.0.0.1:5432" "$PROD_HOST" -o ExitOnForwardFailure=yes
    TUNNEL_PID=$(pgrep -n -f "ssh.*${TUNNEL_PORT}:127.0.0.1:5432" 2>/dev/null || true)
    sleep 1
fi

export PGPASSWORD="$PGPASSWORD_PROD"

# ── 2. Export CSV depuis PostgreSQL ───────────────────────────────────────────
echo "▶ Export des tables depuis la prod..."
psql -h 127.0.0.1 -p "$TUNNEL_PORT" -U "$PGUSER" -d "$PGDB" \
    -c "\COPY cms_cmscategory                TO '${TMP_DIR}/cms_cmscategory.csv'               WITH CSV HEADER NULL '\N'" \
    -c "\COPY content_menuitem               TO '${TMP_DIR}/content_menuitem.csv'              WITH CSV HEADER NULL '\N'" \
    -c "\COPY cms_articlepage_cms_categories TO '${TMP_DIR}/article_cats.csv'                  WITH CSV HEADER NULL '\N'" \
    -c "\COPY wagtailimages_image            TO '${TMP_DIR}/wagtailimages_image.csv'           WITH CSV HEADER NULL '\N'" \
    -c "\COPY cms_sectionpage                TO '${TMP_DIR}/cms_sectionpage.csv'               WITH CSV HEADER NULL '\N'" \
    -c "\COPY cms_carouselarticle            TO '${TMP_DIR}/cms_carouselarticle.csv'           WITH CSV HEADER NULL '\N'" \
    -c "\COPY cms_homepage                   TO '${TMP_DIR}/cms_homepage.csv'                  WITH CSV HEADER NULL '\N'"

echo "   Exports ok → ${TMP_DIR}"

# ── 3. Import dans SQLite via Django shell ─────────────────────────────────────
echo "▶ Import dans SQLite..."
python manage.py shell -c "
import csv, os
from django.db import connection, transaction

TMP = os.environ['SYNC_TMP']

def read_csv(name):
    path = os.path.join(TMP, name)
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = list(reader.fieldnames or [])
    return rows, cols

def normalize(val):
    return None if val in (r'\\\N', '', None) else val

def run(sql):
    with connection.cursor() as cur:
        cur.execute(sql)

def bulk_insert(table, rows, cols):
    if not rows:
        return 0
    ph = ','.join(['?'] * len(cols))
    with connection.cursor() as cur:
        cur.executemany(
            f'INSERT OR IGNORE INTO \"{table}\" ({\",\".join(cols)}) VALUES ({ph})',
            [[normalize(r.get(c)) for c in cols] for r in rows]
        )
    return len(rows)

with transaction.atomic():

    # cms_cmscategory
    rows, cols = read_csv('cms_cmscategory.csv')
    run('DELETE FROM cms_cmscategory')
    print(f'  cms_cmscategory            : {bulk_insert(\"cms_cmscategory\", rows, cols)} lignes')

    # content_menuitem
    rows, cols = read_csv('content_menuitem.csv')
    run('DELETE FROM content_menuitem')
    print(f'  content_menuitem           : {bulk_insert(\"content_menuitem\", rows, cols)} lignes')

    # cms_articlepage_cms_categories
    rows, cols = read_csv('article_cats.csv')
    run('DELETE FROM cms_articlepage_cms_categories')
    print(f'  articlepage_categories     : {bulk_insert(\"cms_articlepage_cms_categories\", rows, cols)} lignes')

    # wagtailimages_image — INSERT OR IGNORE, uploaded_by_user_id forcé NULL
    rows, cols = read_csv('wagtailimages_image.csv')
    safe_cols = [c for c in cols if c != 'uploaded_by_user_id'] + ['uploaded_by_user_id']
    safe_rows = [{**{k: v for k,v in r.items() if k != 'uploaded_by_user_id'}, 'uploaded_by_user_id': None} for r in rows]
    print(f'  wagtailimages_image        : {bulk_insert(\"wagtailimages_image\", safe_rows, safe_cols)} nouvelles entrées')

    # cms_sectionpage — UPDATE uniquement (préserve la structure Wagtail)
    rows, _ = read_csv('cms_sectionpage.csv')
    update_fields = [
        'section_type','description','external_url','agenda_url','logo_id',
        'contact_email','framaform_url','linkstack_url','agenda_text',
        'intro_text','rejoindre_text','canonical_url','og_image_id',
        'social_discord','social_facebook','social_instagram','social_mastodon',
        'social_telegram','social_twitter','social_youtube','social_bluesky',
        'ovh_mailing_list',
    ]
    set_clause = ', '.join(f'\"{f}\"=?' for f in update_fields)
    updated = 0
    with connection.cursor() as cur:
        for r in rows:
            vals = [normalize(r.get(f)) for f in update_fields] + [normalize(r['page_ptr_id'])]
            cur.execute(f'UPDATE cms_sectionpage SET {set_clause} WHERE page_ptr_id=?', vals)
            updated += cur.rowcount
    print(f'  cms_sectionpage            : {updated} sections mises à jour')

    # cms_carouselarticle
    rows, cols = read_csv('cms_carouselarticle.csv')
    run('DELETE FROM cms_carouselarticle')
    print(f'  cms_carouselarticle        : {bulk_insert(\"cms_carouselarticle\", rows, cols)} lignes')

    # cms_homepage — UPDATE intro_text uniquement
    rows, _ = read_csv('cms_homepage.csv')
    updated = 0
    with connection.cursor() as cur:
        for r in rows:
            cur.execute('UPDATE cms_homepage SET intro_text=? WHERE page_ptr_id=?',
                        [normalize(r.get('intro_text')), normalize(r['page_ptr_id'])])
            updated += cur.rowcount
    print(f'  cms_homepage               : {updated} lignes mises à jour')

print('✔ Synchronisation terminée.')
"

echo "✔ Base locale synchronisée avec la prod."
