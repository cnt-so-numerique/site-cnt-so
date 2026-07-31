# Audit du site — 31 juillet 2026

Audit complet des parties publiques et de la configuration, mené sur la base de dev
(branche `refonte-affiche`) **et** vérifié en production (`newsite.cnt-so.org` +
les 7 domaines de fédérations).

## Couverture

| Domaine | Méthode | Résultat |
|---|---|---|
| Routes publiques (dev) | 232 URLs réelles issues de la base, client de test Django | **0 erreur 5xx** |
| Routes publiques (prod) | 69 URLs sur les 8 hôtes | 60×200, 4×3xx, **5×404** (analysés ci-dessous) |
| Suite de tests | `manage.py test` | **695 tests OK** |
| Médias | vérification disque des images référencées | **930/930 présentes**, 0 lien externe restant |
| Sécurité prod | en-têtes HTTP réels | HSTS 30 j, cookies `Secure`, `nosniff`, `X-Frame-Options` ✔ |
| Données | sections, articles, catégories, comptes, formulaires | voir constats |

---

## Constats

### A. ✅ Bug corrigé — sous-site Numérique : 5 pages en 404 en production

`https://numerique.cnt-so.org/` → **404** sur `/agenda/`, `/rejoindre/`,
`/ressources/`, `/plan-du-site/`, `/espace-presse/`.
La home, `/contact/` et `/feed/` répondent 200. Les 6 autres domaines de
fédérations ne sont pas touchés.

**Cause** — `SectionDomainMiddleware` (`cntso/middleware.py:83`) préfixe le chemin
avec `section.legacy_site_slug or section.slug`, alors que **12 vues** résolvent la
section par `slug=` uniquement :

```
content/views.py:114  SiteAgendaView          ← 404
content/views.py:404  SiteEspacePresse        ← 404
content/views.py:672  PlanDuSiteView          ← 404
content/views.py:850  SiteRejoindreView       ← 404
content/views.py:882  SiteRessourcesView      ← 404
content/views.py:150,165,247,253,294,344,730  (mêmes conditions)
```

Seules deux choses échappent au bug :
- `SiteContactView` (`views.py:645`) qui fait `Q(slug=…) | Q(legacy_site_slug=…)` ;
- la home, sauvée par le repli Wagtail `_is_section_wagtail_page()` du middleware.

**Confirmé en base de production** (lecture seule, 31/07) :

| section | slug | legacy_site_slug | domaine |
|---|---|---|---|
| numerique | `numerique` | **`stnum`** | numerique.cnt-so.org |
| education | `education` | **`fter`** | *(pas encore de domaine)* |

Toutes les autres sections ont `legacy == slug` et ne sont pas affectées.

⚠️ **Éducation porte la même bombe à retardement** : son sous-site cassera de la
même façon le jour où `educ.cnt-so.org` sera activé (prévu à la bascule DNS).
Le correctif ci-dessous le désamorce aussi.

**Correctif appliqué** : helper partagé `get_section_or_404()`
(`content/views.py`), qui résout par `slug` **ou** `legacy_site_slug` ; les 12
appels ont été alignés dessus. Les deux résolutions littérales sur `'principal'`
sont laissées telles quelles.

**Test de non-régression** : `LegacySiteSlugRoutingTest` (`content/tests.py`) —
reproduit le cas Numérique (slug `numerique` / legacy `stnum`). Vérifié : sans le
correctif, les **5 mêmes chemins** qu'en production échouent (le contact passe,
comme en prod) ; avec le correctif, tout répond 200. Suite complète : **699 tests OK**.

### A-bis. ✅ Deux bugs révélés par la recette du correctif A

Une fois les 5 pages de Numérique redevenues accessibles, elles ont exposé deux
défauts jusque-là invisibles (les pages étaient en 404) :

1. **Contenus filtrés sur le slug brut de l'URL.** `SitePageDetailView`,
   `PlanDuSiteView`, `SiteRejoindreView` et `SiteRessourcesView` filtraient
   articles et catégories avec `section_slug=site_slug` (le slug de l'URL, donc
   `stnum`) au lieu du slug résolu (`numerique`) — `SiteHomeView`, elle, utilisait
   déjà le bon. Résultat : les pages répondaient 200 mais restaient **vides**.
   Corrigé : filtrage sur la section résolue.

