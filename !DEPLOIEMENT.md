# Déploiement CNT-SO — Fiche récap

## Problème SSH habituel

La clé SSH a une passphrase. Elle doit être déverrouillée **une fois par session de travail**.

```bash
ssh-add ~/.ssh/id_ed25519
# → entre ta passphrase → actif jusqu'à fermeture du terminal
```

Vérification :
```bash
ssh -T git@github.com
# → "Hi arnaud2riviere! You've successfully authenticated"
```

---

## Workflow complet de déploiement

### 1. Déverrouiller la clé (si pas encore fait)
```bash
ssh-add ~/.ssh/id_ed25519
```

### 2. Pusher le code depuis la machine locale
```bash
cd "/home/arnaud/PycharmProjects/site cnt"
git push cnt main
```

### 3. Déployer sur le serveur
```bash
ssh debian@51.91.242.64
```

Une fois connecté au serveur :
```bash
cd /var/www/cntso
sudo -u postgres pg_dump cntso | gzip > ~/cntso-$(date +%Y%m%d-%H%M).sql.gz
git pull --ff-only
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py fix_cms_sessions --dry-run   # puis sans --dry-run si besoin
sudo supervisorctl restart cntso
```

⚠️ **La sauvegarde doit passer par `sudo -u postgres`.** La base appartient au
rôle `cntso` ; un `pg_dump cntso` lancé tel quel par l'utilisateur `debian`
échoue avec « role "debian" does not exist » — et si la sortie est redirigée
vers un `gzip`, l'échec est **silencieux** : on obtient un fichier de 20 octets
qui ressemble à une sauvegarde et n'en est pas (constaté le 26/08/2026).
Toujours vérifier la taille : un dump complet pèse une dizaine de Mo.
```bash
ls -lh ~/cntso-*.sql.gz | tail -1     # ~10 Mo attendu, pas 20 octets
```

### Vérifier qu'une sauvegarde se restaure vraiment

Une sauvegarde jamais restaurée n'est pas une sauvegarde. La vérification se
fait sur une base jetable, sans jamais toucher `cntso`. Faite le 27/08/2026 :
88 tables des deux côtés, les 13 tables essentielles au nombre de lignes près,
et Django tourne dessus sans écart de schéma.

```bash
sudo -u postgres createdb cntso_verif
zcat ~/cntso-AAAAMMJJ-HHMM.sql.gz | sudo -u postgres psql -q cntso_verif

# Comparer quelques tables entre la vivante et la restaurée
for t in cms_articlepage cms_sectionpage wagtailcore_page auth_user; do
  echo "$t : $(sudo -u postgres psql -tAc "SELECT count(*) FROM $t;" cntso)" \
       "vs $(sudo -u postgres psql -tAc "SELECT count(*) FROM $t;" cntso_verif)"
done

# Preuve de bout en bout : Django lit-il vraiment cette base ?
sudo -u postgres psql -q -c "GRANT ALL ON DATABASE cntso_verif TO cntso;"
sudo -u postgres psql -q cntso_verif -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO cntso; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO cntso;"
cd /var/www/cntso && venv/bin/python - <<'EOF'
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cntso.settings')
django.setup()
from django.db import connections
connections.databases['default']['NAME'] = 'cntso_verif'   # jamais la vivante
from django.core.management import call_command
call_command('migrate', '--check', verbosity=0)
from cms.models import ArticlePage
a = ArticlePage.objects.live().first()
print('OK :', a.title[:40], '—', len([b for b in a.body]), 'blocs')
EOF

sudo -u postgres dropdb cntso_verif      # NE PAS OUBLIER
```

⚠️ La restauration ne pèse pas la même taille que la base vivante (49 Mo
contre 75 le 27/08) : c'est normal, un rechargement à neuf n'a ni tuples morts
ni index fragmentés. **Comparer les nombres de lignes, pas les tailles.**

### 4. Vérifier que le site répond
```bash
sudo supervisorctl status cntso
# → cntso   RUNNING   pid XXXXX, uptime ...
```

---

## Infos serveur

| Élément         | Valeur                                          |
|-----------------|-------------------------------------------------|
| Serveur         | `debian@51.91.242.64`                           |
| URL actuelle    | `https://newsite.cnt-so.org`                    |
| Dossier site    | `/var/www/cntso/`                               |
| Remote GitHub   | `https://github.com/cnt-so-numerique/site-cnt-so.git` |
| Process manager | `supervisor` (pas systemctl)                    |
| Service         | `cntso`                                         |
| Web server      | nginx (reverse proxy)                           |
| Socket          | `/var/www/cntso/cntso.sock`                     |

