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
