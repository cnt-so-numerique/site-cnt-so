# Mise en service 34.cnt-so.org — restes (2026-07-17)

Le domaine est en service (DNS + nginx + cert + section prod pk=1903 +
`custom_domain` posés le 2026-07-17 ; provisionnement auto OK : groupe
`redacteur_34` + collection « CNT-SO 34 (Hérault) »). La section est vierge :

- [ ] Remplir la fiche du syndicat dans /cms/ (email de contact, réseaux
      sociaux, framaform d'adhésion, linkstack, agenda, carousel, logo…)
- [ ] Créer le(s) compte(s) rédacteur(s) du 34 (groupe `redacteur_34`)
- [ ] Tester un envoi réel du formulaire de contact une fois l'email renseigné
- [ ] (Optionnel) liste OVH `ovh_mailing_list` si le 34 veut une newsletter

---

# Migration content.Site → cms.SectionPage

**Objectif** : Supprimer le doublon `content.Site` / `cms.SectionPage`. Tout ce qui pointe vers
`content.Site` doit pointer vers `cms.SectionPage`. À la fin, `content.Site` est supprimé.

**Principe** : chaque phase laisse les tests verts et l'app fonctionnelle.
Ne jamais supprimer `content.Site` avant que tous les FK soient migrés.

**Clé de correspondance** : `content.Site.slug` ↔ `cms.SectionPage.slug`
(ou `SectionPage.legacy_site_slug` pour les cas hérités de WordPress)

---

## Phase 0 — Préparer SectionPage (champs manquants)

SectionPage doit avoir tous les champs de content.Site pour être un remplacement complet.

- [ ] Ajouter `contact_email = EmailField(blank=True)` sur `SectionPage`
- [ ] Ajouter `wp_blog_id = IntegerField(null=True, blank=True)` (compat import WP)
- [ ] Ajouter `path = CharField(max_length=100, blank=True)` (compat import WP)
- [ ] Ajouter property `name` → `return self.title` (compatibilité API content.Site)
- [ ] Ajouter property `is_active` → `return self.live`
- [ ] Vérifier / adapter `get_absolute_url()` sur SectionPage
- [ ] Créer migration `cms/migrations/XXXX_sectionpage_extra_fields.py`
- [ ] Tests verts ✓

---

## Phase 1 — Migrer les utilitaires de scoping (colonne vertébrale)

### cms/site_context.py
- [ ] `from content.models import Site` → `from cms.models import SectionPage`
- [ ] `get_current_site()` : retourne `SectionPage` (pk stocké en session = SectionPage.pk)
- [ ] `get_available_sites()` : `SectionPage.objects.filter(live=True)`
- [ ] `scope_qs()` / `scope_qs_slug()` : vérifier compatibilité

### content/admin_utils.py
- [ ] `get_current_site_for_view()` : `Site.objects.get` → `SectionPage.objects.get`
- [ ] Adapter `author_profile.site` → `author_profile.section_page` (après Phase 2)

- [ ] Tests verts ✓

---

## Phase 2 — Migrer les modèles content/ (FK DB)

Pour chaque modèle : changer le FK target, migration schema + migration data (slug mapping).

### Template de migration data à réutiliser
```python
def migrate_fk(apps, schema_editor):
    from django.db.models import Q
    Model = apps.get_model('content', 'MonModele')
    SectionPage = apps.get_model('cms', 'SectionPage')
    for obj in Model.objects.select_related('site').filter(site__isnull=False):
        sp = SectionPage.objects.filter(
            Q(slug=obj.site.slug) | Q(legacy_site_slug=obj.site.slug)
        ).first()
        if sp:
            obj.section_page = sp
            obj.save(update_fields=['section_page'])
```

### Modèles à migrer (dans cet ordre)
- [ ] `FormulaireContact.site` (OneToOne → SectionPage)
- [ ] `ContactMessage.site` (FK nullable → SectionPage)
- [ ] `MenuItem.site` (FK nullable → SectionPage)
- [ ] `MenuItem.target_site` (FK nullable → SectionPage)
- [ ] `Subscriber.site` (FK CASCADE → SectionPage)
- [ ] `Newsletter.site` (FK CASCADE → SectionPage)
- [ ] `Author.site` (FK nullable → SectionPage) — renommer `section_page`
- [ ] `Category.site` (FK nullable → SectionPage)
- [ ] `Tag.site` (FK nullable → SectionPage)
- [ ] `Media.site` (FK nullable → SectionPage)
- [ ] `Article.site` (FK nullable → SectionPage) — modèle legacy
- [ ] `Page.site` (FK nullable → SectionPage) — modèle legacy

- [ ] Tests verts ✓

---

## Phase 3 — Migrer les modèles adhesion/ (FK DB)

- [ ] `FormulaireAdhesion.site` (OneToOne CASCADE → SectionPage)
- [ ] `ZoneGeographique.site` (FK CASCADE → SectionPage)
- [ ] `Adhesion.site` (FK PROTECT → SectionPage)
  - ⚠️ PROTECT : migration en deux temps — ajouter `section_page` nullable, migrer data, supprimer `site`
- [ ] Mettre à jour `adhesion/signals.py` : `Site.objects.filter(slug='principal')` → SectionPage
- [ ] Mettre à jour `adhesion/views.py` : `get_object_or_404(Site, slug=..., is_active=True)`
  → `get_object_or_404(SectionPage, slug=..., live=True)`

- [ ] Tests verts ✓

---

## Phase 4 — Migrer content/views.py

- [ ] Supprimer import `Site`
- [ ] `Site.objects.filter(slug='principal')` → `SectionPage.objects.filter(slug='principal')`
- [ ] `Site.objects.filter(is_active=True)` → `SectionPage.objects.filter(live=True)`
- [ ] `get_object_or_404(Site, slug=...)` → `get_object_or_404(SectionPage, slug=...)`
- [ ] `WordPressRedirectView` : `Site.objects.filter(path__icontains=...)` → SectionPage
- [ ] `_send_contact_email()` : `site.contact_email` → inchangé (property sur SectionPage)

- [ ] Tests verts ✓

---

## Phase 5 — Migrer content/context_processors.py

- [ ] `Site.objects.get(slug='principal')` → `SectionPage.objects.get(...)`
- [ ] `Site.objects.filter(is_active=True)` → `SectionPage.objects.filter(live=True)`
- [ ] Adapter les filtres `site_type`, `site=main_site`

- [ ] Tests verts ✓

---

## Phase 6 — Migrer feeds, sitemaps, newsletter_views

- [ ] `content/feeds.py` : `get_object_or_404(Site, slug=...)` → SectionPage
- [ ] `content/sitemaps.py` : `Site.objects.filter(is_active=True)` → SectionPage
- [ ] `content/newsletter_views.py` : vérifier usages de site

- [ ] Tests verts ✓

---

## Phase 7 — Migrer les wagtail hooks

### cms/wagtail_hooks.py
- [ ] `SyndicatManageView` : utiliser SectionPage directement (plus de jointure Site ↔ SectionPage)
- [ ] `SiteDashboardPanel` : stats via SectionPage
- [ ] Supprimer toute référence à `ContentSite`

### content/wagtail_hooks.py
- [ ] `_scope_by_site()` : vérifier compatibilité
- [ ] Supprimer `SiteViewSet` (contenu.Site n'existera plus)

- [ ] Tests verts ✓

---

## Phase 8 — Migrer les templates

> Si les properties `name`, `is_active`, `get_absolute_url()` sont bien sur SectionPage (Phase 0),
> la plupart des templates ne changent pas. Vérifier uniquement les cas spéciaux.

- [ ] `templates/content/contact.html` — `site.slug`, `site.name`
- [ ] `templates/content/page_detail.html` — `site.slug`, `site.name`, `site.get_absolute_url`
- [ ] `templates/content/site_home_page.html` — `site.name`
- [ ] `templates/content/site_agenda.html` — `site.name`, `site.slug`
- [ ] `templates/content/espace_presse.html` — `site.name`, `site.slug`
- [ ] `templates/newsletter/confirm_email.html` — `site.name`
- [ ] `templates/cms/dashboard/*.html` — `current_site.name`, etc.
- [ ] `adhesion/templates/adhesion/*.html` — `site.name`, `site.slug`

- [ ] Tests verts ✓

---

## Phase 9 — Migrer les tests

- [ ] Créer helper `make_section_page()` en remplacement de `make_site()`
  (crée HomePage si besoin, puis SectionPage dans le page tree)
- [ ] `content/tests.py` : remplacer tous `make_site()` → `make_section_page()`
- [ ] `adhesion/tests.py` : même chose
- [ ] Supprimer imports `from content.models import Site` dans les tests

- [ ] Tests verts ✓

---

## Phase 10 — Nettoyage final

```bash
# Vérification avant suppression
grep -rn "from content.models import.*\bSite\b\|content\.Site\b" --include="*.py" .
# Doit retourner zéro résultat (hors models.py lui-même et sa migration de suppression)
```

- [x] Supprimer `class Site` de `content/models.py`
- [x] Supprimer `SiteAdmin` de `content/admin.py`
- [x] Supprimer `SiteViewSet` de `content/wagtail_hooks.py`
- [x] Créer migration de suppression (`content/migrations/0020_delete_site.py`)
- [x] Supprimer `SectionPage._sync_content_site()` dans `cms/models.py`
- [x] Supprimer les commandes d'import WP cassées par la suppression de Site
  (`import_comments`, `import_featured_images`, `create_users_from_authors`) — 2026-07-12
- [x] Évaluer suppression des modèles legacy `content.Article` / `content.Page` — 2026-07-12
  **Verdict : on garde les deux.**
  - `content.Page` sert encore les vues publiques (pages statiques des sous-sites,
    `content/views.py`)
  - `content.Article` est utilisé activement par la composition de newsletters
    (`NewsletterArticle.article` FK CASCADE, `content/newsletter_views.py`) et par
    le fallback images legacy (`ArticlePage.any_image_url` via `legacy_article_id`)
  - Suppression possible seulement après : migration de `NewsletterArticle` vers
    `cms.ArticlePage` + import des images legacy dans Wagtail (cf. chantier STUCS)
- [x] Suite complète verte ✓ (562 tests, 2026-07-12)

---

## État d'avancement

- [x] Audit complet — 2026-05-29
- [x] Phase 0 — Préparer SectionPage — 2026-05-29
- [x] Phase 1 — Migrer site_context.py + admin_utils.py — 2026-05-29
- [x] Phase 2 — Migrer modèles content/ (FK DB) — 2026-05-30
- [x] Phase 3 — Migrer modèles adhesion/ (FK DB) — 2026-05-30
- [x] Phase 4 — Migrer content/views.py — 2026-05-30
- [x] Phase 5 — Migrer context_processors.py — 2026-05-30
- [x] Phase 6 — Migrer feeds, sitemaps, newsletter — 2026-05-30
- [x] Phase 7 — Migrer wagtail hooks — 2026-05-30
- [x] Phase 8 — Migrer templates — 2026-05-30
- [x] Phase 9 — Migrer tests — 2026-05-30
- [x] Phase 10 — Nettoyage final — 2026-05-30
