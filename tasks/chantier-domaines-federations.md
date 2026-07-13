# Chantier — Domaines autonomes pour les fédérations sectorielles

**Objectif** : servir les sous-sites sectoriels (STUCS, Éducation, Numérique)
sur leur propre **sous-domaine de cnt-so.org** (`stucs.cnt-so.org`,
`educ.cnt-so.org`, `numerique.cnt-so.org`), tout en gardant le site confédéral et
les sous-sites **régionaux** (13, auvergne, poitiers, rhone-alpes) sous
`cnt-so.org/<slug>/` comme aujourd'hui.

> **Variante retenue le 2026-07-13 : sous-domaines** (pas d'achat de domaine).
> Zéro coût, une seule zone DNS, un certificat par nom via certbot. Le code est
> identique quel que soit le type de domaine (le champ accepte n'importe quel hôte).

**Principe directeur** : `custom_domain` vide = comportement actuel strictement inchangé.
Tout le chantier peut être mergé et déployé sans activer un seul domaine ; l'activation
se fait ensuite domaine par domaine. Chaque phase laisse les 564 tests verts.

**Timing** : à faire AVANT la bascule DNS de cnt-so.org (pas de trafic public sur le
nouveau site → pas de SEO à casser, pas d'URLs à migrer plus tard).

---

## Phase 0 — Décisions préalables — ✅ TRANCHÉE (2026-07-13)

- [x] Les fédés sont demandeuses : STUCS, Éducation et Numérique
- [x] Sous-domaines de cnt-so.org (pas d'achat) : `stucs.cnt-so.org`,
      `numerique.cnt-so.org`
- [ ] Éducation : `educ.cnt-so.org` (recommandé — hérite du référencement de
      l'ancien site) ou `education.cnt-so.org` → à confirmer avec la fédé.
      ⚠️ educ.cnt-so.org pointe encore vers le vieux serveur WP : ne récupérer
      ce nom qu'à la bascule DNS.
- [x] E-mail : hors périmètre, les adresses restent @cnt-so.org / cnt-so.info

**Livrable** : `{ stucs → stucs.cnt-so.org, numerique → numerique.cnt-so.org,
education → educ.cnt-so.org (à confirmer) }`

---

## Phase 1 — Modèle : `SectionPage.custom_domain`

- [ ] `custom_domain = models.CharField(max_length=253, blank=True, unique=False)`
  — nu, sans schéma (`stucs-syndicat.org`), unicité vérifiée par un `clean()`
  (unique=True + blank pose problème avec les doublons '' en SQLite → valider à la main)
- [ ] Property `base_url` : `https://{custom_domain}` si défini, sinon `''`
  (URL relative = comportement actuel)
- [ ] Panel d'admin : champ visible uniquement pour les superusers (pas les rédacteurs)
- [ ] Migration cms
- [ ] Tests : modèle + validation d'unicité/format (pas de schéma, pas de slash)

---

## Phase 2 — Résolution par hôte (middleware + urlconf)

Le cœur du chantier. Deux mécanismes complémentaires :

- [ ] **Middleware `SectionDomainMiddleware`** (avant CommonMiddleware) :
  - résout `request.get_host()` → `SectionPage` avec `custom_domain` correspondant
    (lookup mis en cache — table minuscule)
  - pose `request.section_page` (None sur cnt-so.org)
  - si trouvé : `request.urlconf = 'cntso.urls_federation'`
- [ ] **`cntso/urls_federation.py`** : monte à la racine les mêmes vues que les URLs
  de sous-site actuelles (`SiteHomeView`, `SiteArticleDetailView`, contact, agenda,
  rejoindre, ressources, catégories…) mais **sans** le préfixe `<slug:site_slug>/`.
  Implémentation : wrappers de vues qui injectent `site_slug` depuis
  `request.section_page.slug` dans `kwargs` — les vues existantes ne changent pas.
- [ ] Sur un domaine fédération, la racine `/` = home du sous-site
- [ ] `/cms/` et `/admin/` ne sont PAS montés sur les domaines fédérations
  → redirect 301 vers `https://cnt-so.org/cms/` (une seule interface éditoriale)
- [ ] `/media/` : reste servi (images des articles)
- [ ] Garde-fou : un host inconnu ne matche jamais silencieusement le site principal
  (ALLOWED_HOSTS s'en charge, cf. Phase 6)
- [ ] Tests : `self.client.get('/', HTTP_HOST='stucs-syndicat.org')` → home STUCS ;
  article, contact, 404 inter-sites (un article auvergne n'est pas servable
  sur le domaine STUCS), /cms/ redirigé

---

## Phase 3 — Génération d'URLs sortantes

Tout lien *vers* une section à domaine doit être absolu ; les liens internes à la
section restent relatifs.

- [ ] `ArticlePage.get_absolute_url()` : préfixer par `section.base_url` si custom_domain
- [ ] `SectionPage.get_absolute_url()` : idem (la home devient `https://domaine/`)
- [ ] `ContentPage`, `Event`, catégories de section : idem
- [ ] Subtilité : quand on EST déjà sur le domaine (request courante), les URLs
  peuvent rester relatives — acceptable de toujours mettre l'absolu (plus simple,
  et évite les canonicals ambigus). Trancher : **absolu partout** recommandé.
- [ ] `menu_context` / `menu_structure` : les entrées « réseau » (liste des sites)
  pointent vers les domaines autonomes
- [ ] Newsletter : liens d'articles absolus avec le bon domaine (vérifier
  `newsletter_views` + templates d'e-mail, désinscription/confirmation)
- [ ] Tests : get_absolute_url avec/sans domaine, menus, e-mails

---

## Phase 4 — SEO : canonicals, redirections, sitemaps, feeds

- [ ] **301 chemin → domaine** : une fois le domaine actif,
  `cnt-so.org/stucs/...` → `https://stucs-syndicat.org/...` (redirection
  conditionnelle : seulement si `custom_domain` est renseigné)
- [ ] **Canonical** : `<link rel=canonical>` sur toutes les pages de section
  = URL sur le domaine autonome (via `base_url`)
- [ ] **Sitemap par domaine** : sur `stucs-syndicat.org/sitemap.xml`, ne lister que
  le contenu de la section ; sur `cnt-so.org/sitemap.xml`, exclure les sections
  à domaine autonome (sinon duplicate content)
- [ ] **robots.txt par domaine**
- [ ] **Feeds RSS** : `stucs-syndicat.org/feed/` = flux de la section ;
  liens absolus corrects dans les items
- [ ] **Legacy WordPress** : `WordPressRedirectView` (`/YYYY/MM/slug/`) sur cnt-so.org
  doit rediriger vers le domaine autonome quand l'article appartient à une section
  qui en a un (redirection en deux sauts acceptable : WP → chemin → domaine)
- [ ] Open Graph : `og:url` absolu avec le bon domaine
- [ ] Tests : canonicals, 301, contenu des sitemaps/feeds par host

---

## Phase 5 — Cache, formulaires, intégrations

- [ ] **wagtail-cache** : vérifier que la clé de cache inclut le host
  (sinon la home STUCS peut être servie sur cnt-so.org — à tester explicitement)
- [ ] **hCaptcha** : ajouter les nouveaux domaines dans le dashboard hCaptcha
  (sinon les formulaires contact/newsletter des fédés seront rejetés)
- [ ] **Formulaires de contact / newsletter** : vérifier les URLs de confirmation
  (e-mails de double opt-in → domaine de la section)
- [ ] **Cookies** : rien à faire (host-only par défaut) — mais vérifier que rien ne
  dépend d'une session partagée entre le site public et une section
- [ ] **BasicAuthMiddleware** (préprod) : doit couvrir aussi les nouveaux domaines

---

## Phase 6 — Configuration & infra

- [ ] `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS` : générés depuis la liste des domaines
  (settings + doc pour local_settings prod)
- [ ] **DNS** : A record de chaque domaine (+ www) → 51.91.242.64
- [ ] **nginx** : ajouter les `server_name` au vhost cntso (ou un vhost par domaine
  si config TLS distincte) ; redirection www → apex
- [ ] **certbot** : un certificat par domaine (ou SAN unique) ; renouvellement auto ;
  ces domaines-là peuvent être validés en HTTP direct (pas encore de trafic)
- [ ] `WAGTAILADMIN_BASE_URL` : reste `https://cnt-so.org` (CMS unique)
- [ ] Mettre à jour `!DEPLOIEMENT.md` (procédure d'activation d'un domaine)

---

## Phase 7 — Activation & recette (par domaine, un à la fois)

Pour chaque fédération :

- [ ] DNS + nginx + certbot en place, domaine répond en HTTPS
- [ ] Renseigner `custom_domain` sur la SectionPage → l'activation est instantanée
- [ ] Recette : home, article, catégorie, contact (envoi réel), agenda, feed,
  sitemap, 301 depuis cnt-so.org/<slug>/, /cms/ redirigé, hCaptcha OK
- [ ] Vérifier la newsletter de la section (liens dans un envoi de test)
- [ ] Rollback simple : vider `custom_domain` (le chemin redevient canonique)

---

## Hors périmètre (assumé)

- E-mail entrant/sortant sur les nouveaux domaines (MX, SPF/DKIM) — chantier séparé
- Thème/charte graphique distincte par fédération — le design actuel des sous-sites
  s'applique tel quel
- Compte OVH mailing-list par domaine — les listes restent sur cnt-so.info

## Estimation

- Phases 1–3 : le gros du travail (~4–6 jours avec tests)
- Phases 4–5 : ~2–3 jours (beaucoup de petits points à vérifier un par un)
- Phases 6–7 : ~1 jour + délais DNS/certbot
- Total : **1,5 à 2 semaines** étalées, sans bloquer la bascule DNS du site principal
  (les deux chantiers sont indépendants tant que Phase 4 « exclusion sitemap » est
  faite avant d'activer un domaine)

## Risques identifiés

1. **wagtail-cache sans clé par host** → fuite de contenu entre domaines (à tester en Phase 5, tôt)
2. Tests existants écrits avec `testserver` : l'ajout du middleware ne doit rien changer
   pour eux (custom_domain vide partout par défaut) — c'est le filet de sécurité du chantier
3. Duplicate content si un domaine est activé avant l'exclusion sitemap/canonicals
4. Décision politique qui traîne : ne pas commencer la Phase 1 avant la Phase 0 validée
