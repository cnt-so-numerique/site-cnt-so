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
gabarit (le <title> et la meta description viennent du titre et de l'extrait).

## 2. wagtail-2fa → double authentification maison sur django-otp
Décidé le 27/10 : **obligatoire pour les superutilisateurs, facultative pour
les rédacteurs** (bascule « obligatoire pour tous » = un réglage, plus tard).
Comptes partagés dans les syndicats : un appareil TOTP **par personne** sur le
même compte (nommé, révocable seul), pas un QR code commun.
- [ ] Retirer `wagtail_2fa` (app, middleware, réglage) ; garder `django_otp`
      + `otp_totp` + `otp_static` (tables vides en prod, rien à migrer)
- [ ] Connexion /cms/ : après le mot de passe, étape « code à 6 chiffres » si
      le compte a un appareil ; superutilisateur sans appareil → enrôlement forcé
- [ ] Page « Double authentification » dans le compte : ajouter un appareil
      (QR code + nom + confirmation par un code), lister, retirer ;
      générer 10 codes de secours
- [ ] Superutilisateur : retirer les appareils d'un autre compte (téléphone perdu)
- [ ] Limiter les essais de code (django-otp a un throttling intégré : vérifier)
- [ ] Tests : sans appareil, avec appareil (bon/mauvais code), superutilisateur
      forcé, code de secours à usage unique, révocation ; mutation
- [ ] Contrôle visuel : connexion superutilisateur + rédacteur, mobile compris
- [ ] Courte notice pour les rédacteurs (comment activer, que faire si perte)

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
