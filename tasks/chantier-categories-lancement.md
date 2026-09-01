# Catégories — à reprendre AU LANCEMENT

> Créé le 2026-08-16 à la demande d'Arnaud : « note bien car on va devoir mettre
> à jour au lancement la base de données avec les anciennes catégories ».

Au moment de la bascule DNS (`cnt-so.org` → nouveau site), la base sera mise à
jour avec les catégories de l'ancien WordPress. **Les décisions ci-dessous
devront être réappliquées**, sinon elles seront écrasées.

## 1. « Actualités - luttes » → « Actions » (fait le 2026-08-16)

La colonne « Actions » de l'accueil était vide : la vue cherche le slug
`actions`, qui existait mais ne portait **aucun article**, tandis que les 97
articles vivaient dans `actualites-luttes`.

Ce qui a été fait, en production comme en développement :

| Objet | Action |
|---|---|
| Catégorie `actions` (conf, 0 article) | **supprimée** — son slug bloquait le renommage |
| Catégorie `actualites-luttes` (conf, pk 11, 97 articles) | renommée : nom **« Actions »**, slug **`actions`** |
| Entrée de menu conf n° 109 | libellé « Actualités – Luttes » → **« Actions »** |
| Redirection Wagtail `/categorie/actualites-luttes` → `/categorie/actions/` | créée (voir réserve au § 3) |

Côté code (commité) :

- `content/context_processors.py` : `('actualites-luttes', …)` → `('actions', 'Actions')`
  dans `menu_structure['confederation']` ;
- `templates/content/home.html` et `templates/content/article_detail.html` :
  vignette d'appel `/categorie/actualites-luttes/` → `/categorie/actions/`.

**Volontairement PAS touché** — et à ne pas « corriger » par réflexe :

- `cms/models.py` (`context['luttes_articles']`, slug `actualites-luttes`) sert
  les accueils de **sous-sites**, qui gardent chacun leur propre catégorie de ce
  nom. Le 13 en a 132 articles, Éducation une vide ;
- `cms/management/commands/fix_etiquetage_categories.py` : mapping d'import.

## 2. À refaire après le réimport des anciennes catégories

1. Vérifier si l'import recrée une catégorie conf `actualites-luttes` **et** une
   `actions`. Si oui, refaire la fusion : déplacer les articles vers `actions`,
   supprimer le doublon.
2. Vérifier que l'entrée de menu conf pointe bien sur `actions` et s'intitule
   « Actions ».
3. Contrôler la colonne « Actions » de l'accueil : elle doit lister des articles.
4. Ne pas renommer les catégories homonymes des sous-sites.

## 3. Réserve connue : la redirection ne se déclenche pas encore

`/categorie/actualites-luttes/` sur le domaine confédéral répond **200**, pas
301. Cause : `CategoryDetailView.get_queryset()` ne trouve pas la catégorie chez
la conf, puis **se rabat sur celle d'un autre syndicat** portant le même slug —
ici Éducation, qui n'a aucun article. La page s'affiche donc vide, sous le titre
d'un autre syndicat, et la redirection Wagtail (qui n'agit que sur un 404) ne
joue jamais.

La redirection est laissée en place : elle est juste dans son intention et
deviendra active le jour où ce repli sera resserré. **Ne pas supposer qu'elle
fonctionne aujourd'hui.**

Ce repli concerne **166 slugs** appartenant à d'autres syndicats et servis sous
l'URL de la conf. Le resserrer les ferait tous basculer en 404 : c'est une
décision à prendre pour elle-même, avec les redirections correspondantes, pas en
passant. À arbitrer pendant le chantier de lancement.

---

# Relevé du 31/08/2026 — ce que l'écran de rédaction a mis au jour

Fait ce jour (livré) : un groupe n'apparaît plus que s'il distingue quelque
chose. Une catégorie sans enfant redevient une simple case — 12 des 15 en-têtes
de la conf étaient un titre au-dessus de leur propre nom. Le regroupement par
parent reste, il est indispensable au 13.

**Tout le reste ci-dessous est en attente d'arbitrage d'Arnaud.**

## 1. Les trois familles — bloqué par une limite technique

