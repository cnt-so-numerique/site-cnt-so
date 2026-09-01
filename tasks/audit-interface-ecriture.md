# Audit de l'interface d'écriture — 15/08/2026

Mesures faites sur le formulaire **réellement rendu** à un compte rédacteur
(`redac_test`, groupes `redacteur` + `redacteur_13`), pas sur le code seul, et
recoupées en production par requêtes en base et par HTTP public.

---

## Constat 1 — [GRAVE, VISIBLE EN LIGNE] Un article écrit dans le CMS n'a aucune date

`ArticlePage.save()` ne renseigne **ni `publication_date` ni `first_published_at`**
pour un article créé depuis `/cms/snippets/cms/articlepage/add/`. Le champ Date
de publication arrive vide et son texte d'aide dit « Date originale
(WordPress / import) » — un intitulé d'import, sur le champ qu'un rédacteur
d'aujourd'hui devrait remplir.

Or tout le site trie sur `('-publication_date', '-first_published_at')`. **Les
deux clés sont nulles**, et la production est sous PostgreSQL, qui place les
NULL **en tête** d'un tri décroissant (SQLite les place en queue — le défaut est
donc invisible en développement).

Vérifié en production le 15/08 : 3 articles live sans aucune des deux dates, tous
au STUCS. Le **flux RSS public** `https://stucs.cnt-so.org/feed/` sert
aujourd'hui, dans l'ordre :

```
1. test d
2. jkjmo
3. jkjmo
4. Travailleur·euse de la Culture et du Spectacle : rejoins le STUCS-CNTSO !
```

Idem pour l'espace presse et la page Ressources (`content/views.py` lignes 403,
431, 912 et `content/feeds.py` 19, 59, 96).

⚠️ **Ce qui masque le défaut ailleurs** : les pages de catégorie et les accueils
trient d'abord par `-has_img`. Les trois articles n'ayant pas d'image, ils
retombent en bas. C'est un hasard, pas une protection : un article de test **avec**
une image passerait devant tout le reste sur toutes les pages.

**Portée réelle** : 3 articles aujourd'hui parce que presque tout le contenu vient
de l'import WordPress, qui portait ses dates. Mais **chaque article écrit dans
le CMS** part avec ce défaut — c'est-à-dire tout ce que les syndicats vont
produire à partir de maintenant.

## Constat 2 — [GRAVE] Deux interfaces d'édition concurrentes pour le même article

`ArticlePage` est un modèle *Page* Wagtail **et** un snippet enregistré. Deux
définitions de panneaux ont été écrites séparément et ont divergé.

| | `/cms/snippets/cms/articlepage/edit/<pk>/` | `/cms/pages/<pk>/edit/` |
|---|---|---|
| Source | `ArticlePageViewSet.panels` | `ArticlePage.content_panels` |
| Onglets | Contenu, Métadonnées | Contenu › (Promotion, Métadonnées, **Contenu**) |
| Ordre | **Contenu d'abord** | Métadonnées d'abord |
| `in_carousel` | présent | **absent** |
| `featured_on_conf` | présent | **absent** |

Les deux répondent 200 au même rédacteur sur le même article (vérifié sur pk=62).

L'onglet « Contenu » qui contient un onglet « Contenu » vient d'un
`TabbedInterface` **imbriqué dans `content_panels`** là où il devrait être
l'`edit_handler` du modèle.

⚠️ **Atteignable en 2 clics** : le tableau de bord d'un rédacteur contient un lien
vers `/cms/pages/4/`, d'où l'on descend sur l'éditeur de pages. Ce n'est pas une
URL exotique — c'est le chemin qu'Arnaud a pris spontanément le 05/08.

Le panneau du viewset porte le commentaire « Contenu en premier : c'est là qu'un
rédacteur débutant commence ». L'intention est la bonne ; elle n'a simplement
jamais été reportée sur le modèle.

## Constat 3 — [MOYEN] Deux étiquettes sans champ sous elles

Sur l'onglet Métadonnées, le rédacteur voit :