---

## ⚠️ Bascule DNS cnt-so.org → nouveau site (état vérifié le 2026-09-02)

### 🔴 L'ancien site est TOMBÉ — la bascule n'est plus une amélioration

```
cnt-so.org        → 5.196.74.69   HTTP 500   « Database Error »
www.cnt-so.org    → 5.196.74.69   ne répond pas
educ.cnt-so.org   → 5.196.74.69   HTTP 500   « Database Error »
/wp-admin/, /wp-login.php, /feed/            HTTP 500
SSH port 22 sur 5.196.74.69                  connexion refusée
```

**L'adresse principale du syndicat sert une page d'erreur WordPress à tout
visiteur** — celle qui est sur les tracts et dans les moteurs de recherche. Ce
n'est pas la base Django : c'est la base MySQL de l'ancien WordPress.

Conséquences :
- l'administration WP est inaccessible (`wp-login.php` répond 500) : **les
  articles publiés là-bas depuis mars sont enfermés**, ni consultables ni
  exportables tant que l'hébergeur ne relance pas la base ;
- le point 5 ci-dessous — « garder l'ancien serveur accessible en lecture » —
  **est caduc**, il n'y a plus rien à lire ;
- basculer le DNS **répare cnt-so.org pour le public**, indépendamment de la
  récupération des articles.

### 🔴 DEUX BLOQUANTS À RÉGLER AVANT DE TOUCHER AU DNS

**A. 346 fichiers legacy servis par l'ancien serveur.**

Contrairement à ce que laissait croire l'erreur 500, **Apache sert toujours les
fichiers statiques** de l'ancien serveur : seules PHP et MySQL sont à terre. Une
image legacy répond aujourd'hui en 200 (vérifié : 52 906 octets).

```
273 contenus EN LIGNE référencent cnt-so.org/wp-content/uploads/
346 URL distinctes : 132 png · 130 jpg · 78 pdf · 6 odt
répartition : 13 (178) · education (66) · auvergne (14)
              rhone-alpes (12) · principal (2) · poitiers (1)
```

Ces URL pointent `cnt-so.org`. **Le jour où ce nom pointera sur 51.91.242.64,
les 346 fichiers disparaîtront** — le nouveau serveur ne les a pas. Images
cassées et PDF morts sur 273 contenus en ligne.

Trois issues possibles, à trancher :
1. **Rapatrier les 346 fichiers** par HTTP (ils répondent encore) et les servir
   depuis nginx sur le nouveau serveur — le plus sûr, et faisable tout de suite
   sans accès SSH à l'ancien ;
2. réécrire les URL dans les contenus vers les images déjà importées dans
   Wagtail, quand l'équivalent existe ;
3. garder un nom dédié (`old.cnt-so.org`) pointant sur 5.196.74.69 et réécrire
   les URL — dépend de la survie d'un serveur en panne.

⚠️ L'ancienne note disait « garder l'ancien serveur accessible en lecture ».
C'est insuffisant : ce n'est pas l'accès qui manquera, c'est **le nom de
domaine**, qui aura changé de machine.

**B. Une double barre oblique casse le nom d'hôte** (`cntso/middleware.py:85`).

```
/13/wp-content/…    → https://13.cnt-so.org/wp-content/…     correct
//13/wp-content/…   → https://13.cnt-so.org3/wp-content/…    hôte inexistant
```

```python
seg  = path.lstrip('/').split('/', 1)[0]   # "//13/x" → seg = "13"
rest = path[len(seg) + 1:]                 # path[3:] = "3/x"  ← décalage
```

`len(seg) + 1` suppose une seule barre en tête. Or **les 346 URL legacy
contiennent précisément `cnt-so.org//13/…`** — avec la double barre. Après la
bascule, elles tomberaient donc sur un hôte malformé, en plus d'être absentes.

Sans effet aujourd'hui : personne n'atteint `newsite.cnt-so.org//13/…`. Le
défaut ne se réveille qu'à la bascule.

### État de chaque prérequis, mesuré sur le serveur