Demande : séparer **lieux / secteurs / le reste**, au moins une catégorie
géographique par région.

Deux obstacles, dans cet ordre :

- Rien ne dit aujourd'hui qu'une catégorie est un lieu ou un secteur. Champs de
  `CmsCategory` : `name`, `slug`, `section_slug`, `description`, `parent`,
  `legacy_id`. Il faut **ajouter un champ `famille`** (migration + classement
  des 247 lignes).
- **Django ne sait grouper les cases QUE sur un seul niveau** (`optgroups`).
  Or le regroupement par parent est déjà pris et ne peut pas être abandonné :
  le 13 a sept « Actualités - luttes », une par secteur, dont cinq portent
  exactement le même nom. Afficher famille **et** parent demande donc un
  **widget maison** avec son propre gabarit, pas un réglage.

## 2. Le dédoublonnage

247 catégories, 183 noms distincts → **64 recopies**. 21 noms présents sur
plusieurs syndicats.

```
Non classé            × 6   13, auvergne, numerique, poitiers, principal, rhone-alpes
Nettoyage             × 4   13(10), auvergne(20), principal(93), rhone-alpes(11)
Santé & social        × 4
CNT-SO                × 3   auvergne(90), principal(27), rhone-alpes(1)
```

Et sur le **seul site 13**, sept rubriques « actualités », une par secteur :

```
Education - Recherche › Actualités - luttes   133 art
Nettoyage             › Actualités - luttes    85
Interpro              › Actualités - luttes    20
BTP                   › Actualités - luttes     5
Transports            › Actualités - luttes     3
Santé & social        › Actualité et luttes     6
Restauration          › Actualité - luttes      3
```

## 3. Nommage à normaliser

Cinq graphies inclusives pour le même mot : `travailleur·euses` (point médian),
`Travailleur.euse.s`, `Travailleurs.euses`, `Travailleur-euses`,
`travailleurs.euses`. Proposition : **le point médian partout**, celui que le
STUCS emploie pour lui-même.

Défauts francs, corrigeables sans arbitrage si Arnaud le dit :
- faute de frappe **« Animation & Education Popuplaire »** (6 articles) ;
- **deux « Gard »** — l'un sous *CNT-SO Occitanie* (1 art), l'autre sous
  *Syndicalisme* (4 art).

## 4. Deux imbrications qui n'ont pas de sens

```
Syndicalisme › Syndicat national des transports…  0 article  ← niveau vide
                 └─ Transport - logistique         4 articles
Syndicalisme › …culture et du spectacle (STUCS)   32 articles
                 └─ …Artistes-Auteurs (STAA)        6 articles  ← deux syndicats distincts
```

Ce sont elles qui produisent les derniers en-têtes à une seule entrée dans
l'écran de rédaction : corriger la donnée corrige l'affichage.

## 5. 166 catégories d'autres syndicats servies sous l'adresse de la conf

Arnaud, 31/08/2026 : « les catégories du menu de la conf sont reliées à
l'Auvergne, ça n'a pas de sens ». Vérifié — le mécanisme n'est pas le menu
(aucune entrée croisée en base) mais le **repli inter-syndicats de
`CategoryDetailView`** :

```
/categorie/petite-enfance/     → Petite enfance - CNT-SO Auvergne
/categorie/coiffure-esthetique/ → Coiffure/Esthétique - CNT-SO Auvergne
/categorie/agro-alimentaire/   → Agro-alimentaire - CNT-SO Auvergne
```

**166 slugs** sont dans ce cas : 13 (55), education (43), auvergne (39),
poitiers (16), rhone-alpes (8), stucs (7), staa (7).

## 6. Hors catégories, relevé au passage

- **11 `ArticlePage` portent `section_slug='staa'` et sont servies
  publiquement** sur `/staa/…`, sitemap compris, alors que le STAA a son propre
  site. Dont `/staa/site-en-cours-de-fabrication/` et `/staa/post-201/`
  intitulé « (Sans titre) ». Décision de contenu.
- **`Debug A`, `Debug B`, `test`** figurent encore dans le sélecteur de
  syndicat (0 article chacun). À vérifier en production avant toute suppression
  — la base de dev est désynchronisée.
