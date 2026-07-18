# Sauvegarde externalisée sur le NAS Synology

*Révision 2026-07-18 — remplace le montage du 2026-07-12 (voir Historique en bas).*

## Architecture

Le **NAS tire** (pull) les sauvegardes depuis le serveur, jamais l'inverse :
- pas besoin d'exposer le NAS sur internet (connexion SSH sortante uniquement) ;
- un serveur compromis ne peut pas détruire l'historique de sauvegardes.

### Côté serveur — `/var/backups/cnt/` (staging)

Un timer systemd (`pg-backup.timer`, **3h30**) exécute `/usr/local/bin/pg_backup.sh` :

| Sous-dossier | Contenu | Méthode |
|---|---|---|
| `postgres/` | dumps quotidiens des 3 bases (cntso + adhesion + timetrack, cluster dédié :5433), rétention 14 j | `pg_dump -Fc` |
| `media-cntso/` | miroir des uploads du site (≈ 7,5 Go) | liens durs (`rsync --link-dest`, coût disque ≈ 0) |
| `media-cnt-adhesion/` | miroir des uploads adhésion (logos, relevés fiscaux) | idem |
| `secrets/` | `.env` adhésion + `local_settings.py` site + `.env` site (clés API OVH) + `timetrack.env` + `letsencrypt.tar.gz` (certificats TLS), **chiffrés GPG AES-256** ; plus `config-serveur.tar.gz` en clair (vhosts nginx, supervisor, timers systemd, site statique quiz-syntec — aucun secret) | passphrase : `/root/.backup_env_pass` (root only) + gestionnaire de mots de passe d'Arnaud |

⚠️ Le serveur n'a **pas de service cron** : toute planification passe par systemd
(le cron du 12/07 n'a jamais tourné — découvert le 18/07).

### Côté NAS (« nononas », DS224+, `192.168.1.27`)

- **Une seule clé** : `/var/services/homes/nononas/.ssh/nas-cnt`, installée sur le
  serveur pour l'utilisateur `nasbackup` (mot de passe verrouillé) avec
  `restrict,command="/usr/bin/rrsync -ro /var/backups/cnt"` — lecture seule sur le
  staging uniquement, pas de shell, pas de forwarding.
- **Destination** : `/volume2/sauvegardes-cnt/` (volume2 **chiffré**) :
  - `postgres/` : accumulation des dumps, purge à 60 j (le serveur ne garde que 14 j) ;
  - `media/` : miroir du media du site (`--exclude=matomo/tmp`) ;
  - `media-adhesion/` : miroir du media adhésion ;
  - `secrets/` : copies chiffrées ;
  - `backup.log` : journal de chaque passage.
- **Script** : `/volume2/sauvegardes-cnt/backup-cnt.sh`
- **Tâche planifiée DSM** : utilisateur `nononas`, tous les jours à **4h30**,
  script `sh "/volume2/sauvegardes-cnt/backup-cnt.sh"`.

### (Recommandé) Snapshots
Si le volume 2 est en **btrfs** : installer « Snapshot Replication » et planifier un
snapshot quotidien de « sauvegardes-cnt » (rétention ~4 semaines). Protège le miroir
media contre une suppression accidentelle côté serveur qui serait propagée par `--delete`.

## Restauration (résumé)

1. Code : cloner les dépôts GitHub (site + adhésion).
2. Base : copier le dump sur le serveur puis
   `sudo -u postgres pg_restore -d cntso --clean --if-exists cntso-YYYYMMDD-HHMMSS.dump`
   (idem `adhesion`).
3. Médias : rsync du NAS vers `/var/www/cntso/media/` (inverser le sens, clé admin).
4. Secrets : `gpg -d cnt-adhesion.env.gpg > .env` (passphrase dans le gestionnaire
   de mots de passe d'Arnaud), idem `local_settings.py`.

Tester la restauration une fois par an (ou après changement de config serveur) —
une sauvegarde jamais restaurée n'est pas une sauvegarde.

**Dernier test réussi : 2026-07-12** — dump récupéré depuis le NAS et restauré dans
un PostgreSQL 15 jetable (Docker local) : 83 tables, 1 800 articles, 1 878 pages
Wagtail, requêtes de cohérence OK.

## Surveillance

Le log est dans `/volume2/sauvegardes-cnt/backup.log`. Optionnel :
DSM → Planificateur de tâches → Paramètres → envoyer les résultats par e-mail en
cas d'échec.

## Historique

- **2026-07-12** : premier montage — deux clés (`id_dumps`, `id_media`), dumps via
  cron (qui ne tournait pas, faute de service cron), pulls séparés dumps + media.
- **2026-07-18** : refonte — timer systemd fonctionnel, staging unique
  `/var/backups/cnt` (bases + médias × 2 + secrets chiffrés), **clé unique `nas-cnt`**
  (les clés `id_dumps`/`id_media` sont révoquées côté serveur et peuvent être
  supprimées du NAS). Un doublon temporaire créé le même jour sur volume1
  (« sauvegarde base adhesion cnt-so » + tâche « Sauvegarde CNT ») est à retirer
  au profit du volume2 chiffré.
