# Sauvegarde externalisée sur le NAS Synology

## Architecture

Le **NAS tire** (pull) les sauvegardes depuis le serveur, jamais l'inverse :
- pas besoin d'exposer le NAS sur internet (connexion SSH sortante uniquement) ;
- un serveur compromis ne peut pas détruire l'historique de sauvegardes.

Ce qui est sauvegardé, chaque nuit :

| Source (serveur) | Contenu | Stratégie NAS |
|---|---|---|
| `/var/backups/postgres/` | dumps PostgreSQL quotidiens (cntso + adhesion, 3h30, rétention 14 j sur serveur) | accumulation, purge à 60 j |
| `/var/www/cntso/media/` | uploads (≈ 7,5 Go) | miroir rsync |

L'accès se fait via l'utilisateur **`nasbackup`** (créé le 2026-07-12) : mot de passe
verrouillé, connexion par clé uniquement, chaque clé étant **forcée en lecture seule
sur un seul dossier** via `rrsync -ro` (impossible d'écrire, de lire autre chose,
ou d'obtenir un shell).

## Côté serveur — état

- [x] Cron `pg_backup` : dump quotidien des deux bases à 3h30 (`/etc/cron.d/pg_backup`)
- [x] Utilisateur `nasbackup` créé, mot de passe verrouillé, `~/.ssh/authorized_keys` prêt
- [ ] Coller les deux clés publiques du NAS (voir ci-dessous) dans
  `/home/nasbackup/.ssh/authorized_keys` :

```
restrict,command="/usr/bin/rrsync -ro /var/backups/postgres" ssh-ed25519 AAAA… nas-dumps
restrict,command="/usr/bin/rrsync -ro /var/www/cntso/media" ssh-ed25519 AAAA… nas-media
```

## Côté NAS Synology — procédure

### 1. Activer SSH (si pas déjà fait)
DSM → Panneau de configuration → Terminal & SNMP → cocher « Activer le service SSH ».
(Peut être désactivé après la mise en place si souhaité — la tâche planifiée tourne en local.)

### 2. Créer le dossier partagé et les clés
DSM → Panneau de configuration → Dossier partagé → créer **`backup-cnt`**
(désactiver la corbeille réseau, accès admin uniquement).

Puis en SSH sur le NAS (`ssh <admin>@<ip-du-nas>`) :

```bash
sudo mkdir -p /volume1/backup-cnt/keys /volume1/backup-cnt/postgres /volume1/backup-cnt/media
sudo ssh-keygen -t ed25519 -N '' -C nas-dumps -f /volume1/backup-cnt/keys/id_dumps
sudo ssh-keygen -t ed25519 -N '' -C nas-media -f /volume1/backup-cnt/keys/id_media
sudo chmod 600 /volume1/backup-cnt/keys/id_*
cat /volume1/backup-cnt/keys/id_dumps.pub /volume1/backup-cnt/keys/id_media.pub
```

→ transmettre les **deux lignes `.pub`** pour installation sur le serveur (cf. ci-dessus).

### 3. Créer la tâche planifiée
DSM → Panneau de configuration → Planificateur de tâches → Créer → Tâche planifiée
→ Script défini par l'utilisateur :

- **Utilisateur** : `root`
- **Planification** : tous les jours à **4h30** (après le dump serveur de 3h30)
- **Script** :

```sh
#!/bin/sh
KEYS=/volume1/backup-cnt/keys
DEST=/volume1/backup-cnt
LOG=$DEST/backup.log
{
  echo "=== $(date '+%F %T') ==="
  # 1. Dumps PostgreSQL — accumulation, purge à 60 jours
  rsync -a -e "ssh -i $KEYS/id_dumps -o StrictHostKeyChecking=accept-new" \
    nasbackup@51.91.242.64:./ "$DEST/postgres/"
  find "$DEST/postgres" -name '*.dump' -mtime +60 -delete
  # 2. Media — miroir
  rsync -a --delete -e "ssh -i $KEYS/id_media -o StrictHostKeyChecking=accept-new" \
    nasbackup@51.91.242.64:./ "$DEST/media/"
  echo "OK $(date '+%F %T')"
} >> "$LOG" 2>&1
```

### 4. Premier lancement et vérification
Lancer la tâche manuellement (Planificateur → Exécuter). Le premier passage copie
les ~7,5 Go de media (long) ; les suivants ne transfèrent que les nouveautés.

Vérifier :
```bash
tail /volume1/backup-cnt/backup.log
ls -lh /volume1/backup-cnt/postgres/   # les .dump du jour
du -sh /volume1/backup-cnt/media/      # ≈ taille du media serveur
```

### 5. (Recommandé) Snapshots
Si le volume est en **btrfs** : installer « Snapshot Replication » et planifier un
snapshot quotidien de `backup-cnt` (rétention ~4 semaines). Protège le miroir media
contre une suppression accidentelle côté serveur qui serait propagée par `--delete`.

## Restauration (résumé)

```bash
# Base : copier le dump sur le serveur puis
sudo -u postgres pg_restore -d cntso --clean --if-exists cntso-YYYYMMDD-HHMMSS.dump
# Media : rsync du NAS vers /var/www/cntso/media/ (inverser le sens, clé admin)
```

Tester la restauration au moins une fois après la mise en place (sur la base de dev
par exemple) — une sauvegarde jamais restaurée n'est pas une sauvegarde.

## Surveillance

Le log est dans `/volume1/backup-cnt/backup.log`. Optionnel : DSM → Planificateur
de tâches → Paramètres → envoyer les résultats par e-mail en cas d'échec.
