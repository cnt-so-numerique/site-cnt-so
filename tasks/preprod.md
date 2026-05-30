# Checklist pré-production

Tout ce qui doit être fait **avant** la mise en prod de cnt-so.org.

---

## BLOQUANT — doit être réglé avant déploiement

### Sécurité

- [ ] **Remplacer `SECRET_KEY`** par une vraie clé (50+ chars, aléatoire) via variable d'environnement
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```
  `cntso/settings.py` ligne 23 — la clé actuelle commence par `django-insecure-`

- [ ] **`DEBUG = False`** en production (via variable d'environnement)
  - Ne jamais déployer avec `DEBUG = True`
  - Les tracebacks complets seraient exposés publiquement

### Données prod

- [ ] **Créer le SectionPage 'principal'** avant de lancer `migrate` en prod
  - En dev il n'existait pas → la migration `adhesion/0002` l'a créé automatiquement
  - En prod, vérifier que `SectionPage.objects.filter(slug='principal').exists()` avant migration

- [ ] **Lancer `fix_cms_sessions` après `migrate`** si des utilisateurs sont connectés pendant le déploiement
  ```bash
  python manage.py fix_cms_sessions --dry-run  # vérifier
  python manage.py fix_cms_sessions            # corriger
  ```

---

## IMPORTANT — impact visible utilisateurs

### Configuration

- [ ] **Ajouter `cnt-so.org` dans `ALLOWED_HOSTS`** ✅ déjà fait
  - Vérifier aussi que `CSRF_TRUSTED_ORIGINS` contient `https://cnt-so.org`

- [ ] **`WAGTAILADMIN_BASE_URL = 'https://cnt-so.org'`** ✅ déjà fait
  - Était sur `http://localhost:8000` → liens emails cassés

- [ ] **`DEFAULT_CONTACT_EMAIL`** non défini dans settings
  - Si un FormContact n'a pas d'email configuré, le fallback est vide → contact silencieux
  - Ajouter : `DEFAULT_CONTACT_EMAIL = 'contact@cnt-so.org'`

### Logging

- [ ] **Configurer `LOGGING`** pour capturer les erreurs 500 en production
  ```python
  LOGGING = {
      'version': 1,
      'disable_existing_loggers': False,
      'handlers': {
          'file': {
              'class': 'logging.FileHandler',
              'filename': BASE_DIR / 'logs/django.log',
          },
      },
      'root': {
          'handlers': ['file'],
          'level': 'WARNING',
      },
  }
  ```
  Créer le dossier `logs/` et l'ajouter à `.gitignore`

### Données manquantes

- [ ] **8 MenuItems désactivés** (URSSAF, Pôle Emploi, TPE, Lexique, Tableurs, Liens utiles, Radio/Podcasts, CNT-SO Thiers) — ils étaient type=category sans catégorie liée. À reconfigurer dans le CMS avec les bonnes URLs si nécessaire.

- [ ] **Données des sous-sites** : stucs, education, test n'ont aucun article. Vérifier si c'est voulu.

---

## NICE TO HAVE — améliorations non bloquantes

- [ ] **`robots.txt`** ✅ déjà fait — `/robots.txt` → 200
- [ ] **`favicon.ico`** ✅ déjà fait — redirige vers `/static/image/logocntso.png`
- [ ] **Open Graph / meta description** ✅ déjà fait sur les articles
  - À étendre aux autres pages (catégorie, sous-site, home) si besoin

- [ ] **Mettre à jour les dépendances**
  ```
  Django 6.0.2 → 6.0.5
  Pillow 12.1.1 → 12.2.0
  requests 2.32.5 → 2.34.2
  ```

- [ ] **`Adhesion.status` index** — full scan sur une table qui va grossir
  Ajouter `db_index=True` sur `Adhesion.status` dans `adhesion/models.py`

---

## Procédure de déploiement recommandée

```bash
# 1. Variables d'environnement
export SECRET_KEY="<clé générée>"
export DEBUG=False

# 2. Migrations
python manage.py migrate

# 3. Corriger les sessions actives
python manage.py fix_cms_sessions

# 4. Permissions Wagtail
python manage.py setup_wagtail_permissions

# 5. Fichiers statiques
python manage.py collectstatic --noinput

# 6. Vérification
python manage.py check --deploy
```

---

## Ce qui a été corrigé en dev (déjà dans le code)

| Correction | Fichier |
|---|---|
| N+1 sitemap (270→10 requêtes) | `content/sitemaps.py` |
| N+1 menu (83→30 requêtes home) | `content/templatetags/menu_tags.py` |
| N+1 context processor catégories | `content/context_processors.py` |
| Slugs menu cassés (éducation, STUCS) | `content/context_processors.py` |
| Open Graph + meta description | `templates/base.html`, `templates/content/article_detail.html` |
| Recherche étendue au body | `content/views.py` |
| robots.txt + favicon.ico | `cntso/urls.py`, `templates/robots.txt` |
| ALLOWED_HOSTS + WAGTAILADMIN_BASE_URL | `cntso/settings.py` |
| Sessions corrompues post-migration | `content/management/commands/fix_cms_sessions.py` |
| Migration content.Site → SectionPage | migrations `0019`, `0020`, `adhesion/0002` |