- **« Section slug »** avec l'aide « Slug dénormalisé de la SectionPage parente »
- **« Mettre en avant sur la confédération »** avec son aide complète

Dans les deux cas l'`<input>` est en `type="hidden"` (bien : le premier est
imposé par `form_valid`, le second réservé aux chefs) **mais le panneau ne l'est
pas** — libellé et texte d'aide restent affichés, sans contrôle dessous.

Le premier est en plus du jargon interne : « slug dénormalisé », « SectionPage »
ne veulent rien dire pour un syndicaliste.

## Constat 4 — [MOYEN, sécurité] Le bloc « HTML brut » est offert à tout rédacteur

`ARTICLE_BODY_BLOCKS` propose `RawHTMLBlock` sans condition. Vérifié présent dans
le formulaire d'un rédacteur simple. C'est une **injection HTML/JS arbitraire sur
une page publique** par n'importe quel compte de syndicat.

Son propre libellé — « HTML brut (import legacy) » — et son aide — « Utilisé pour
le contenu importé qui ne peut pas être converti » — disent que ce n'est pas un
outil de rédaction. Il n'a pas à figurer dans le menu d'insertion.

## Constat 5 — [MINEUR] Le bouton souligné n'existe pas

`RICHTEXT_FEATURES` déclare `'underline'`, que Draftail ne connaît pas sous ce
nom. Chaque rendu du formulaire émet :

```
RuntimeWarning: Draftail received an unknown feature 'underline'
```

Le bouton est absent de la barre d'outils alors que le code croit l'avoir activé.

## Constat 6 — [À DÉCIDER] 94 % des articles n'ont pas d'extrait

Production, 15/08 : **1677 articles live sans extrait sur 1785**. Le champ est
facultatif et rien ne le remplit. L'extrait sert les cartes de liste, les
métadonnées SEO et le corps des newsletters.

---

## Ce qui va bien, à ne pas casser

- Onglet **Contenu en premier** côté snippet, et champ Titre hors des onglets.
- **Brouillon et Publication** disponibles au rédacteur, prévisualisation active.
- Blocs proposés lisibles et en français : Texte, Image, Galerie, Document,
  Citation, Vidéo / iFrame, Colonnes.
- Menu latéral **sans entrée « Pages »** : l'éditeur de pages n'est pas offert
  franchement (il reste atteignable, cf. constat 2).
- Catégories bornées au syndicat et groupées par parent (passe du 05/08).

---

## Propositions, par rapport valeur / risque

### A. Dater un article à sa création — *petit changement, gros effet*

Dans `ArticlePage.save()`, renseigner `publication_date` à `timezone.now()` quand
elle est vide **et que la page n'est pas issue de l'import** (donc à la
création). Corriger le texte d'aide : « Laissez vide pour dater à la
publication ; ne servez cette case que pour reprendre une date d'origine. »

Filet complémentaire : rendre le tri explicite avec `F('publication_date').desc(nulls_last=True)`,
pour que la question ne se repose plus jamais selon le moteur de base.

Et **traiter les 3 articles en ligne** : ce sont des essais (« test d », « jkjmo »
× 2) — à supprimer plutôt qu'à dater, mais c'est ta décision, ils sont au STUCS.

### B. Une seule définition de panneaux

Faire de `ArticlePage.content_panels` (et `edit_handler`) la **même source** que
`ArticlePageViewSet.panels`, plutôt que deux listes recopiées. C'est exactement
le remède qui a refermé la famille `legacy_site_slug` en passe 7 : une source
unique et un test qui refuse la recopie.

Au passage, sortir le `TabbedInterface` de `content_panels` pour le poser en
`edit_handler` — ce qui supprime l'onglet dans l'onglet.

### C. Masquer les panneaux, pas seulement les champs

Retirer `section_slug` des panneaux (il est imposé par le code, le rédacteur n'a
rien à en faire), et masquer le **panneau entier** de `featured_on_conf` pour un
non-chef au lieu de son seul `<input>`.

### D. Retirer « HTML brut » du menu d'insertion

