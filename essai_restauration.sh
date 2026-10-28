#!/bin/bash
# Restauration d'essai : la dernière sauvegarde automatique est-elle utilisable ?
#
# À lancer SUR le serveur : cd /var/www/cntso && ./essai_restauration.sh
#
# Une sauvegarde qu'on n'a jamais restaurée n'est qu'un espoir. Celle-ci est
# chargée dans une base TEMPORAIRE (la prod n'est pas touchée), comparée à la
# prod table par table, puis Django y est branché en lecture. La base est
# supprimée à la fin, même en cas d'échec. Premier essai réussi : 28/10/2026
# (85 tables, 51 924 lignes identiques, 282 migrations).
set -euo pipefail
cd "$(dirname "$0")"
SAUV=$(ls -1t ~/cntso-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9].sql.gz | head -1)
PROPRIO=$(sudo -u postgres psql -Atc "select pg_get_userbyid(datdba) from pg_database where datname='cntso'")
ESSAI=cntso_essai_restauration
nettoyer() { sudo -u postgres dropdb --if-exists $ESSAI; rm -f /tmp/essai_restau.py /tmp/compte_*.txt; }
trap nettoyer EXIT
echo "   sauvegarde : $SAUV ($(stat -c%s "$SAUV") octets) ; propriétaire : $PROPRIO"
sudo -u postgres dropdb --if-exists $ESSAI
sudo -u postgres createdb -O "$PROPRIO" $ESSAI
debut=$(date +%s)
zcat "$SAUV" | sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d $ESSAI > /tmp/restau.log 2>&1 && echo "   ✓ restaurée sans erreur en $(( $(date +%s) - debut )) s" || { echo "   ✗ ÉCHEC"; tail -5 /tmp/restau.log; exit 1; }
rm -f /tmp/restau.log
COMPTE="select table_name || '|' || (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1"
sudo -u postgres psql -Atc "$COMPTE" cntso > /tmp/compte_prod.txt
sudo -u postgres psql -Atc "$COMPTE" $ESSAI > /tmp/compte_essai.txt
echo "   tables : prod $(wc -l < /tmp/compte_prod.txt), restaurée $(wc -l < /tmp/compte_essai.txt) ; lignes : prod $(awk -F'|' '{s+=$2} END{print s}' /tmp/compte_prod.txt), restaurée $(awk -F'|' '{s+=$2} END{print s}' /tmp/compte_essai.txt)"
echo "   tables qui diffèrent (prod → restaurée) :"
join -t'|' /tmp/compte_prod.txt /tmp/compte_essai.txt -a1 -a2 -e ABSENTE -o 0,1.2,2.2 | awk -F'|' '$2!=$3 {print "     " $1 " : " $2 " → " $3}'
cat > /tmp/essai_restau.py <<'PYS'
from cntso.settings import *  # noqa
DATABASES = {**DATABASES, 'default': {**DATABASES['default'], 'NAME': 'cntso_essai_restauration'}}
PYS
echo "   Django sur la base restaurée :"
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=essai_restau venv/bin/python manage.py showmigrations --plan 2>&1 | awk '/\[ \]/{n++} /\[X\]/{x++} END{print "     migrations appliquées " x+0 ", en attente " n+0}'
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=essai_restau venv/bin/python manage.py shell -c "
from django.db import connection
from cms.models import ArticlePage, SectionPage
from wagtail.images import get_image_model
print('     base :', connection.settings_dict['NAME'], '; articles publics', ArticlePage.objects.publics().count(), '; syndicats', SectionPage.objects.count(), '; images', get_image_model().objects.count())
" 2>&1 | grep "base :"
echo "═══ Restauration d'essai terminée ═══"
