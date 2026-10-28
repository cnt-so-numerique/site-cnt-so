# À faire — demandé le 27/10/2026 : retirer wagtail-seo et wagtail-2fa

Constat : deux extensions à l'arrêt, qui bloquent seules Wagtail 8. Mesuré en
prod le 27/10 : 0 appareil TOTP confirmé, 0 page avec `canonical_url` ou
`og_image` (ArticlePage et SectionPage). Les gabarits n'utilisent aucune des deux :
les balises de partage sont écrites à la main (base.html, article_detail.html).
Aucune de nos migrations ne les importe.

## 1. wagtail-seo — FAIT et DÉPLOYÉ le 27/10 (c44b8c5)
- [x] `SeoMixin` retiré de `SectionPage` et `ArticlePage` ; `promote_panels`
      d'ArticlePage = `Page.promote_panels` + l'existant (les champs slug/seo_title/
      search_description y apparaissaient en double)
- [x] Migration `cms.0048_retrait_wagtailseo` (canonical_url, og_image)
- [x] Aperçus : 200 (article et site) ; 302 anciennes révisions contenant
      `og_image` se rechargent sans erreur
- [x] `migrate wagtailseo zero` en dev (table SeoSettings vide), app retirée,
      paquet désinstallé du venv, requirements.txt
- [x] `ArticlePageSeoTest` supprimé : il ne testait que la présence du paquet ;
      les balises réellement servies sont déjà couvertes (content/tests.py ~10353,
      cms/tests.py ~2079). Suite complète : 1 638 tests OK
- [x] Prod : SeoSettings = 1 ligne aux valeurs par défaut (rien de renseigné),
      `migrate wagtailseo zero` avec l'ancien code, déploiement (code 0),
      paquet désinstallé ; article et /cms/login/ en 200, og:image présent

