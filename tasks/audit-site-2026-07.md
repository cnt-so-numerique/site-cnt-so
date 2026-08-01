# Audit du site — 31 juillet 2026

Audit complet des parties publiques et de la configuration, mené sur la base de dev
(branche `refonte-affiche`) **et** vérifié en production (`newsite.cnt-so.org` +
les 7 domaines de fédérations).

## Couverture

| Domaine | Méthode | Résultat |
|---|---|---|
| Routes publiques (dev) | 232 URLs réelles issues de la base, client de test Django | **0 erreur 5xx** |
| Routes publiques (prod) | 69 URLs sur les 8 hôtes | avant : 60×200 et **5×404** ; après correctifs : **63×200, 2×404** |
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

3. **Flux RSS vides.** `SiteArticlesFeed.items()` filtrait sur
   `legacy_site_slug or slug` — donc sur `stnum` / `fter` — alors que les articles
   portent le slug Wagtail. **Le flux de Numérique et celui d'Éducation étaient
   vides en production** (0 item, alors que leurs homes listent respectivement 4 et
   15 articles). Ce bug-là ne dépendait pas du domaine : il était actif depuis le
   départ. Corrigé en acceptant les deux slugs, comme le font déjà les sitemaps
   (`content/sitemaps.py`).

Couverts par trois tests de non-régression dans `LegacySiteSlugRoutingTest`,
chacun vérifié par retrait du correctif. Suite : **702 tests OK**.

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

### D. ✅ Images : 93,8 % de couverture après récupération (et non 45 % de manques)

⚠️ **Constat initial erroné, corrigé le 31/07.** La base de dev donnait « 763
articles sur 1693 sans image », soit 45 %. **C'est un artefact de la base locale** :
la prod a reçu un import de médias (16/07) que dev n'a jamais eu.

Chiffres réels en production :

| | articles |
|---|---|
| Publiés | 1782 |
| **Avec vignette** | **1631 (91,5 %)** |
| Sans vignette | 151 (8,5 %) |
| … dont une image existe dans le corps | 43 |
| … dont aucune image du tout | 108 |

Et le manque est **concentré sur Poitiers** : 130 des 151 articles. Les autres
syndicats ont entre 1 et 5 articles sans visuel.

**Conséquence pour la refonte** : le risque de « cadres vides » dans la une et la
manchette est marginal, pas structurel. Une image de repli suffirait ; il n'y a pas
de chantier éditorial à mener.

**Vérifié en ligne, contre le vieux WordPress** (`cnt-so.org/poitiers/`, encore
debout) : rien n'a été perdu à l'import. Les articles concernés affichent bien
leurs visuels sur le nouveau site, servis depuis `/media/` — il leur manque
seulement le statut d'image « à la une », d'où des cartes vides dans les listes.
Contrôle par sondage : « Ukraine, presque 3 ans de guerre » a ses 4 visuels des
deux côtés ; « Un LRA à Rouillé » n'en a aucun, ni sur l'ancien site ni sur le
nouveau — ces articles n'ont tout simplement jamais eu d'image.

⚠️ *Attention au comptage :* une page d'article contient 4 images de barre latérale
(campagnes, « ce que vous avez loupé »). Il faut les retrancher avant de conclure.

**✅ Récupération faite le 31/07** — commande `promote_body_images`
(`cms/management/commands/`) : quand une page n'a pas de vignette mais porte une
image dans son corps, cette image est promue en image « à la une » (rattachée à
l'Image Wagtail existante, ou créée depuis le fichier déjà sur disque, dans la
collection du syndicat).

Résultat en production :

| | avant | après |
|---|---|---|
| Articles avec vignette | 1631 (91,5 %) | **1671 (93,8 %)** |
| Sans vignette | 151 | 111 |
| Cartes illustrées sur `86.cnt-so.org/ressources/` | 67/197 | **104/197** |

53 vignettes posées au total (40 articles + 13 pages de contenu). Les 111 restants
n'ont aucune image nulle part — vérifié contre le vieux WordPress, ils n'en ont
jamais eu.

