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

---

## Working methodology

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.