2. **« STUCS » codé en dur dans le template générique des Ressources.**
   `templates/content/site_ressources.html` affichait « Ressources — STUCS CNT-SO »
   en titre, « STUCS » en vignette de repli et « choisissez la section STUCS » dans
   le message de page vide — **sur les 7 sous-sites** (vérifié en prod : Marseille,
   Poitiers, Auvergne, Rhône-Alpes, 34, Numérique affichaient tous « STUCS »).
   Corrigé : `{{ site.name }}`. Le commentaire CSS « STUCS sub-pages » de
   `site_subpage_base.html`, servi au navigateur, a été neutralisé aussi.

Couverts par les tests `test_le_contenu_du_syndicat_est_bien_affiche_via_le_slug_legacy`
et `test_le_nom_du_syndicat_remplace_stucs_dans_les_ressources`. Suite : **701 tests OK**.

### B. 🟠 Formulaires de contact sans destinataire propre

**Vérifié en production** : sur les 8 formulaires actifs, **4 n'ont aucun
destinataire propre** et retombent sur `contact@cnt-so.org` :

| formulaire | destinataire réel |
|---|---|
| principal | `contact@cnt-so.org` ✔ |
| stucs | `spectacle@cnt-so.org` ✔ |
| education | `fede.education.public@cnt-so.org` ✔ |
| numerique | `numerique@cnt-so.org` ✔ |
| **13** | ⚠️ repli confédéral |
| **poitiers** | ⚠️ repli confédéral |
| **auvergne** | ⚠️ repli confédéral |
| **rhone-alpes** | ⚠️ repli confédéral |

Conséquence : un message adressé à Marseille, Poitiers, Auvergne ou Rhône-Alpes
arrive dans la boîte confédérale. **Rien n'est perdu** (les messages sont stockés
et consultables dans `/cms/contact/`), mais le routage ne fait pas son office.

*(La base de dev donnait un tableau bien plus alarmant — 9 sur 10 — car elle est
désynchronisée : voir constat G.)*

### C. 🟠 Fiches d'identité des syndicats incomplètes

En production, 8 sections sur 12 n'ont pas d'email de contact : `13`, `34`,
`auvergne`, `poitiers`, `rhone-alpes` et les 3 sections Rhône-Alpes non publiées.
C'est la cause directe du constat B. (La fiche de `34`, tout juste créée, est
entièrement vide — déjà noté dans `tasks/todo.md`.)

### D. 🟠 45 % des articles n'ont pas d'image

763 articles publiés sur 1693 sont sans visuel. Impact direct sur la refonte en
cours (une, manchette à vignettes) : les cadres tombent sur un fond vide.
À arbitrer : visuel de repli, ou mise en page dégradée sans image.

### E. 🟡 Métadonnées éditoriales

- 1684 articles sur 1693 sans extrait saisi → la meta description repose sur le
  repli « premier bloc de texte » (fonctionnel, mais non maîtrisé pour le référencement).
- 15 articles publiés sans aucune catégorie.
- 71 catégories ne contiennent aucun article publié.

### F. 🟡 hCaptcha inopérant en production

La prod tourne avec les clés de test : les formulaires publics (contact, newsletter)
ne sont pas réellement protégés du spam. *(Déjà connu, non traité.)*

### G. 🟡 Base de dev désynchronisée de la production

Écarts constatés :
- 16 sections en dev contre 12 en prod (dev a `staa`, `test`, `debug-a`, `debug-b`) ;
- `legacy_site_slug` égal au slug partout en dev, alors que Numérique et Éducation
  divergent en prod — **c'est ce qui a rendu le bug A invisible en local** ;
- destinataires de contact : 4 renseignés en prod, 1 seul en dev ;
- menus « Flux RSS » pointant vers `/rss/` (404) présents en dev, absents en prod ;
- 2021 URLs au sitemap de dev contre 838 en prod (écart en partie normal : les
  sections à domaine ont leur sitemap séparé).

**Conséquence méthodologique** : ne jamais conclure sur la production à partir de la
base locale — vérifier par HTTP ou en base de prod.

### H. 🟢 Détail — liens internes en dur provoquant une redirection

`templates/content/home.html` pointe deux fois vers `/page/syndicats/`, qui répond
301 vers `/syndicats/`. Introduit lors de la refonte du 19/07. Redirection inutile.

---

## Ce qui est sain

- Aucune erreur serveur sur l'ensemble des routes testées, en dev comme en prod.
- Sécurité de production correcte : HSTS, cookies sécurisés, en-têtes de protection.
  Les alertes de `check --deploy` proviennent uniquement de la config de dev.
- Intégrité des médias parfaite : plus aucune dépendance au vieux WordPress.
- Les 7 domaines de fédérations répondent correctement (hors bug A).
- Suite de 695 tests au vert.