| Point | État au 2026-09-02 |
|---|---|
| `ALLOWED_HOSTS` | `['51.91.242.64', 'newsite.cnt-so.org']` + les 7 `FEDERATION_DOMAINS`. **Manquent `cnt-so.org`, `www.cnt-so.org`, `educ.cnt-so.org`** |
| `MAIN_SITE_BASE_URL` | `https://newsite.cnt-so.org` — à passer à `https://cnt-so.org` |
| nginx `server_name` | 8 noms (newsite + 6 fédérations + IP). **Mêmes 3 manquants** |
| Certificat `newsite.cnt-so.org` | 8 noms. **Mêmes 3 manquants.** Expire le **2026-10-15** |
| `FEDERATION_DOMAINS` | 7 domaines dans supervisor. **`educ.cnt-so.org` absent** |
| Formulaires de contact | 7 syndicats sur 8 ont leur adresse. **Seul le 34 (Hérault) retombe sur `contact@cnt-so.org`** — normal, syndicat en attente |
| hCaptcha | à vérifier dans le tableau de bord (hors de portée depuis le serveur) |

⚠️ **Piège relevé** : `local_settings.py` ligne 7 **écrase** l'`ALLOWED_HOSTS` de
`settings.py`, qui contenait déjà `cnt-so.org` et `www.cnt-so.org`. Les y remettre
dans `settings.py` ne suffirait donc pas — c'est `local_settings.py` qu'il faut
modifier.

### Le jour de la bascule

**1. `local_settings.py` du serveur** (`/var/www/cntso/cntso/local_settings.py`) :
```python
ALLOWED_HOSTS = ['cnt-so.org', 'www.cnt-so.org', 'educ.cnt-so.org',
                 'newsite.cnt-so.org', '51.91.242.64']
MAIN_SITE_BASE_URL = 'https://cnt-so.org'
```

**2. supervisor** — ajouter `educ.cnt-so.org` à `FEDERATION_DOMAINS`
(`/etc/supervisor/conf.d/cntso.conf`), puis `sudo supervisorctl reread &&
sudo supervisorctl update`.

**3. nginx** — les DEUX blocs (80 et 443) de `/etc/nginx/sites-enabled/cntso` :
```
server_name 51.91.242.64 cnt-so.org www.cnt-so.org educ.cnt-so.org
            newsite.cnt-so.org stucs.cnt-so.org 34.cnt-so.org
            numerique.cnt-so.org 13.cnt-so.org 86.cnt-so.org
            auvergne.cnt-so.org rhone-alpes.cnt-so.org;
```

**4. DNS** (zone `cnt-so.org` chez OVH) : `cnt-so.org` (A), `www` et `educ`
→ `51.91.242.64`.

**5. Certificat, APRÈS le DNS** — la validation HTTP échoue tant que le nom
pointe ailleurs. Repasser **tous** les noms, jamais le nouveau seul :
```bash
sudo certbot --nginx --cert-name newsite.cnt-so.org --expand -n \
  -d newsite.cnt-so.org -d cnt-so.org -d www.cnt-so.org -d educ.cnt-so.org \
  -d 13.cnt-so.org -d 34.cnt-so.org -d 86.cnt-so.org -d auvergne.cnt-so.org \
  -d numerique.cnt-so.org -d rhone-alpes.cnt-so.org -d stucs.cnt-so.org
```

**6. hCaptcha** — ajouter `cnt-so.org` et `educ.cnt-so.org` dans le tableau de
bord, sinon tous les formulaires publics refusent l'envoi.

**7. Vérifications** :
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://cnt-so.org/          # 200
curl -s -o /dev/null -w "%{http_code}\n" https://cnt-so.org/cms/      # 302
curl -s -o /dev/null -w "%{http_code}\n" https://educ.cnt-so.org/     # 200
curl -sI https://cnt-so.org/ | grep -i strict-transport                # HSTS
curl -s https://cnt-so.org/sitemap.xml | grep -c "<loc>"               # ~816
```

### Ce que la bascule répare toute seule

- **`cnt-so.org`** cesse de servir une page d'erreur ;
- `educ.cnt-so.org` sert le site Wagtail et **remplace l'ancien Éducation** ;
- l'entrée de menu « Liens CNT-SO » du site Éducation, qui pointe
  `https://cnt-so.org` et donne aujourd'hui un 500, redevient valide.

Note : les redirections WordPress (`/YYYY/MM/slug/`) sont déjà gérées côté Django
par `WordPressRedirectView`.

## Commandes supervisor utiles