Le bloc reste dans le modèle pour ne pas casser les articles importés qui en
contiennent, mais disparaît du menu d'ajout des rédacteurs.

### E. Retirer `'underline'`

Une ligne. Fait taire l'avertissement et aligne le code sur ce que voit
l'utilisateur.

### F. Extrait automatique si vide

Au premier enregistrement, dériver l'extrait des ~200 premiers caractères du
premier bloc de texte, sans écraser une saisie. À valider : c'est un
changement de contenu public sur 1677 articles si on l'applique rétroactivement
— je ne le proposerais **que pour les nouveaux articles**.

---

## Méthode — pièges rencontrés

- **Le rendu, pas le code.** Les labels « Section slug » et « Mettre en avant sur
  la confédération » apparaissent dans la liste des champs alors que leurs inputs
  sont cachés : lire les panneaux dans le code aurait donné une réponse fausse
  dans un sens, lire la liste des `<label>` une réponse fausse dans l'autre.
- **Le tri NULL dépend du moteur.** Le défaut du constat 1 est **invisible en
  développement** (SQLite) et actif en production (PostgreSQL). Une reproduction
  locale aurait conclu « rien à signaler ».
- **Une page d'accueil correcte ne prouve rien.** L'accueil du STUCS paraît sain
  parce qu'il trie d'abord par présence d'image ; c'est le flux RSS qui a montré
  le défaut. Il a fallu chercher la liste qui ne trie *pas* par image.

---

# Deuxième passe — 31/08/2026

Demande d'Arnaud : « quand on se connecte avec un compte de haut niveau il faut
atterrir avec la conf sélectionnée » et « il faut revoir totalement l'interface
de création des articles, l'article est noyé sous les autres infos ».

Mesures au navigateur sur `/cms/snippets/cms/articlepage/add/`, 1440×900,
compte superuser.

## Ce qui occupait l'écran

| Élément | Avant | Après |
|---|---|---|
| Barre syndicat | 79 px, 14 pastilles sur 2 lignes | 41 px, un menu déroulant |
| Minimap + « Tout replier » | 400 px de la colonne | retirés |
| Bulles de commentaire | 32 (0 commentaire en base / 1710 articles) | 0 |
| Ancres 🔗 de panneau | 32 | 0 |
| Largeur de saisie | 840 px | 1080 px |
| Zone d'écriture | un « + » de 30 px, étiqueté « Body », à y=513 | un cadre de saisie à y=553, dans le premier écran |

Le bouton « Tout replier » est rendu **par** le composant minimap : masquer
`[data-minimap-container]` retire les deux. Vérifié dans le DOM, pas supposé.

La variante `.w-panel__anchor--prefix` garde un `display: grid` qui l'emporte
sur un sélecteur à deux classes — d'où le ciblage par `[data-panel-anchor]`.

## Le syndicat courant

`get_current_site()` renvoyait `None` pour un chef global sans choix en session.
La barre affichait « ⚠️ Aucun sélectionné », les listes servaient les quatorze
syndicats mêlés, et aucun bouton ne ramenait à cet état une fois qu'on en était
sorti : il n'existait qu'au premier écran après connexion.

Repli sur `principal`. Conséquence assumée : le cloisonnement s'applique dès la
connexion. `NewsletterSendView` refuse désormais la lettre d'un autre syndicat
là où un chef sans syndicat choisi passait au travers.

## Effet de bord relevé, non corrigé en masse