⚠️ **Garde-fous de la commande** : les pages ayant un brouillon en attente sont
ignorées (les republier mettrait en ligne des modifications non validées) ; aucune
image n'est dupliquée si le fichier est déjà connu de Wagtail ; `--dry-run`,
`--section` et `--limit` disponibles. Contrôle après passage : 18 brouillons non
publiés avant **et** après — rien n'a été publié par inadvertance.

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
- **images** : 91,5 % des articles ont une vignette en prod, contre 55 % en dev —
  la prod a reçu l'import de médias du 16/07, pas la base locale (voir constat D) ;
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

### Les deux 404 restants sont légitimes

- `newsite.cnt-so.org/agenda/` : il n'existe pas d'agenda confédéral (l'agenda est
  une page de sous-site). Aucun lien du site n'y mène — URL inventée par le balayage.
- `newsite.cnt-so.org/staa/` : la section STAA n'existe pas en production
  (elle n'est présente qu'en base de dev — voir constat G).

---

## Ce qui est sain

- Aucune erreur serveur sur l'ensemble des routes testées, en dev comme en prod.
- Sécurité de production correcte : HSTS, cookies sécurisés, en-têtes de protection.
  Les alertes de `check --deploy` proviennent uniquement de la config de dev.
- Intégrité des médias parfaite : plus aucune dépendance au vieux WordPress.
- Les 7 domaines de fédérations répondent correctement (hors bug A).
- Suite de 695 tests au vert.

---

# Seconde passe (31/07/2026) — au-delà du site public

La première passe ne couvrait que le site public en lecture. Cette seconde passe
a porté sur les logs, les sauvegardes, les mails, l'espace de rédaction et la
performance. **Cinq bugs de plus**, tous déployés.

## Logs de production — un incident, pas de dérive

48 Mo de journaux depuis le 08/06. L'essentiel est du bruit de scanners
(`/.env`, `/*.php`, `/.git/config` — ~1500 tentatives) et 12 échecs de
négociation TLS côté nginx, sans conséquence.

**Un seul incident réel** : le 26/07 de 11:50:46 à 11:52:14 (1 min 28), les
workers gunicorn refusaient de démarrer — `SyntaxError` dans
`cntso/local_settings.py` ligne 53, corrigée à la main. Le site était en 502.
⚠️ Ce fichier est édité directement sur le serveur et n'est pas versionné : une
faute de frappe coupe le site. Il est en revanche sauvegardé (chiffré) sur le NAS.

## Sauvegardes — le circuit fonctionne

Vérifié de bout en bout : `pg-backup.timer` tourne quotidiennement à 01h30
(dernier dump `cntso` : 10,5 Mo), le miroir média local fait 7,5 Go — identique à
la production — et le NAS vient tout récupérer à 02h30.

## Mails — configuration saine

SMTP OVH (`ssl0.ovh.net:587`, TLS, identifiants présents), **connexion et
authentification testées avec succès**, zéro erreur d'envoi dans les logs. Aucun
message n'a été envoyé depuis la prod pour ne pas polluer les boîtes des syndicats.

## Webhook d'adhésion — protégé

`POST /api/newsletter/sync/` renvoie **403** sans signature comme avec une
signature invalide.

## Espace de rédaction — 3 bugs (commits e6c5b1b, 8bed149)

Parcours complet d'un rédacteur rattaché à un syndicat au slug hérité :
**18 contrôles sur 19** passaient déjà (navigation, cloisonnement des listes,
accès refusé aux comptes/groupes/admin Django).

1. **Édition hors périmètre** : le formulaire d'édition d'un article d'un *autre*
   syndicat s'ouvrait par URL directe. L'enregistrement était bien bloqué (pas de
   fuite en écriture, vérifié), mais le contenu — brouillons compris — était
   lisible. Désormais 404 ; le chef garde l'accès à tout.
2. **Espace de rédaction vide** : `scope_qs_slug` filtrait sur le seul slug
   hérité → les rédacteurs de Numérique et Éducation n'auraient vu **aucun** de
   leurs contenus. Idem pour la liste des catégories du formulaire d'article.
