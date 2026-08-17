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
