# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
cd "/home/arnaud/PycharmProjects/site cnt"
source venv/bin/activate

python manage.py runserver        # Start dev server
python manage.py migrate          # Apply migrations
python manage.py makemigrations   # Create new migrations
python manage.py createsuperuser  # Create admin user
python manage.py test             # Run tests
python manage.py test content     # Run tests for a specific app
```

## Architecture overview

This is a Django 5.2 CMS for the CNT-SO (anarcho-syndicalist union) website, migrated from a WordPress multisite. It uses SQLite in development, Python 3.12, with a venv at `venv/`.

### Multisite model

The central concept is `Site` (in `content/models.py`), representing either the main confederation site (`slug='principal'`) or regional/sectoral sub-sites. All major models (`Article`, `Page`, `Category`, `Tag`, `Media`, `MenuItem`) have a ForeignKey to `Site`. Views always filter by site context.

The main site slug `'principal'` is hardcoded throughout views and context processors as the entry point.

### Apps

**`content/`** — Public-facing app. All models, views, URLs, feeds, sitemaps. No authentication required for reading. URL namespace: `content`.

**`redaction/`** — Internal editorial interface at `/redac/`. No Django models (no migrations). Uses `content` models directly. URL namespace: `redaction`.

### Role-based access in `redaction/`

Three access levels enforced via mixins in `redaction/mixins.py`:
- **superuser** — full access, can manage all sites and users
- **`redacteur_en_chef` group** — manages content, comments, categories; can switch active site via session (`redac_current_site_id`)
- **`redacteur` group** — can create/edit articles and pages on their assigned site only

Groups and permissions are created automatically on `post_migrate` signal in `redaction/apps.py`. A `redacteur` is scoped to a site via `Author.site` (linked to `Author.user` via OneToOneField `author_profile`).

### Context processors

- `content.context_processors.menu_context` — injects `main_site`, `sites`, `regional_sites`, `sectoral_sites`, `main_categories`, `menu_structure` (hardcoded category slugs) into all templates
- `redaction.context_processors.redac_context` — injects `is_chef`, `user_site`, `current_site`, `all_sites` for the editorial interface

### URL routing

```
/                   → content app (HomeView, articles, pages, categories, tags)
/redac/             → redaction app (dashboard, CRUD for articles/categories/tags/etc.)
/admin/             → Django admin
/sitemap.xml        → django.contrib.sitemaps
/<site_slug>/       → sub-site home (SiteHomeView)
```

WordPress legacy URL redirects are handled by `WordPressRedirectView` (date-based `/YYYY/MM/slug/` patterns).

### WordPress import commands

Located in `content/management/commands/`:
- `import_wordpress.py` — main import from WP export
- `import_comments.py` — import comments
- `import_featured_images.py` — import featured images
- `fix_media_urls.py` — fix media URLs post-import

All models include `wp_id` (nullable IntegerField) and `wp_date` fields to preserve WordPress metadata.

### Templates

- Global base: `templates/base.html`
- Content templates: `templates/content/`
- Redaction templates: `templates/redaction/` — uses dark-palette CSS defined inline in `templates/redaction/base.html`
- Template tag: `content/templatetags/menu_tags.py`

### Media

Uploaded files go to `media/uploads/%Y/%m/`. `Media.url` property returns local file URL if available, falls back to original WordPress URL (`original_url` field).

### Key settings

- `LANGUAGE_CODE = 'fr-fr'`, `TIME_ZONE = 'Europe/Paris'`
- Templates lookup: `DIRS=[BASE_DIR / 'templates']` plus `APP_DIRS=True`
- Media served via Django in DEBUG mode only