3. **Contenus nés invisibles** : `ArticlePage.save()`, `ContentPage.save()` et
   `form_valid()` estampillaient `section_slug` avec le slug hérité → tout
   contenu créé sous ces syndicats aurait été invisible côté public. Vérifié en
   prod : 0 contenu portait `stnum`/`fter`, le piège n'avait pas encore servi.

*(Le provisionnement nommait aussi les groupes d'après le slug hérité, ce qui
aurait créé des doublons de `redacteur_numerique`.)*

## Performance — un N+1 sur toutes les pages (commit 910a845)

`base.html` descend à trois niveaux de menu (item → enfant → petit-enfant) alors
que `get_menu` n'en préchargeait qu'un : chaque enfant déclenchait une requête,
plus une par catégorie liée pour bâtir son URL. Le menu étant reconstruit sur
**chaque page**, le surcoût était général.

| page | avant | après |
|---|---|---|
| Home d'un sous-site | 62 requêtes | **18** |
| Page Ressources | 60 | **15** |
| Agenda | 55 | **10** |
| Accueil confédéral | 52 | **27** |

Temps de réponse en production après correction : 0,4 s à 1,0 s.

## Reste non couvert

- **Accessibilité** : rien n'a été vérifié (contrastes, navigation clavier,
  lecteurs d'écran, attributs ARIA).
- **Rendu visuel et responsive** : non revu dans cette passe.
- **Parcours d'écriture réels** : créer puis publier un article, téléverser un
  média, envoyer une vraie newsletter — testés en droits, pas en usage.
- **Montée en charge** : aucun test de charge.

---

## Accessibilité — premier audit (01/08/2026)

