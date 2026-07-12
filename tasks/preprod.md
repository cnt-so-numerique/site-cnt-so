# Checklist pré-production

Tout ce qui doit être fait **avant** la mise en prod de cnt-so.org.

---

## BLOQUANT — doit être réglé avant déploiement

### Sécurité

- [x] **Remplacer `SECRET_KEY`** — vérifié en prod le 2026-07-12 : clé de 67 chars,
  non-insecure, définie dans `/var/www/cntso/cntso/local_settings.py` (voie acceptée
  par le garde-fou de `settings.py`)

- [x] **`DEBUG = False`** en production — vérifié en prod le 2026-07-12
  (`local_settings.py` + défaut `False` dans `settings.py`)

### Données prod

- [x] **SectionPage 'principal'** — vérifié en prod le 2026-07-12 :
  `SectionPage.objects.filter(slug='principal').exists()` → `True` ;
  0 migration en attente sur le serveur

- [x] **`fix_cms_sessions`** — exécuté en prod le 2026-07-12 :
  0 sessions à corriger

---

## IMPORTANT — impact visible utilisateurs

### Configuration

- [ ] **Ajouter `cnt-so.org` dans `ALLOWED_HOSTS`** ✅ déjà fait
  - Vérifier aussi que `CSRF_TRUSTED_ORIGINS` contient `https://cnt-so.org`

- [ ] **`WAGTAILADMIN_BASE_URL = 'https://cnt-so.org'`** ✅ déjà fait
  - Était sur `http://localhost:8000` → liens emails cassés

- [x] **`DEFAULT_CONTACT_EMAIL`** — ajouté le 2026-07-12 dans `cntso/settings.py` :
  `DEFAULT_CONTACT_EMAIL = 'contact@cnt-so.org'` (fallback déjà en place dans
  `content/views.py::_send_contact_email`)

### Logging

- [x] **`LOGGING` configuré** — ajouté le 2026-07-12 dans `cntso/settings.py` :
  `logs/django.log` (RotatingFileHandler 5 Mo × 3) + console (stderr → repris par
  supervisor dans `/var/log/cntso.log`), niveau WARNING. `logs/` créé automatiquement
  au démarrage et ajouté à `.gitignore`.

### Données manquantes

- [ ] **MenuItems désactivés** — état prod au 2026-07-12 : 5 sur 8 ont été supprimés
  (URSSAF, Pôle Emploi, Lexique, Tableurs, Liens utiles). Il en reste **3**, tous
  type=category sans catégorie liée — décision éditoriale à prendre dans le CMS :
  - `TPE` (auvergne, sous Ressources) — candidat probable : catégorie « TPE 2021 » (pk 171)
  - `Radio / Podcasts` (poitiers, sous Ressources) — aucune catégorie correspondante
  - `CNT-SO Thiers` (auvergne, sous CNT-SO Auvergne) — aucune catégorie correspondante

- [x] **Données des sous-sites** — vérifié en prod le 2026-07-12 : education a
  **100 articles**, stucs **31**, le site `test` n'existe pas en prod (dev uniquement).
  Seul `numerique` n'a qu'1 article (site récent, attendu). Rien à faire.

---

## NICE TO HAVE — améliorations non bloquantes

- [ ] **`robots.txt`** ✅ déjà fait — `/robots.txt` → 200
- [ ] **`favicon.ico`** ✅ déjà fait — redirige vers `/static/image/logocntso.png`
- [ ] **Open Graph / meta description** ✅ déjà fait sur les articles
  - À étendre aux autres pages (catégorie, sous-site, home) si besoin

- [x] **Dépendances mises à jour** — 2026-07-12 : Django 6.0.2 → 6.0.7,
  Pillow 12.1.1 → 12.3.0, requests 2.32.5 → 2.34.2, certifi et urllib3 aussi.
  562 tests verts après mise à jour.

- [x] **`Adhesion.status` index** — 2026-07-12 : `db_index=True` ajouté dans
  `cnt-adhesion/adhesion/models.py` + migration `0011_alter_adhesion_status`
  (l'app adhesion vit désormais dans le repo cnt-adhesion). 525 tests verts.

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