**400 blocs de texte vides dorment en base, sur 229 articles** — hérités de
l'import WordPress. Ils produisent un `<div class="rich-text"></div>` sur la
page publique (vérifié sur l'article 293). Le crible posé dans
`ArticlePageForm.clean()` les retire **quand un humain enregistre cet
article**, jamais en lot : aucune migration de contenu n'a été lancée.

## Les trois cases « mise en avant » — deux faisaient double emploi, aucune ne marchait

Arnaud, 31/08/2026 : « c'est quoi la différence entre le 1 et le 3 ? ».

Aucune. `HomePage.get_context` les joignait par un OU :

```python
Q(section_slug='principal', is_featured=True) | Q(featured_on_conf=True)
```

Sur un article de la conf — le seul écran où les deux s'affichaient ensemble —
cocher l'une ou l'autre donnait le même résultat. `is_featured` n'était qu'un
sous-ensemble de `featured_on_conf`, **en plus offert à tout rédacteur** alors
que `featured_on_conf` est masqué aux non-chefs : le verrou qui réserve la une
aux chefs était contournable par la case d'à côté.

En cherchant où `featured_on_conf` atterrissait, plus grave :

| Constat | Vérification |
|---|---|
| `/` est servi par `content.views.HomeView` | `content.urls` inclus avant `wagtail_urls` |
| `HomePage.get_context` ne sort nulle part | aucun gabarit ne lit `featured_article` ni `hero_mini_cards` |
| `in_carousel` ignorait la conf | `section_type__in=['sectoral','regional']`, la conf est `main` |

Donc, sur un article confédéral, **les trois cases étaient inertes**. Sur un
article de syndicat, seule `in_carousel` agissait. 0 article sur 1710 en portait
une seule.

**Corrigé** — « il faut bien pouvoir remplir le carrousel et la une depuis la
création d'article » :

- `is_featured` supprimé (migration `0030`) ;
- `in_carousel` synchronise sur **tous** les sites, conf comprise ;
- `featured_on_conf` appliqué dans `HomeView` : un article hissé à la une par
  un chef rejoint le carrousel confédéral, quel que soit son syndicat ;
- les épinglés de la fiche passent devant — l'ordre du carrousel reste un choix
  éditorial ;
- le bloc mort de `HomePage.get_context` retiré ;
- libellés : « Au carrousel de mon syndicat » / « À la une de la confédération »,
  chacun nommant enfin **son** accueil.

## La une des syndicats — et la règle des affiches, restée à moitié appliquée

Arnaud, 31/08/2026 : « il faut que les sites des syndicats aient eux aussi une
une ».

Ils en avaient déjà une, au sens du gabarit : `_article_listing.html` s'intitule
« Option C — Layout Une de journal » (article 1 en tête, 2-3 en duo, 4+ en
grille). Mais il était rendu **à l'inverse de la décision du 16/08** — affiche
entière sur blanc, titre dessous :

```css
.une-hero      { height: 460px }        /* affiche recadrée en bandeau */
.une-hero-img  { object-fit: cover }
.une-hero-overlay { linear-gradient(rgba(0,0,0,.82) …) }   /* voile noir */
.une-hero-title   { position: absolute }                   /* titre PAR-DESSUS */
.une-card-img img { object-fit: cover }                    /* et les petites cartes aussi */
```

La règle avait été appliquée à l'accueil confédéral (`.hp-manchette`,
`object-fit: contain` sur blanc) et **jamais à ce gabarit**, qui sert cinq
écrans : accueils de syndicat, pages de catégorie, pages de tag, espace presse,
`site_home`.

**Livré :**

- la manchette de la conf devient `templates/content/_manchette.html`, partagée
  entre l'accueil confédéral et ceux des syndicats — CSS compris, sorti de
  `home.html` : une seule définition ;
- `SiteHomeView._vitrine()` calcule diaporama + manchette une seule fois, et
  `get_queryset` les retire de la liste. Le même article s'affichait jusqu'à
  **trois fois** sur un écran (constaté sur `/13/`) ; repli si le syndicat n'a
  que des articles de vitrine, pour ne pas servir « Aucun article » ;
- voile et recadrage retirés du bloc de tête **et** des petites cartes ;
- hauteur fixe résiduelle de 300 px supprimée en mobile — elle aurait rogné
  l'affiche et le titre maintenant qu'ils sont dans le même bloc.

Les deux derniers points ont été trouvés **par un test trop large** qui
cherchait `object-fit: cover` partout : il échouait sur sa propre phrase
d'explication, et en le resserrant sur les règles CSS j'ai vu que les cartes et
le média mobile n'avaient pas été traités.