Jamais auditée jusqu'ici. Analyse du HTML réellement servi en production sur
6 pages (accueil, contact, plan du site, home et ressources d'un sous-site, agenda).

### Corrigé et déployé (commits 05935a9, 6e36894)

1. **Aucun lien d'évitement** — un utilisateur au clavier devait traverser toute
   la navigation avant d'atteindre le contenu. Ajout d'un lien « Aller au contenu
   principal », invisible à la souris, révélé au focus.
2. **Champs sans étiquette** — la recherche et les trois champs e-mail de
   newsletter n'avaient qu'un `placeholder`, inaudible pour un lecteur d'écran.
   `aria-label` ajouté.
3. **Repère `<main>` absent** des gabarits qui redéfinissent `full_content`
   (accueil, qui-sommes-nous, s'organiser). Ajouté, et sert d'ancre au lien
   d'évitement.
4. **Sauts de niveau de titre** — h1→h3 (blocs de sidebar passés en h2) puis
   h2→h4 (titres du pied de page passés en h3). Styles pilotés par classes :
   apparence inchangée.

Après déploiement, **tous les contrôles automatisables passent** sur les 6 pages :
`lang`, `<h1>` unique, hiérarchie continue, images avec `alt`, champs étiquetés,
boutons et liens avec nom accessible, repères `<main>`/`<nav>`/`<footer>`.

⚠️ **Ma première passe sur-signalait** : le détecteur capturait le contenu des
balises sans leurs attributs, comptant tous les champs, boutons et liens comme
non étiquetés. Les liens sociaux et boutons à icône avaient déjà leur
`aria-label`. Version corrigée du script en pièce jointe de session.

### Contraste — corrigé

| paire | ratio | texte courant (≥4,5) | texte large (≥3) |
|---|---|---|---|
| **rouge `#EC1C24` sur blanc** | **4,41** | ⚠️ sous le seuil | ✔ |
| blanc sur rouge | 4,41 | ⚠️ sous le seuil | ✔ |
| gris `#5C5C5C` sur blanc | 6,69 | ✔ | ✔ |
| texte `#333` sur blanc | 12,63 | ✔ | ✔ |
| blanc sur fond sombre | 17,40 | ✔ | ✔ |
| gris clair sur pied de page sombre | 9,98 | ✔ | ✔ |

**✅ Arbitré et corrigé le 01/08** — passage à **`#E81C24`** (4,54:1), écart
invisible à l'œil. Deux autres rouges sous le seuil ont été alignés au passage :

| teinte | ratio | où | devenu |
|---|---|---|---|
| `#EC1C24` | 4,41 | `--primary-color`, tout le site | `#E81C24` |
| `#EC1A2E` | 4,42 | liens du gabarit de home héritée | `#E81C24` |
| `#E63946` | 4,17 | liens des écrans `/cms/` (contact, listes mails, menus) | `#E81C24` |

Le back-office bénéficie donc de la même conformité que le site public, et la
teinte est unifiée partout. Verrouillé par `ContrasteCouleursTest` : le calcul
est validé sur des repères connus (noir = 21:1, blanc = 1:1), `--primary-color`
doit tenir 4,5:1, et aucune ancienne teinte ne peut réapparaître dans les gabarits.

## Passe 6 — cloisonnement du back-office (01/08)

La fiche `tasks/chantier-autonomie-syndicats.md` annonçait les lots 2 à 6 comme
restant à faire : **elle était périmée**. Publication directe, permissions
modèle, ouverture de la newsletter et sécurisation des menus étaient livrées.
Ce qui manquait, c'était l'inverse : les droits avaient été ouverts aux
rédacteurs sans que les barrières par objet suivent.

### La faille principale : la suppression en masse

Le rôle syndicat possède `content.delete_subscriber` au niveau modèle. Or
`BulkAction` résout `?id=all` en `model.objects.all()` et `check_perm` ne teste
que la permission de modèle — Wagtail l'assume dans son propre code : *« snippets
permissions are not enforced per object »*. **Un seul POST sur
`/cms/bulk/content/subscriber/delete/?id=all` effaçait les abonnés newsletter de
tous les syndicats.** Exploitable en l'état par n'importe quel rédacteur.

### La faille de fond : un seul écran protégé sur une centaine

Wagtail ne passe le queryset d'un `SnippetViewSet` qu'à la vue index. Édition,
suppression, copie, historique, dépublication, révisions, prévisualisation :
tous relisent par clé primaire sans filtre, et plusieurs appellent
`get_object_or_404(self.model, pk=…)` en dur. Sur douze snippets enregistrés,
seul `ArticlePage` était couvert, par un garde ad hoc posé lors de la passe 2 —
et uniquement sur son écran d'édition.

### Le correctif

`cms/cloisonnement.py`. Chaque viewset déclare son périmètre une fois, et cette
déclaration sert la liste comme les écrans par pk. Le point d'accroche est
`construct_view`, traversé par les 24 URLs d'un viewset sans exception :
énumérer les attributs `*_view_class` aurait été un inventaire à maintenir,
donc à oublier, alors que Wagtail en ajoute à chaque version. Un viewset sans
déclaration lève `ImproperlyConfigured` à l'enregistrement plutôt que de
s'ouvrir en silence.

**Contre-épreuve, la vérification qui compte** : `cms/tests_cloisonnement.py`
rejoué sur le code d'avant donne **114 échecs et 1 erreur**, contre 7 tests
verts après. Un test de sécurité qu'on n'a jamais vu échouer ne prouve rien.
Détail parlant : `edit` d'ArticlePage ne figure pas parmi ces 114 — l'ancien
garde couvrait exactement un écran.

### Aussi corrigé

Trois gardes filtraient « si un syndicat est résolu » et laissaient donc passer
quand il ne l'était pas. `_enforce_menuitem_site` s'appliquait à l'édition et
réattribuait au rédacteur l'entrée de menu d'un autre syndicat. Les raccourcis
« Menus » et « Newsletter » restaient réservés aux chefs alors que les vues leur
étaient ouvertes. Enfin, le reliquat d'Editor.js a été retiré : deux endpoints
d'upload publics sans contrôle de rôle, leurs routes, le widget, le JS/CSS et
cinq viewsets non enregistrés — 35 tests disparaissent avec.

**Non retenu** : accorder `delete_menuitem` aux rédacteurs. Deux tests encodent
la décision inverse, cohérente avec l'ensemble (ni articles, ni pages, ni
catégories, ni images ne sont supprimables par un rédacteur). C'est un choix de
produit, à trancher par Arnaud, pas à retourner en passant.

### Reste de ce chantier

Verrouillage en écriture du champ syndicat dans les formulaires (créer un
événement dans l'agenda d'un voisin reste possible), cloisonnement des
sélecteurs de snippets — en veillant à **ne pas** cloisonner celui de
`SectionPage`, dont `MenuItem.target_site` a légitimement besoin —, retrait du
motif `chef_` devenu inutile, et migration désactivant la ligne
`wagtailcore_workflow` « Moderators approval » restée active.

---

### Reste non couvert

Les contrôles automatisables ne remplacent pas un test réel : lecteur d'écran
(NVDA/VoiceOver).

---

## Passe 4 — navigation clavier, rendu responsive, parcours newsletter (01/08)

Menée au navigateur (Chrome piloté) sur le rendu réel, plus un balayage de
structure sur 55 pages. **7 défauts trouvés, tous corrigés.**

### Trois pièges de mesure, à retenir

1. **`:focus-visible` ne se déclenche pas sur un focus programmatique.** Mon
   premier script appelait `el.focus()` puis lisait les styles : le navigateur
   n'était pas en « modalité clavier » et ne dessinait aucun anneau. Résultat
   absurde : *69 éléments sur 69 sans indicateur*. Il faut d'abord provoquer une
   vraie frappe au clavier dans la page.
2. **Une transition CSS fausse la lecture immédiate.** `getComputedStyle` juste
   après `.focus()` renvoie l'opacité de *départ* de l'animation, soit 0. Sans
   attendre la fin de la transition, tout paraît invisible.

3. **Un navigateur dont la fenêtre n'est pas active ne dispatche aucun événement
   de focus** (`document.hasFocus()` faux). `el.focus()` déplace bien
   `document.activeElement`, mais ni `focusin` ni `focusout` ne partent — j'ai
   d'abord conclu à tort que la suspension du carrousel au clavier ne marchait
   pas. Émettre l'événement à la main lève le doute.

Ces trois pièges s'ajoutent à celui de la passe 3 (`re.findall` avec groupe de
capture qui ne voyait que le contenu des balises, jamais les attributs).