Constat hors lot : `seo_title` et `search_description` ne sont lus par AUCUN
gabarit (le <title> et la meta description viennent du titre et de l'extrait),
et aucun écran d'édition ne les montre (0 page remplie). **Décision d'Arnaud,
28/10/2026 : ne rien faire** — le titre et l'extrait suffisent.

## 2. wagtail-2fa → double authentification maison sur django-otp
Décidé le 27/10 : **obligatoire pour les superutilisateurs, facultative pour
les rédacteurs** ; « obligatoire pour tous » = un réglage, plus tard.
Comptes partagés dans les syndicats : un appareil **par personne** sur le même
compte (nommé, révocable seul), pas un QR code commun.

Constats (27/10) : wagtail-2fa = ~600 lignes de tuyauterie sur django-otp
(maintenu, limite déjà les essais) ; 0 appareil en prod ; 4 superutilisateurs
et 15 comptes actifs en dev. Deux trous à ne pas reproduire :
- `/admin/` (admin Django) n'est pas couvert : un superutilisateur y entre au
  seul mot de passe ;
- une session « mot de passe OK, code pas encore donné » garde ses droits sur le
  site public (sites en test réservés aux rédacteurs, aperçus).

### Règle centrale (middleware `cms.double_auth.DoubleAuthMiddleware`)
Une session **doit être vérifiée** si le compte a au moins un appareil
confirmé, ou s'il est superutilisateur (réglage `DOUBLE_AUTH_OBLIGATOIRE`,
valeurs `'superutilisateurs'` | `'tous'`). Tant qu'elle ne l'est pas :
- sur `/cms/` et `/admin/` → redirection vers la page du code (ou vers
  l'enrôlement si le compte n'a pas encore d'appareil), en gardant `?next=` ;
- partout ailleurs → la requête est traitée comme **anonyme** ;
- toujours permis : page du code, enrôlement, déconnexion, fichiers de l'admin.
Les sessions déjà ouvertes au déploiement passent par la même règle : les
superutilisateurs seront invités à s'enrôler à leur prochain clic.

### Écrans — FAIT le 27/10 (cms/double_auth.py, templates/cms/double_auth/)
- [x] **Code** : `/cms/double-auth/code/` (TOTP ou code de secours) ; limitation
      PAR COMPTE (`EchecsDoubleAuth`, 1 s, 2 s, 4 s… plafond 15 min) ; celle de
      django-otp est coupée (`OTP_*_THROTTLE_FACTOR = 0`) : par appareil, elle
      bloquait les téléphones des comptes partagés (prouvé par mutation)
- [x] **Mes appareils** (menu du compte) : nom, ajout, dernière utilisation,
      retirer. Pas de « renommer » : on retire et on rajoute (YAGNI)
- [x] **Ajouter** : QR code SVG + clé en clair, nom, mot de passe, code ; la clé
      vit en session, rien en base avant le bon code (`verify_token` aurait
      enregistré un appareil confirmé sur un code faux)
- [x] **Codes de secours** : 10, remis d'office au premier téléphone, affichés
      une fois, régénérables ; effacés avec le dernier téléphone
- [x] **Superutilisateur → autre compte** : lien sur la fiche utilisateur
- [x] **Dernier recours** : `manage.py retire_double_auth <compte>`
- [x] Tests : `cms/tests_double_auth.py` (20) + site en test dans
      `SectionDomainMiddlewareTest` ; 14 mutations toutes tuées ; suite
      complète 1 660 OK. Pendant les tests `DOUBLE_AUTH_OBLIGATOIRE='personne'`
      (refusé hors DEBUG par settings.py)
- [x] Contrôle navigateur (bureau + mobile) : enrôlement forcé, codes de
      secours, page des appareils, code à la reconnexion, code de secours,
      lien sur la fiche. **A trouvé un bug que les tests rataient** : la requête
      de fond `current-site-fragment`, renvoyée vers l'enrôlement, tirait une
      nouvelle clé → enrôlement impossible. Corrigé + test.
- [x] 27/10 (soir) : obligatoire AUSSI pour les rédacteurs en chef (réglage
      renommé `'chefs'`, règle `is_chef`), à la demande d'Arnaud, pour le compte
      partagé `media`. Deuxième personne d'un compte partagé : entre par un code
      de secours puis ajoute son téléphone (consigne sur la page du code, testé)
- [x] Notice pour les rédacteurs : document « Double authentification — notice pour les rédacteurs » (Claude Docs, 27/10)

### Retrait de wagtail-2fa — DÉPLOYÉ le 27/10 (5de754a)
- [x] App, middleware, réglage, requirements.txt (+ `six`, qui ne servait qu'à
      lui) ; `migrate wagtail_2fa zero` en dev (permission `enable_2fa` : 0
      groupe, 0 compte)
- [x] Prod : seul superutilisateur `arnaud`, permission `enable_2fa` sur 0
      groupe/0 compte ; `migrate wagtail_2fa zero` avec l'ancien code,
      deploiement.sh (code 0, cms.0049 appliquée), paquets désinstallés ;
      /cms/login/, /admin/login/ et / en 200
- [ ] Arnaud enregistre son téléphone TOUT DE SUITE (premier passage dans /cms/)

## 3. Wagtail 8 — DÉPLOYÉ le 28/10/2026 (ff19711)
- [x] Dépendances : wagtail 8.0.1, draftjs_exporter 5.2 → 7.3.1, + django-ninja,
      pydantic (+ core, annotated-types, typing-inspection), swapper ;
      wagtailmedia 0.19.1 passe. Une seule migration : wagtailcore.0098_apitoken
- [x] **Régression trouvée et corrigée** : en Wagtail 8, la politique de
      permissions vient d'un registre global, et pour une PAGE c'est l'arbre des
      pages → les rédacteurs (permissions de modèle seulement) n'accédaient plus
      à leurs articles (13 tests rouges). Correctif dans `cms/cloisonnement.py` :
      `ModelPermissionPolicy` injectée dans NOS écrans seulement (via
      `construct_view`), PAS enregistrée globalement — sinon l'explorateur de
      pages, non cloisonné, en aurait hérité. Marche aussi en 7.4.
- [x] Suites : 1 662 OK en 8 ET en 7.4
- [x] Contrôle navigateur en rédacteur (copie de la base migrée en 8) : menu
      identique à la 7.4, liste et édition de ses articles, bouton Publier ;
      articles d'un autre syndicat en 404 ; explorateur de pages : tout refus
- [x] Déploiement 28/10 : sauvegarde ~/cntso-avant-wagtail8-20261028-0617.sql.gz
      (13 Mo, 88 tables), deploiement.sh code 0, wagtailcore.0098 appliquée,
      Wagtail 8.0.1 en prod ; accueil, article, recherche, /cms/login/,
      /admin/login/ en 200, aucune erreur au journal. Retour arrière si besoin :
      commit 8f24ea5, `pip install -r requirements.txt`, `migrate wagtailcore 0097`
- ~~Constat : un rédacteur verrait l'explorateur sous le site confédéral~~
  **FAUX, vérifié le 28/10** : la page 4 était SON syndicat (CNT-SO 13), pas la
  conf. Wagtail le confine à son sous-arbre (accueil, autres sites, articles des
  autres → renvoyé sur sa page) ; aucune page rangée sous le syndicat d'un autre
  (1 782 pages : 700 hors de tout syndicat, sous l'accueil, invisibles des
  rédacteurs). Rien à corriger.
- Plus tard (Wagtail 9) : tests qui importent `wagtail.images.permissions.
  permission_policy` / `wagtail.documents…` (avertissements RemovedInWagtail90)

## 3. Finir
- [ ] requirements.txt, suite complète, contrôle visuel de l'admin
- [ ] Déploiement : séquence annoncée (migrate zero AVANT le pull qui retire les apps)
- [ ] Ensuite seulement : montée Wagtail 8 (chantier séparé)

# À faire — demandé le 05/10/2026 : « Qui sommes-nous » modifiable

Constat : texte écrit en dur dans `qui_sommes_nous.html` ; la page Wagtail
`qui-sommes-nous` existe mais l'URL est prise par la vue ; les deux images de
la page sont en 404 en prod (anciennes adresses WordPress).

- [x] Bloc « Cartes » (pictogramme + titre + texte), dans tous les corps de page
- [x] La vue lit la page Wagtail : corps dans la colonne, extrait dans le bandeau
- [x] Commande `remplit_qui_sommes_nous` : recopie le texte actuel (révision
      publiée), crée la page si absente, refuse d'écraser un corps rempli
- [x] Tests + mutation ; suite complète ; contrôle visuel
- [ ] Déploiement : migrate + commande en prod

Aussi : le bloc « Citation » n'avait aucun style sur tout le site (corrigé dans base.html).

# À faire — demandé le 17/09/2026

## 1. Retirer la case « Fiche pratique — téléchargeable en tract »
- [x] Compter en prod les articles qui l'ont cochée (attendu : le forfait jours)
- [x] Retirer `FieldPanel('fiche_pratique')` de l'éditeur (cms/models.py)
- [x] Garder le champ, la route `/article/<slug>/tract/` et le gabarit : l'article
      du forfait jours garde son tract
- [x] Décocher les autres articles s'il y en a (à valider avec Arnaud)

## 2. Carrousel : remettre le défilement automatique
- [x] Minuterie (≈6 s), **avec bouton pause** — WCAG 2.2.2 l'exige au-delà de 5 s
- [x] Arrêt au survol et au focus clavier ; respect de `prefers-reduced-motion`
- [x] Le défilement reprend là où l'on est après un clic sur flèche/pastille

## 3. Écran des messages reçus (/cms/contact/)
- [x] Ligne entière cliquable (le lien « Lire » devient superflu)
- [x] Par ligne : marquer lu / non lu, supprimer (avec confirmation)
- [x] Sélection multiple + suppression de masse (avec confirmation et compte)
- [x] Cloisonnement : un rédacteur n'agit que sur les messages de son syndicat

## 4. « Répondre par mail »
- [x] Encoder correctement le `mailto:` (objet, accents, espaces)
- [x] Ajouter « copier l'adresse » : marche même sans logiciel de courrier associé

## Vérification
- [x] Tests + mutation pour chaque point ; suite complète
- [x] Contrôle dans un vrai navigateur pour le carrousel et l'écran des messages

## Fait le 17/09/2026 — en attente de déploiement

- **Case « Fiche pratique » retirée de l'éditeur.** Un seul article la portait en
  production (« Forfait jours », pk 1917) : il garde son tract, le champ et la
  route restent. 4 tests.
- **Carrousel : défilement automatique (6 s) avec bouton pause.** Suspendu au
  survol, au focus clavier et quand l'onglet passe en arrière-plan ; ne démarre
  pas si l'utilisateur a réduit les animations. Vérifié dans un vrai navigateur :
  défile, la pause tient, la reprise repart, le survol suspend.
  Le test qui interdisait `setInterval` est réécrit autour de l'exigence réelle
  (WCAG 2.2.2) : si ça défile, la pause doit exister. Validé par mutation.
- **Écran des messages** : ligne entière cliquable (lien étendu, utilisable au
  clavier), boutons « marquer lu/non lu » et « supprimer » par ligne, sélection
  multiple et suppression de masse avec confirmation chiffrée. Toute action
  repasse par le filtre de syndicat. 8 tests, 5 mutations détectées.
- **« Répondre par mail »** : objet encodé (`Re%3A%20…`), arobase laissée
  littérale, plus un bouton « copier l'adresse » qui marche sans logiciel de
  courrier.
- **Piège trouvé au passage** : `{# … #}` sur plusieurs lignes n'est PAS un
  commentaire Django — le texte s'affichait dans la page. Utiliser
  `{% comment %}`. C'est un test qui l'a attrapé.
