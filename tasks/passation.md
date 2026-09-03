# Où en est le chantier — 03/09/2026

Note de passation, écrite avant compactage. **À relire en début de séance.**

## En production, déployé et vérifié

```
HEAD 69e7b15 · gunicorn 26.2.0 · django 6.1.1 · wagtail 7.4.3 LTS · DRF 3.18.0
1181 tests verts
```

- **Écran de rédaction** refait : deux colonnes (titre/article/extrait à gauche,
  réglages à droite), catégories en pleine largeur, minimap et « Tout replier »
  retirés, commentaires coupés, cadre de saisie ouvert d'office.
- **Une des syndicats** : manchette partagée avec la conf, affiches entières sur
  blanc (règle du 16/08 enfin appliquée aux 5 écrans du gabarit partagé).
- **Catégories** : 60 % des pages de la conf servaient un autre syndicat →
  redirection 302 ; 5 flux qui rendaient 500 réparés ; arbre rangé ;
  écriture inclusive au point médian.
- **Contact** : hCaptcha n'autorisait que `cnt-so.org` (aucun formulaire
  n'était envoyable) + en-tête « De » invalide. Les deux réglés. Premier
  message reçu et remis.
- **Adhésion** : 7 boutons sur 8 rendaient 404 → page « à venir » + contact.
- **346 fichiers legacy** rapatriés de l'ancien serveur, servis par nginx.

## Décisions prises (ne pas les rouvrir)

- **Wagtail 8 : NON.** wagtail-2fa plante à l'import (module retiré),
  wagtail-seo exige `<8.0` et n'a rien publié depuis 14 mois. 7.4 est **LTS**
  et reçoit les correctifs. Rester est le bon choix.
- **Catégories vides : on garde tout**, ce sont des rubriques à remplir.
- **Taxonomie du 13** (« Vos droits » ×6 etc.) : PAS des doublons, ne jamais
  fusionner. Test de garde dans `cms.tests.RangeCategoriesConfTest`.
- **Déploiement automatique par GitHub Actions : non** (clé SSH du serveur en
  secret). Tests + veille sécurité : oui.

## En cours / à faire

1. **GitHub Actions** — tests contre **PostgreSQL** (les tests tournent sur
   SQLite, la prod sur PostgreSQL : c'est le trou qui a laissé passer le bug
   de tri des dates nulles en août). S'inspirer de `cnt-adhesion/.github/
   workflows/tests.yml`, même auteur. + `pip-audit` hebdomadaire.
   Vérifier d'abord que l'organisation autorise les Actions.
2. **Menu de l'Éducation** — 25 entrées, toutes en URL écrites à la main ;
   « Accueil » sans cible, « Textes officiels » et « Supérieur – Recherche »
   à `#`. Refonte à faire avec le syndicat.
3. **Bascule DNS** — tout est prêt côté serveur. Reste : DNS chez OVH
   (cnt-so.org, www, educ → 51.91.242.64), certbot APRÈS le DNS avec TOUS les
   noms, `MAIN_SITE_BASE_URL` et le `custom_domain` de l'Éducation le jour J
   (surtout pas avant). Voir `!DEPLOIEMENT.md`.

## Pièges appris aujourd'hui

- `cmd | tail` masque l'échec de `cmd` — `set -euo pipefail`, jamais de tuyau
  sur ce qui compte. A fait passer un déploiement raté pour réussi.
- `git pull` en HTTPS est **cassé** sur le serveur (git 2.39.5 de Debian 12).
  Clé de déploiement SSH sur le dépôt **personnel** (l'organisation interdit
  les clés). `./deploiement.sh` compare les deux dépôts et refuse si divergence.
- Toujours vérifier **en production**, pas en dev : la base de dev diverge
  (sites Debug, « Etudiant-es » sans accent, 0 article avec `is_featured`
  alors que la prod en avait un).
- Pour une question de navigation, lire **le HTML servi**, pas la base : j'ai
  conclu deux fois de travers en interrogeant les clés étrangères.