### Défauts corrigés

| # | défaut | portée |
|---|---|---|
| 1 | `.hp-mcard-body` en `opacity: 0`, révélé au seul survol — **le cartouche porte le lien du titre**, donc on tabulait sur 5 liens invisibles | accueil |
| 2 | Diapositives inactives du carrousel : `pointer-events: none` ne bloque que la souris, **pas le clavier** — 8 liens fantômes de plus | accueil |
| 3 | Deux formulaires newsletter faisaient `outline: none` **sans rien mettre à la place** | accueil + tous les sous-sites |
| 4 | Champs de contact : focus signalé par une bordure 1 px et une ombre à 10 % d'opacité, dans une teinte bordeaux périmée | contact + sous-pages |
| 5 | `site_home_page.html` : page HTML autonome, **titre et colophon codés en dur au nom du syndicat du numérique**, sans menu ni pied de page ni `h1`, Tailwind chargé depuis un CDN externe | tout syndicat gardant une page « home » WordPress |
| 6 | `h1 → h3` sur **toutes** les pages d'article (« Partager cet article », « Articles similaires ») | toutes les pages d'article |
| 7 | **Le carrousel défile seul toutes les 5 s sans aucun moyen de le mettre en pause** — WCAG 2.2.2, **niveau A**. Il ignorait aussi `prefers-reduced-motion` et ne s'arrêtait ni au survol ni au focus clavier | accueil |

Le défaut 7 est le plus grave sur l'échelle WCAG : c'est le seul de **niveau A**,
le socle. Le défaut 1 est le plus insidieux : mon propre contrôle l'avait manqué
parce qu'il lisait les styles calculés de l'élément sans remonter l'opacité des
ancêtres.

Corrigés par `:focus-within` (1), `visibility: hidden` (2), un anneau interne noir
(3), un anneau rouge de 2 px (4), un gabarit qui étend `base.html` (5), un décalage
des niveaux de titres (6), et un bouton pause + suspension au survol et au focus +
respect de `prefers-reduced-motion` (7). Un filet de sécurité `:focus-visible`
global a été ajouté à `base.html` pour tout élément futur.

