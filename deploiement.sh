#!/bin/bash
# Déploiement du site CNT-SO en production.
#
# À lancer SUR le serveur : cd /var/www/cntso && ./deploiement.sh
#
# ── Pourquoi ce script existe ────────────────────────────────────────────────
#
# `set -euo pipefail` et non `set -e` seul. Le 02/09/2026, un déploiement a
# échoué au `git pull` et s'est poursuivi quand même : la commande était écrite
# `git pull --ff-only | tail -3`, et le code de retour d'un tuyau est celui de
# sa DERNIÈRE commande — `tail`, qui réussit toujours. La sauvegarde a été
# faite, le service redémarré, et le correctif de sécurité n'est jamais parti.
# Le déploiement s'annonçait réussi sans l'être.
#
# Même famille que la sauvegarde de 20 octets d'août : une commande qui échoue
# derrière un tuyau ne dit rien. D'où, ici : pas de tuyau sur ce qui compte.
#
# ── Le contrôle de divergence ────────────────────────────────────────────────
#
# Le serveur tire du dépôt PERSONNEL (arnaud2riviere/site-cnt) et non de celui
# de l'organisation : la politique de cnt-so-numerique interdit les clés de
# déploiement, et git 2.39.5 de Debian 12 ne sait plus transférer d'objets avec
# GitHub en HTTPS — `ls-remote` passe, `fetch` réclame un mot de passe.
#
# Les deux dépôts sont censés être identiques, on pousse aux deux. « Censés »
# est une discipline ; ce contrôle en fait une garantie.
set -euo pipefail
cd "$(dirname "$0")"

echo "═══ 1. Les deux dépôts sont-ils au même point ? ═══"
perso=$(git ls-remote origin main | cut -f1)
orga=$(git ls-remote github-org main | cut -f1)
echo "   personnel    : ${perso:0:8}"
echo "   organisation : ${orga:0:8}"
if [ "$perso" != "$orga" ]; then
    echo "   ✗ ARRÊT : les deux dépôts divergent."
    echo "     Poussez sur les deux avant de déployer."
    exit 1
fi
echo "   ✓ identiques"

if [ "$(git rev-parse HEAD)" = "$perso" ]; then
    echo "═══ Rien à déployer, le serveur est déjà à jour ═══"
    exit 0
fi

echo "═══ 2. Sauvegarde de la base ═══"
sauv=~/cntso-$(date +%Y%m%d-%H%M).sql.gz
# `umask 077` AVANT la redirection, et `chmod 600` après par sécurité : le
# fichier contient TOUTE la base — empreintes de mots de passe, adresses des
# abonnés, messages de contact. Le umask du compte vaut 022, les sauvegardes
# sortaient donc en `-rw-r--r--`, lisibles par tout compte de la machine
# (relevé par Arnaud le 03/09/2026 ; les sauvegardes manuelles antérieures,
# elles, étaient bien en 600).
( umask 077; sudo -u postgres pg_dump cntso | gzip > "$sauv" )
chmod 600 "$sauv"
taille=$(stat -c%s "$sauv")
echo "   $sauv ($taille octets)"
# Une sauvegarde minuscule est une sauvegarde ratée : pg_dump lancé sans le bon
# rôle rend une erreur, gzip l'emballe, et le fichier fait 20 octets (août 2026).
if [ "$taille" -lt 1000000 ]; then
    echo "   ✗ ARRÊT : sauvegarde suspecte (< 1 Mo)"
    exit 1
fi

echo "═══ 3. Code ═══"
avant=$(git rev-parse --short HEAD)
git fetch origin main
git merge --ff-only FETCH_HEAD
echo "   $avant → $(git rev-parse --short HEAD)"

echo "═══ 4. Dépendances, migrations, statiques ═══"
source venv/bin/activate
pip install -q -r requirements.txt
pip check

# Une migration oubliée ne se voit PAS : le code part, `migrate` ne trouve rien
# à appliquer, et la base reste en retard sur les modèles. La panne surgit plus
# tard, sur une requête qui touche la colonne absente. On refuse d'aller plus
# loin (suggéré par Arnaud, 03/09/2026).
if ! python manage.py makemigrations --check --dry-run > /dev/null 2>&1; then
    echo "   ✗ ARRÊT : des modèles ont changé sans migration."
    python manage.py makemigrations --check --dry-run || true
    exit 1
fi
echo "   ✓ aucune migration oubliée"

python manage.py migrate
python manage.py collectstatic --noinput > /dev/null
echo "   ok"

# Informatif : les quatre avertissements connus (HSTS includeSubDomains,
# redirection SSL déléguée à nginx, X_FRAME_OPTIONS que l'aperçu Wagtail exige
# en SAMEORIGIN, préchargement HSTS) sont des choix assumés. On les affiche
# pour qu'un CINQUIÈME se remarque.
echo "═══ 4 bis. Contrôles de déploiement Django ═══"
python manage.py check --deploy 2>&1 | grep -E "^\?:|identified" | sed 's/^/   /' || true

echo "═══ 5. Redémarrage ═══"
sudo supervisorctl restart cntso
sleep 5
sudo supervisorctl status cntso

echo "═══ 6. Contrôle ═══"
base=https://newsite.cnt-so.org
souci=0
for chemin in / /13/ /education/ /contact/ /categorie/droit/ /sitemap.xml; do
    code=$(curl -s -o /dev/null -m 20 -L -w '%{http_code}' "$base$chemin")
    printf '   %-22s %s\n' "$chemin" "$code"
    [ "$code" = "200" ] || souci=1
done
cms=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$base/cms/")
printf '   %-22s %s (302 attendu)\n' "/cms/" "$cms"
[ "$souci" = "0" ] && echo "═══ Déploiement terminé ═══" || { echo "✗ des pages ne répondent pas 200"; exit 1; }