```bash
sudo supervisorctl status          # état de tous les services
sudo supervisorctl restart cntso   # redémarrer le site
sudo supervisorctl stop cntso      # arrêter
sudo supervisorctl start cntso     # démarrer
```

## Logs en cas de problème

```bash
# Log gunicorn (stdout + stderr redirigés)
sudo tail -f /var/log/cntso.log

# Logs nginx
sudo tail -f /var/log/nginx/error.log

# Logs supervisor (événements start/stop/crash)
sudo journalctl -u supervisor --since '10 minutes ago' --no-pager
```

---

## Problèmes connus et solutions

### 502 Bad Gateway après restart — socket "Permission denied"

**Cause** : gunicorn tourne en `user=www-data` mais le répertoire `/var/www/cntso/` est
owned by `debian`. www-data ne peut pas créer le socket → crash en boucle.

**Fix déjà appliqué** : le supervisor config est `user=debian`.
Config : `/etc/supervisor/conf.d/cntso.conf`

Si le bug revient (ex. après update de la config) :
```bash
sudo bash -c "sed -i 's/^user=www-data/user=debian/' /etc/supervisor/conf.d/cntso.conf"
sudo supervisorctl reread && sudo supervisorctl update && sudo supervisorctl restart cntso
```

### Vieux processus gunicorn en daemon (orphelins)

Si le site sert du vieux HTML malgré un restart :
```bash
ps aux | grep gunicorn | grep daemon   # chercher d'anciens processus --daemon
# Si trouvés, noter les PIDs et les tuer :
kill <PID1> <PID2> ...
sudo supervisorctl restart cntso
```

---

## Domaines autonomes des fédérations (chantier 2026-07)

Le code (middleware `SectionDomainMiddleware`, SEO par hôte) est déployé et
**inerte** tant que `custom_domain` est vide sur toutes les SectionPages.

### Activation d'un sous-domaine (ex. stucs.cnt-so.org)

1. **DNS** (zone cnt-so.org chez OVH) : enregistrement `A` → `51.91.242.64`
   (ou CNAME vers le nom du serveur). Attendre la propagation (`dig +short stucs.cnt-so.org`).
2. **nginx** : ajouter le nom au `server_name` du vhost cntso (bloc 80 ET 443).
3. **certbot** : étendre le certificat existant en repassant **tous** les noms :
   `sudo certbot --nginx --cert-name newsite.cnt-so.org --expand -n -d newsite.cnt-so.org -d <tous les domaines déjà couverts> -d nouveau.cnt-so.org`
   (lister l'existant avec `sudo certbot certificates`).
   ⚠️ Ne jamais faire `certbot --nginx -d nouveau.cnt-so.org` seul : ça crée un
   certificat isolé qui **remplace** le cert multi-noms dans le vhost et casse
   le HTTPS de tous les autres domaines (incident du 2026-07-17).
4. **Django** : ajouter le domaine à `FEDERATION_DOMAINS` (env supervisor ou
   local_settings : `FEDERATION_DOMAINS = "stucs.cnt-so.org"` — liste séparée
   par des virgules), puis `sudo supervisorctl restart cntso`.
5. **hCaptcha** : ajouter le domaine dans le dashboard hCaptcha (sinon les
   formulaires contact/newsletter seront rejetés sur ce domaine).
6. **Activation** : dans /cms/ → Mon syndicat → fiche du syndicat → panneau
   « Domaine autonome » (superuser) → renseigner `stucs.cnt-so.org` → Publier.
   Effet immédiat : le domaine sert le sous-site, `cnt-so.org/stucs/…` 301 vers
   le domaine, sitemaps/canonicals séparés.
7. **Recette** : home, article, catégorie, contact (envoi réel), feed,
   sitemap.xml, robots.txt, 301 depuis le chemin, /cms/ redirigé vers l'admin
   central.

**Rollback** : vider `custom_domain` sur la fiche → tout revient en chemins.

⚠️ Prérequis global : `MAIN_SITE_BASE_URL` doit pointer vers l'origine publique
du site principal (`https://newsite.cnt-so.org` avant la bascule DNS,
`https://cnt-so.org` après) — utilisé par les canonicals et les renvois
inter-domaines.

⚠️ Cas Éducation : reprendre `educ.cnt-so.org` (référencement existant) n'est
possible qu'à la bascule DNS — ce nom pointe encore vers le vieux serveur WP.