Comportement du carrousel vérifié au navigateur : il défile seul, s'arrête au clic
sur pause (l'étiquette devient « Reprendre le défilement »), repart au clic
suivant, et se suspend dès qu'un `focusin` atteint la piste.

Le défaut 5 est le jumeau du « STUCS » codé en dur corrigé en passe 1, mais plus
grave : c'était la dernière page publique encore rendue par du HTML hérité de
WordPress. En dev seul Numérique est concerné — **à confirmer en production.**

### Vérifié sain

- **Aucun défilement horizontal** à 320 px de large (équivalent zoom 400 %,
  WCAG 1.4.10) : le seul élément hors cadre est le lien d'évitement, volontaire.
- **Aucun `tabindex` positif** — l'ordre de tabulation suit le DOM.
- Le lien d'évitement est bien le premier élément focusable.
- Après correction : **0 lien focusable invisible, 0 élément sans anneau de focus.**
- Balayage de structure sur 55 pages : **51 sans aucun manquement** (`main`
  unique, `h1` unique, `lang`, `title`, `alt`, étiquettes de champs, intitulés de
  liens explicites). Les 2 restants sont des sauts de niveau **dans le contenu
  rédigé** (un `h3` puis un `h5` en tête de corps d'article), pas dans le code.
- Rendu mobile 390 px vérifié : titres longs bornés à 5 lignes et voile assombri
  sur toute la hauteur des cartes, faute de quoi les premières lignes se posaient
  sur l'image nue.

### Liens internes sur les domaines autonomes

Relevé pendant la recette : sur `86.cnt-so.org`, la page Ressources contenait
**301 liens en `/poitiers/article/…`** plus une vingtaine d'autres liens
préfixés, chacun provoquant une redirection 301 vers l'URL canonique. Même
comportement sur `13.cnt-so.org`. Ça fonctionnait, mais au prix d'un
aller-retour réseau par clic.

Cause : `{% url 'content:site_…' site.slug %}` produit toujours la forme
préfixée, que `SectionDomainMiddleware` redirige ensuite. Deux méthodes de
modèle faisaient de même — dont `MenuItem.get_url()` pour Contact et Agenda,
donc **sur toutes les pages du site**.

Corrigé par un tag `{% section_url %}` (content_tags.py) qui rend directement
l'URL finale : chemin relatif inchangé sans domaine autonome, URL absolue sans
préfixe sinon. 14 occurrences remplacées dans 8 gabarits, plus
`SectionPage.get_rejoindre_url()` et `MenuItem.get_url()`. Les liens d'articles
passent par `get_absolute_url()`, déjà conscient du domaine.

Le lien `/rejoindre/` avait échappé à mon inventaire — il vient d'une méthode de
modèle, pas d'un `{% url %}` : c'est le test de balayage qui l'a trouvé.

**Puis la recette de production en a révélé une troisième source** : sur STUCS,
10 liens de menu restaient préfixés. Ce n'était pas du code mais des **données** —
des entrées de menu `link_type='url'` où un rédacteur avait tapé
`/stucs/ressources/?cat=communiques` à la main. `MenuItem.get_url()` normalise
désormais ces saisies quand la section a un domaine, en gardant la chaîne de
requête ; les URL externes et celles visant une autre section sont laissées
intactes.

### Parcours newsletter

**Aucune newsletter réelle n'a été envoyée** — c'est une action externe
irréversible. Le parcours complet a été exercé en base de test :
inscription publique → e-mail de confirmation → **le lien reçu active bien le
compte** → composition et envoi depuis `/cms/` → **l'abonnée reçoit un courrier
complet (texte + HTML)** → **le lien de désabonnement du courrier fonctionne** →
la newsletter est marquée envoyée et ne peut pas repartir. Un désabonné ne reçoit
plus rien. Chaque étape était déjà testée isolément ; rien ne vérifiait que la
chaîne tient.

### Tests ajoutés

`NavigationClavierTest` (6), `HierarchieDesTitresTest` (2),
`AccueilHeriteDeWordPressTest` (5), `ParcoursNewsletterCompletTest` (2),
`SectionUrlTagTest` (11). **730 → 756 tests.**
