# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
cd "/home/arnaud/PycharmProjects/site cnt"
source venv/bin/activate

python manage.py runserver        # Start dev server
python manage.py migrate          # Apply migrations
python manage.py makemigrations   # Create new migrations
python manage.py test             # Run tests (content + cms)
python manage.py test content     # Run tests for a specific app

# Après chaque migrate (surtout en prod avec utilisateurs connectés) :
python manage.py fix_cms_sessions --dry-run  # vérifier les sessions à corriger
python manage.py fix_cms_sessions            # corriger les sessions avec site_id obsolète
```

Déploiement prod : voir `!DEPLOIEMENT.md` (serveur `debian@51.91.242.64`, `/var/www/cntso/`, supervisor service `cntso`).

## Architecture overview

Django 6.0 + **Wagtail 7.4** CMS for the CNT-SO (anarcho-syndicalist union) website, migrated from a WordPress multisite. SQLite in development, Python 3.12, venv at `venv/`. `/cms/` (Wagtail admin) is the only editorial interface — the old `redaction/` app was removed and `/redac/` permanently redirects to `/cms/`.

### Multisite model

The central concept is `SectionPage` (in `cms/models.py`), a Wagtail page representing either the main confederation site (`slug='principal'`, hardcoded throughout views and context processors) or a regional/sectoral sub-site (`section_type` field; `RegionalSectionPage`/`SectoralSectionPage` are proxies). Content models reference their site either by FK to `SectionPage` (`MenuItem`, `Subscriber`, `Newsletter`, `FormulaireContact`…) or by a `section_slug` SlugField (`ArticlePage`, `ContentPage`, `CmsCategory`). Views always filter by site context.

`SectionPage` also carries per-site identity: contact email, social links, `framaform_url` (adhésion), `linkstack_url`, `agenda_url`, carousel (`CarouselArticle` inline), OVH mailing list.

### Apps

**`cms/`** — Wagtail page models and admin customization. `CmsCategory`, `HomePage`, `SectionPage`, `ArticlePage` (StreamField body), `ContentPage` (static pages), `Event` (agenda). `wagtail_hooks.py` customizes the admin (site scoping, menu structure). `site_context.py` handles the per-user "current site" scoping in the admin (session key; see `fix_cms_sessions`). `ovh_client.py` + `widgets.py` for OVH mailing-list management.

**`content/`** — Public-facing views/URLs/feeds/sitemaps (namespace `content`) plus non-page models: `MenuItem`, `Subscriber`/`Newsletter`, `ContactMessage`/`FormulaireContact`/`ChampContactCustom` (dynamic contact forms), `Comment`, `Author`. Also `wagtail_hooks.py` registering these models as snippets (SnippetViewSet groups). Legacy WordPress models (`Article`, `Page`, `Tag`, `Media`) are kept for data/import history but are no longer registered in the admin (the legacy `ContenuGroup` is unregistered).

Editorial groups (`redacteur`, `redacteur_en_chef`) are created on `post_migrate` in `content/apps.py`; a `redacteur` is scoped to a site via `Author.site` (`Author.user` OneToOneField `author_profile`).

### URL routing

```
/                     → content.views.HomeView (une de journal : carousel, manchette, réseau)
/<slug>/              → SiteHomeView + sub-site URLs (contact, agenda, rejoindre, ressources…)
/cms/                 → Wagtail admin (seule interface éditoriale)
/admin/               → Django admin
/adherer/<slug>/      → redirect vers l'app externe cnt-adhesion
/api/newsletter/sync/ → webhook cnt-adhesion (HMAC, csrf_exempt)
/sitemap.xml, /robots.txt
```

`content.urls` is included **before** `wagtail_urls`; Wagtail page serving is the final catch-all. WordPress legacy URLs handled by `WordPressRedirectView` (`/YYYY/MM/slug/`). Media served by Django before the `<slug>` catch-all.

### Context processors

`content.context_processors.menu_context` — injects `main_site`, `sites`, `regional_sites`, `sectoral_sites`, `main_categories`, `menu_structure` into all templates.

### Key integrations

- **hCaptcha** on public forms (test keys by default; mock `hcaptcha.fields.hCaptchaField.validate` in tests).
- **wagtail-cache** (`WAGTAILCACHE_*`), **wagtail-2fa** (`WAGTAIL_2FA_REQUIRED = False` for now), **wagtailseo**.
- **OVH** : newsletter sending throttled (`NEWSLETTER_SEND_DELAY`), mailing-list API via env keys (`OVH_*`). Guide: `docs/newsletter-ovh-guide.md`.
- **cnt-adhesion** (separate app at `/home/arnaud/PycharmProjects/cnt-adhesion`) : `ADHESION_WEBHOOK_SECRET`, `ADHESION_BASE_URL`.
- `local_settings.py` (gitignored) overrides credentials/DEBUG in dev; prod uses env vars. A hardening block at the end of `settings.py` refuses to start in prod with the fallback insecure `SECRET_KEY` and enables secure cookies + HSTS.

### Templates & static

- Global base: `templates/base.html`; public templates in `templates/content/` (sub-site home: `sectoral_site_home.html`, sidebar partials `_sidebar*.html`); Wagtail rendering in `templates/cms/`.
- Template tags: `content/templatetags/menu_tags.py`, `content_tags.py` (`render_content` is legacy WordPress/EditorJS rendering).
- Media uploads: `media/`; WordPress-era models keep `wp_id`/`original_url` fallbacks.

### Tests

`content/tests.py` (~4300 lines) and `cms/tests.py` (~950 lines), ~550 tests. Factories at the top of `content/tests.py`: `make_site` (SectionPage), `make_article_page`, `make_content_page`, `make_cms_category`… Gotchas: dynamic contact forms require `objet` by default (`field_objet=True`); hCaptcha must be mocked; Wagtail pages are created via `add_child` under the `home-test` HomePage.

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
