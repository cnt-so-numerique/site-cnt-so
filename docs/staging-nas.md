# Déploiement staging sur NAS Synology

## Accès au site de staging

- **URL** : http://cnt-so.synology.me
- **Identifiant** : (n'importe quoi)
- **Mot de passe** : `cnt-so-preview`

## Infrastructure

- NAS Synology, volume3, dossier partagé `cnt-so`
- IP locale NAS : `192.168.1.26`
- DDNS Synology : `cnt-so.synology.me`
- Container Docker (image `cnt-so-web`) sur port 8080
- Reverse proxy DSM : `cnt-so.synology.me:80` → `localhost:8080`
- Port forwarding box SFR : port 80 → `192.168.1.26:80`

## Fichier local_settings.py sur le NAS

Ce fichier est **monté en volume** dans le container et n'est jamais transféré depuis la machine locale.
Il doit être recréé manuellement après chaque rebuild.

Emplacement : `/volume3/cnt-so/cntso/local_settings.py`

Contenu :
```python
DEBUG = True
SECRET_KEY = "2hq*2w=a4bgplq4a(f6t3u7idg_vq(18ixyh(=*x8-v$1meq0o"
ALLOWED_HOSTS = ["cnt-so.synology.me", "192.168.1.26", "localhost"]
CSRF_TRUSTED_ORIGINS = ["http://cnt-so.synology.me:8080"]
BASIC_AUTH_PASSWORD = "cnt-so-preview"
```

## Connexion SSH au NAS

```bash
ssh nononas@192.168.1.26
```

## Mettre à jour le site

### 1. Transférer les fichiers (depuis la machine locale)

```bash
cd "/home/arnaud/PycharmProjects/site cnt" && tar -czf - --exclude='./venv' --exclude='./staticfiles' --exclude='./.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='./media' -C . . | ssh nononas@192.168.1.26 "tar -xzf - -C /volume3/cnt-so/"
```

### 2. Rebuilder le container (sur le NAS via SSH)

```bash
cd /volume3/cnt-so && sudo docker-compose down && sudo docker-compose up --build -d
```

### 3. Recréer local_settings.py (sur le NAS via SSH)

```bash
printf 'DEBUG = True\nSECRET_KEY = "2hq*2w=a4bgplq4a(f6t3u7idg_vq(18ixyh(=*x8-v$1meq0o"\nALLOWED_HOSTS = ["cnt-so.synology.me", "192.168.1.26", "localhost"]\nCSRF_TRUSTED_ORIGINS = ["http://cnt-so.synology.me:8080"]\nBASIC_AUTH_PASSWORD = "cnt-so-preview"\n' > /volume3/cnt-so/cntso/local_settings.py && sudo docker-compose restart
```

## Arrêter le staging

```bash
cd /volume3/cnt-so && sudo docker-compose down
```
