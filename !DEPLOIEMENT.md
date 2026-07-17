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
git pull
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
sudo supervisorctl restart cntso
```

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

## ⚠️ Bascule DNS cnt-so.org → nouveau site (checklist, constat du 2026-07-02)

**État actuel** : `cnt-so.org` pointe encore vers l'ancien WordPress (`5.196.74.69`,
un autre serveur, toujours en ligne). Le site Django/Wagtail n'est public que sur
`newsite.cnt-so.org` (`51.91.242.64`).

Le jour de la bascule (faire AVANT de changer le DNS) :

1. **ALLOWED_HOSTS prod** — le `local_settings.py` du serveur rejette actuellement
   le Host `cnt-so.org` (erreur 400). Ajouter dans
   `/var/www/cntso/cntso/local_settings.py` :
   ```python
   ALLOWED_HOSTS = ['cnt-so.org', 'www.cnt-so.org', 'newsite.cnt-so.org', '51.91.242.64']
   ```

2. **nginx** — élargir le `server_name` du vhost cntso
   (`/etc/nginx/sites-enabled/cntso`) :
   ```
   server_name cnt-so.org www.cnt-so.org newsite.cnt-so.org 51.91.242.64;
   ```

3. **Certificat TLS** — obtenir un certificat pour `cnt-so.org` + `www.cnt-so.org`
   (certbot). Attention : tant que le DNS pointe ailleurs, la validation HTTP
   échouera → utiliser la validation DNS, ou refaire le certbot juste après la
   bascule DNS.

4. **Basculer le DNS** : `cnt-so.org` (A) et `www` → `51.91.242.64`.

5. **Après bascule** :
   - `sudo supervisorctl restart cntso` puis vérifier `https://cnt-so.org/` (200)
     et `https://cnt-so.org/cms/` (302 vers login) ;
   - vérifier le header `Strict-Transport-Security` (déjà actif, 30 jours) ;
   - garder l'ancien serveur WordPress accessible en lecture quelque temps
     (redirections legacy, `wp-content/uploads` encore référencé par les
     images non importées).

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
