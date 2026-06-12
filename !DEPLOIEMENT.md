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
| Dossier site    | `/var/www/cntso/`                               |
| Remote GitHub   | `https://github.com/cnt-so-numerique/site-cnt-so.git` |
| Process manager | `supervisor` (pas systemctl)                    |
| Service         | `cntso`                                         |
| Web server      | nginx (reverse proxy)                           |
| Socket          | `/var/www/cntso/cntso.sock`                     |

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
