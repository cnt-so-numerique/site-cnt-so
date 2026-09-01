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

## 2. « Dédoublonnage » — LA NOTE ÉTAIT FAUSSE, corrigée le 01/09/2026

J'avais écrit « 247 catégories, 64 recopies à dédoublonner ». **Deux erreurs**,
toutes deux dues à une analyse faite sur ma base de développement et non sur la
production :

- la production compte **218** catégories, pas 247 ;
- surtout, les « recopies » n'en sont pas.

Un même nom sur deux syndicats différents (« Nettoyage » au 13, en Auvergne, à
la conf…) n'est PAS un doublon : c'est le modèle multisite. Chaque syndicat a sa
catégorie et ses articles. Les fusionner casserait le cloisonnement.

Même nom **dans le même syndicat**, en production : **6 cas seulement**.

```
13         « Vos droits »              ×6   un par secteur
13         « Revendiquons ! »          ×7   un par secteur
13         « Actualités - luttes »     ×5   un par secteur
13         « Se syndiquer »            ×2
13         « CNT-Solidarité Ouvrière » ×2
principal  « Gard »                    ×2   ← le seul vrai doublon
```

Les cinq du 13 sont sa **taxonomie par secteur**, héritée de WordPress :
chaque rubrique appartient à un secteur, porte son propre slug et ses propres
articles. **Les fusionner détruirait l'organisation du plus gros syndicat du
réseau** (532 articles). `cms.tests.RangeCategoriesConfTest` contient un test
qui échoue si une fusion générique est un jour ajoutée.

### Ce qui reste réellement à ranger — commande `range_categories_conf`

Trois défauts francs, tous confédéraux, tous vérifiés en production :

1. **Deux « Gard »** — pk 76 (slug `gard`, parent Syndicalisme, 4 articles) et
   pk 77 (slug `gard-cnt-so-occitanie`, parent CNT-SO Occitanie, 1 article).
   On garde le premier, on lui reverse l'article du second, on le range sous
   « CNT-SO Occitanie » : le Gard est un département, pas un secteur.
2. **Un niveau vide** — « Syndicat national des transports et de l'aménagement
   du territoire », 0 article, dont l'unique rôle est de porter
   « Transport - logistique » (4 articles). Un nom de syndicat au milieu de
   noms de métiers. L'enfant remonte sous « Syndicalisme ».
3. **STAA sous STUCS** — « …Artistes-Auteurs (STAA) » (6 art) est enfant de
   « …culture et du spectacle (STUCS) » (32 art). Deux syndicats distincts ; le
   STAA a même son propre site. Il remonte sous « Syndicalisme ».

```bash
python manage.py range_categories_conf              # constat seul
python manage.py range_categories_conf --appliquer
```

Filet : la commande refuse d'écrire si un article se retrouve sans aucune
catégorie, et vérifie que la fusion réunit bien l'union des deux.

## 3. Naming — EN ATTENTE D'ARBITRAGE

Corrections à ma note précédente : **« Popuplaire » et « Etudiant-es » sans
accent n'existent pas en production** — c'était ma base de dev. En ligne, c'est
« Animation & Éducation Populaire » et « Étudiant-es », correctement écrits.

En revanche l'écriture inclusive est bien hétérogène, vérifié en ligne :

```
travailleur·euses   point médian   principal (STUCS)
uni·es              point médian   principal
Travailleur.euse    points         principal (STAA)
Travailleurs.euses  points         principal (sans-papiers)
travailleurs.euses  points         principal, auvergne (plateformes)
Travailleur-euses   trait d'union  principal (de la terre)
Auteur.e            points         auvergne
```

Sept graphies. Choix d'Arnaud — ce sont les mots du syndicat.

## 4. 14 catégories vides — EN ATTENTE D'ARBITRAGE

```
stucs        Banque d'images · Communiqués · Fanzine · Revue de presse
             · Visuels à télécharger          ← rubriques prévues ?
13           Commerce et services · Permanences syndicales · Transports
             · Web - Liens
principal    « actions à venir » · « communiqué de presse » (en minuscules)
             · Syndicat national des transports (traité en 2. ci-dessus)
numerique    Banque d'images
rhone-alpes  TPE - salariés du particuliers   (syndicat dépublié)
```

Celles du STUCS ressemblent à des rubriques préparées pour un syndicat jeune :
à garder, sans doute. Les autres, à trancher.

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
- ~~**`Debug A`, `Debug B`, `test`** dans le sélecteur~~ — **RÉGLÉ le
  01/09/2026.** Vérifié en production : **aucun des trois n'y existe**. C'étaient
  des résidus de ma seule base de développement. `test` supprimé en dev (cascade :
  1 formulaire de contact, 2 abonnés d'essai ; aucun appel OVH possible, les clés
  sont vides en dev). Le sélecteur en production sert **8 syndicats** — les huit
  vrais —, STAA et TAS écartés comme sites externes, 4 fiches non publiées déjà
  invisibles.
