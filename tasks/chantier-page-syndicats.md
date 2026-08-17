# Chantier — rendre éditable la page « Nos syndicats et structures »

Ouvert et livré le 17/08/2026, à la demande d'Arnaud.

## Le problème

`/syndicats/` était une `ContentPage` dont tout le corps tenait dans **un seul
bloc HTML de près de 10 000 caractères**, feuille de style comprise. Ajouter un
champ de syndicalisation supposait de recopier un `<a>` et ses quatre `<div>`
imbriqués au milieu du CSS — le même symptôme que les permanences juridiques
avant leur refonte (cf. `content.Permanence`).

Symptôme révélateur : la page oubliait trois syndicats existants (STAA, TAS,
Numérique selon les bases). Non par choix éditorial, mais parce que personne
n'osait toucher au bloc.

## Ce qui a été fait

- **`content.FicheSyndicat`** — `site` (propriétaire, pour le cloisonnement),
  `titre`, `description`, `image` (image Wagtail) + `image_url` (repli sur les
  visuels hérités de l'ancien site), `order`, `is_active`.
- **La cible du lien est une clé étrangère**, seul écart au patron des
  permanences : `categorie` → `CmsCategory`, `site_cible` → `SectionPage`, ou
  `url` libre, résolus dans cet ordre par `get_lien()`. Onze cartes pointent
  vers une catégorie, et le réimport des catégories WordPress prévu au
  lancement (cf. `tasks/chantier-categories-lancement.md`) réécrira les slugs :
  onze `/categorie/<slug>/` en dur seraient devenus onze liens morts
  silencieux. `clean()` refuse une carte sans aucune destination.
- **`FicheSyndicatViewSet`** cloisonné par site, dans le groupe *Navigation* de
  `/cms/` aux côtés des menus, et déclaré dans les fabriques de
  `cms/tests_cloisonnement.py`.
- **`SyndicatsView`** sur `/syndicats/`, déclarée dans `content/urls.py` donc
  prioritaire sur le service Wagtail de la page de même slug. Le chapô reste le
  corps de la `ContentPage`, éditable dans `/cms/` via `_page_editoriale` —
  exactement comme les permanences.
- **`templates/content/syndicats.html`** — la grille et son CSS, qui ont leur
  place dans un gabarit et pas dans un champ de saisie.
- **`importe_fiches_syndicats`** — convertit les cartes existantes en fiches,
  idempotente, `--dry-run`, `--completer` (ajoute les syndicats absents),
  `--vider-la-page` (réduit le corps au seul chapô).

## Deux pièges rencontrés

**Ne pas parser du HTML à la regex.** Ma première version exigeait un `<img>`
par carte et sautait en silence les deux cartes sans image (Numérique et STAA
ont un aplat de couleur à la place). Pire, le `.*?` pouvait apparier le titre
d'une carte avec la description de la suivante. Réécrit avec BeautifulSoup,
déjà dans les dépendances.

**Les affiches ne se recadrent pas.** L'ancien CSS montait les visuels en
`object-fit: cover` sur 150 px de haut, ce qui rognait des affiches portant
titre, date et mot d'ordre. Passé en `contain` sur fond blanc, 170 px, comme
partout ailleurs depuis la refonte de l'accueil (cf. mémoire
`project_redesign_accueil`). Les cartes sans visuel gardent leur bloc sombre,
sans quoi la grille se désaligne.

## Tests

18 nouveaux, suite complète à **963 tests verts** : résolution des trois types
de liens, refus d'une carte sans destination, ordre, fiche masquée,
cloisonnement entre syndicats, chapô éditable, import (cartes sans image,
idempotence, `--dry-run`, `--completer`, `--vider-la-page`), et non-duplication
des cartes une fois la page vidée.

## Déploiement (17/08/2026) — fait

`migrate`, `collectstatic`, `importe_fiches_syndicats --dry-run --completer`
pour lecture, puis `--completer --vider-la-page`, redémarrage supervisor.
Page en 200, 19 cartes rendues dont 7 sans visuel, chapô conservé (183
caractères contre 9 802 avant). Visuels vérifiés à l'écran : les affiches
s'affichent entières, plus rognées.

**La page comptait 19 cartes et non 13.** Mon relevé initial passait par une
regex exigeant un `<img>` : elle avait sauté six cartes sans visuel, dont le
STAA et le TAS — que j'ai donc annoncés à tort comme absents de la page.
`--completer` n'a rien eu à ajouter, les 19 cartes couvrant déjà tous les
syndicats publiés. Leçon consignée dans `tasks/lessons.md`.

## Alignement page / menu (17/08/2026)

Le menu « Secteurs » listait 20 rubriques, la page 19 cartes. `--completer`
couvre désormais les deux sources : tout syndicat publié **et** toute rubrique
rangée sous « Secteurs » a sa carte. Ajoutés en production : T.P.E., Animation
& Éducation populaire, Intérim. « Librairie » supprimée sur demande d'Arnaud
(fusionnée dans le STUCS). « Fonction publique » est gardée bien qu'absente du
menu. Total : 21 cartes.

**L'article de « Librairie » n'était pas celui de la confédération.**
« Travailleur·euses des librairies, organisons-nous ! » (id 920) appartient à
**Auvergne**, comme la catégorie « Librairie » (id 98) vers laquelle pointait
la carte confédérale — le piège inter-syndicats déjà connu. Il a donc été
rebasculé vers la catégorie STUCS *d'Auvergne* (« Culture et Spectacle »,
id 64) et non vers celle de la conf : filer un article d'Auvergne sous une
catégorie confédérale irait à rebours du cloisonnement appliqué partout
ailleurs. Sa seconde catégorie (« TPE 2021 ») est conservée. La catégorie
« Librairie » reste en base, vide.

Trois défauts rattrapés en chemin, tous par le `--dry-run` sur la base de
production ou par la vérification de la page rendue :

1. Le filtre prenait **toute** entrée de menu pointant vers une catégorie, y
   compris « Solidarités », rubrique racine et non champ de syndicalisation.
   Restreint aux enfants de l'entrée « Secteurs ».
2. « Activités postales et Télécommunications » existe en **deux catégories**
   (héritage WordPress) : la fiche pointait sur l'une, le menu sur l'autre.
   Une carte de plus n'aurait été qu'un doublon. Les homonymes sont reconnus
   par nom normalisé et ignorés.
3. Le rang des cartes ajoutées repartait du nombre de cartes lues dans le HTML
   — zéro une fois la page vidée, ce que fait ce chantier lui-même. Les trois
   nouvelles se sont entrelacées en tête de grille avant correction. Le rang de
   départ est désormais lu en base.

## Reste à faire

- Rien de bloquant. Sept fiches n'ont pas de visuel (Fonction publique,
  Finance & Assurances, Agriculture, Numérique, STAA, TAS…) et affichent un
  bloc sombre portant leur nom : elles n'attendent qu'une affiche, désormais
  déposable depuis `/cms/` sans toucher au code.
