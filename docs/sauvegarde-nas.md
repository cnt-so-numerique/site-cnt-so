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

## État de la mise en place (2026-07-12)

Côté **serveur** (fait) :
- [x] Cron `pg_backup` : dump quotidien des deux bases à 3h30 (`/etc/cron.d/pg_backup`)
- [x] Utilisateur `nasbackup` créé, mot de passe verrouillé
- [x] Clés publiques du NAS installées dans `/home/nasbackup/.ssh/authorized_keys`
  avec restrictions :

```
restrict,command="/usr/bin/rrsync -ro /var/backups/postgres" ssh-ed25519 … nas-dumps
restrict,command="/usr/bin/rrsync -ro /var/www/cntso/media" ssh-ed25519 … nas-media
```

Côté **NAS** (« nononas », DS224+, `192.168.1.27`) — fait :
- [x] Clés privées : `/var/services/homes/nononas/.ssh/id_dumps` et `id_media`
  (⚠️ pas dans le partage : le chemin avec espaces casse l'option `-e` de rsync)
- [x] Destination : `/volume2/sauvegarde a froid/backup-cnt/{postgres,media}`
  (volume2 chiffré, ~900 Go libres)
- [x] Script : `/volume2/sauvegarde a froid/backup-cnt/backup-cnt.sh`
- [x] Testé : pull des dumps OK ; écriture vers le serveur bien refusée par rrsync
- [x] Premier passage complet lancé (media ~7,5 Go)

Reste à faire **une fois, dans l'interface DSM** (seule étape impossible en SSH sans root) :
- [ ] **Créer la tâche planifiée** : Panneau de configuration → Planificateur de tâches
  → Créer → Tâche planifiée → Script défini par l'utilisateur :
  - Utilisateur : **nononas** (pas besoin de root)
  - Planification : tous les jours à **4h30** (après le dump serveur de 3h30)
  - Script : `sh "/volume2/sauvegarde a froid/backup-cnt/backup-cnt.sh"`
  - Onglet Paramètres du planificateur : activer l'e-mail en cas d'échec (optionnel)

### Vérification (à tout moment)
```bash
ssh nononas@192.168.1.27
tail "/volume2/sauvegarde a froid/backup-cnt/backup.log"
ls -lh "/volume2/sauvegarde a froid/backup-cnt/postgres/"   # les .dump
du -sh "/volume2/sauvegarde a froid/backup-cnt/media/"      # ≈ taille du media serveur
```

### (Recommandé) Snapshots
Si le volume 2 est en **btrfs** : installer « Snapshot Replication » et planifier un
snapshot quotidien de « sauvegarde a froid » (rétention ~4 semaines). Protège le miroir
media contre une suppression accidentelle côté serveur qui serait propagée par `--delete`.

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
