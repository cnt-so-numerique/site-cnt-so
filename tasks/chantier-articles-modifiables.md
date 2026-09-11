# Rendre modifiables les articles importés de WordPress

Ouvert le 10/09/2026.

## Le défaut

L'import range tout le contenu d'un article dans un **unique bloc « HTML brut
(import legacy) »**. Or ce bloc est masqué du menu de l'éditeur
(`CorpsBlock.BLOCS_MASQUES`, `cms/models.py`) : le rédacteur qui ouvre un
article importé tombe sur une zone de code source. Il ne peut pas corriger une
faute sans lire du HTML, ni déplacer une image, ni insérer un encadré.

C'est le cas des **51 articles repris le 06/09/2026**.

~~Et de 1 061 articles et 48 pages au total~~ — **faux** : ce chiffre venait de
la base de développement, qui diverge de la production. Mesuré en production
le 11/09/2026 :

| ArticlePage (1 854) | |
|---|---|
| texte entièrement modifiable | 758 |
| texte modifiable + un morceau de HTML brut (« mixte ») | 960 |
| entièrement en HTML brut | 114 |
| corps vide | 22 |

Le texte du fonds a donc bien été rendu modifiable par la migration d'origine.
Ce qui reste en HTML brut, ce sont **des images** : 1 775 blocs « image seule »
dans 970 articles, que le convertisseur ne peut pas changer en blocs image
parce qu'elles **ne sont pas dans la médiathèque Wagtail** — 1 521 fichiers sont
bien sur le serveur sous `/media/`, 249 pointent encore l'ancien WordPress.
S'y ajoutent 61 aperçus PDF, 26 morceaux de texte, 12 texte + image et 5
tableaux. Sur tout le fonds, la simulation ne trouve que **137 pages**
convertibles en l'état.

## Ce qui a été fait

- `cms/conversion_html.py` — convertit le HTML hérité en blocs `rich_text` et
  `image`. Deux règles :
  1. **On ne convertit que ce que l'on sait représenter.** Un morceau qui
     contient un tableau, une vidéo ou une balise inconnue reste en HTML brut.
     Un tableau déplié en paragraphes ne se répare pas.
  2. **Rien n'est produit sans que Wagtail ait confirmé pouvoir le rouvrir**
     (`ContentstateConverter.from_database_format`). C'est le défaut du
     15/08/2026 : 261 articles s'affichaient en public et rendaient une erreur
     500 dès qu'un rédacteur cliquait « Modifier ».

  Une image introuvable en médiathèque n'est jamais supprimée : sa balise
  d'origine est conservée dans un bloc HTML brut.

- `python manage.py convertit_html_modifiable` — reprise du fonds existant.
  `--dry-run`, `--section`, `--slug`, `--limit`, et `--publie-apres AAAA-MM-JJ`
  pour ne reprendre que le dernier lot importé sans toucher au fonds.
  Idempotente ; refuse les pages qui ont un brouillon en attente ; aligne la
  dernière révision, sans quoi l'éditeur rouvrirait l'ancien bloc et sa
  republication écraserait la conversion.

- `import_from_wp_api` produit désormais directement des blocs modifiables, et
  annonce en fin de course ce qu'il n'a pas su convertir.

- 19 tests (`cms.tests.ConversionHtmlModifiableTest`), **six gardes validées
  par mutation**. Suite complète : 1255 tests verts.

## Ce que la mesure sur contenu réel a changé

Éprouvé sur 14 articles réellement servis par l'ancien WordPress, et non sur
les seuls exemples des tests : **8 sur 12 retombaient entièrement en HTML
brut**. Le convertisseur n'aurait presque rien apporté.

En cause, dans 17 articles sur 20 : l'`<object class="wp-block-file__embed">`
du bloc fichier WordPress — un aperçu PDF masqué d'office, piloté par un moteur
JavaScript que nous n'embarquons pas, et qui double le lien de téléchargement
que l'import convertit déjà en bloc « fichier ». Un greffon inerte condamnait
l'article entier. Même chose pour un `<script>` d'embed Bluesky, que la
politique de sécurité du 09/09/2026 bloque de toute façon.

Ces deux-là sont désormais retirés — et ce sont les **seules** suppressions que
le module s'autorise, chacune tenue par un test et par sa mutation. Résultat sur
le même échantillon : **14 articles sur 14 deviennent modifiables**, 0 morceau
gardé en HTML brut, 0 image perdue.

## Leçon du jour : deux tests ne testaient rien

Validés par mutation, comme la règle du 26/08 l'impose. Deux sont passés
malgré la garde retirée :

- la normalisation `<br>` → `<br/>` était **du code mort** : bs4 referme les
  balises orphelines de lui-même. Retirée. Ce qui protège réellement, c'est la
  validation par le convertisseur de l'éditeur ;
- l'extraction des images hors des paragraphes semblait inutile, le nettoyage
  les retirant de toute façon. Elle sert en fait dans un seul cas — un morceau
  gardé en HTML brut — où sans elle l'image paraîtrait **deux fois**. Le test a
  été récrit sur ce cas.

## En production, le 11/09/2026

**48 articles convertis**, un laissé intact (« Forfait jours », qui contient un
tableau — la garde a joué et l'a dit). 62 blocs de texte, 78 blocs image,
54 greffons inertes retirés, zéro image perdue.

Article témoin vérifié contre l'original encore servi par l'ancien WordPress :
texte identique au caractère près (2 696), les 85 mots présents, les 4 images
là ; seul l'aperçu PDF inerte a disparu. L'écran de rédaction s'ouvre (200). Il
portait une révision (n° 915) : sans l'alignement de révision, l'éditeur aurait
rouvert l'ancien bloc HTML.

## Ce que l'import du 11/09 a cassé, et qui est corrigé

L'import de rattrapage n'avait qu'un article à créer par site. Il a pourtant :

1. **recréé 40 rubriques** (38 conf, 2 Éducation) dans un arbre rangé à la main,
   dont un « Actualités - luttes » qui a capté le nouvel article au lieu de
   « Actions ». L'import créait d'office toutes les catégories WordPress.
   → Il ne crée plus rien : correspondance par slug avec l'existant, plus un
   alias pour la seule rubrique renommée avec son slug (`actualites-luttes` →
   `actions`, cf. `chantier-categories-lancement.md` § 1). Les catégories sans
   équivalent sont nommées en fin de course ;
2. **perdu le PDF du rassemblement du 15/09** : 130 caractères de chemin pour
   un champ de 100. → `nom_qui_tient` raccourcit le nom en gardant dossier et
   extension. La recherche de doublon de documents ne marchait pas non plus
   (elle omettait le préfixe `documents/` réellement stocké) ;
3. **laissé le bouton « Télécharger »** de WordPress pointer l'ancien serveur,
   alors que le PDF était déjà en bloc fichier : un lien mort à la bascule.
   → Tous les liens vers un document converti sont retirés, pas le premier seul.

Et `normalise_urls_heritees`, commitée le 06/09 sans test, était **cassée deux
fois** : elle tombait sur la première page relue en base (`RawDataView` n'est
pas sérialisable), et même réparée elle n'aurait rien réécrit — elle cherche
dans le JSON du corps, où `"` devient `\"`, et capturait donc des chemins
finissant par une barre inverse. Premier test écrit, les deux défauts sont
tenus par mutation.

## Articles STUCS rangés sous la conf

`rend_au_syndicat` déplace un article sous son syndicat : parent Wagtail,
`section_slug`, rubriques remplacées par celles du syndicat (aucune créée),
révision alignée. L'ancienne adresse redirige d'elle-même (302).

Cinq articles de catégorie STUCS vivaient sous la conf ; quatre sont
déplaçables, le cinquième (HISTOROCK, id 24) a un brouillon en attente et reste
où il est. « FÊTES LIBRES » porte aussi la rubrique STAA, qui n'a pas
d'équivalent au STUCS.

**Fait le 11/09/2026** : Festival Europavox, Le roi est nu, FÊTES LIBRES et la
réforme de l'assurance-chômage sont au STUCS. Vérifié pour chacun : section,
parent et révision à `stucs`, éditeur en 200, ancienne adresse en 302 vers
`stucs.cnt-so.org`. Tous ont perdu la rubrique conf
`communication-culture-spectacle` (elle nomme le STUCS lui-même) ; FÊTES LIBRES
a aussi perdu sa rubrique STAA, sans équivalent au STUCS.

**HISTOROCK** (id 24) : son brouillon — révision n°3 du 11/06/2026, créée par un
script, sans auteur — a été écarté le 11/09 à la demande d'Arnaud (il reste
dans l'historique de la page), puis l'article rendu au STUCS.

## Remise en ordre et réimport, le 11/09/2026

- article du 07/09 supprimé puis réimporté avec le code corrigé (id 1971) :
  rubrique « Actions », **ses deux PDF**, aucun lien vers l'ancien serveur,
  éditeur et page publique en 200 ;
- les 40 rubriques recréées supprimées (toutes vides, repérées par comparaison
  avec la sauvegarde de la veille) ; « Actions » compte 111 articles ;
- réimport : **0 rubrique créée**, 38 reconnues, 37 sans équivalent signalées ;
- `normalise_urls_heritees` passée pour la première fois : **84 adresses
  réécrites sur 41 pages**, 104 laissées faute de fichier chez nous.

## Le fonds, le 11/09/2026

Le convertisseur cherchait les images par chemin exact ; Wagtail renomme ce
qu'il range. `ResolveurImages` les retrouve (chemin, rendu, même contenu sous
un autre nom, original d'une réduction WordPress) et verse les manquantes dans
la collection de leur syndicat.

| ArticlePage (1 854) | avant | après |
|---|---|---|
| texte entièrement modifiable | 758 | **1 811** |
| mixte (texte + HTML brut) | 960 | **17** |
| tout en HTML brut | 114 | **4** |
| corps vide | 22 | 22 |

ContentPage : 44 modifiables, 2 tout HTML, 22 vides.

Lot du 11/09 : 1 092 pages converties, 20 ignorées (tableaux, deux brouillons),
1 928 blocs image, 731 images retrouvées en médiathèque, **954 versées** (témoin
compris) — conf 352, 13 279, Auvergne 244, Poitiers 46, STUCS 26, Rhône-Alpes 7,
**aucune à la racine** —, 2 introuvables conservées, 4 morceaux gardés en HTML
brut. 0 bloc de texte que l'éditeur ne saurait rouvrir.

Témoin (page 176, Radisson Blu) : texte identique au mot près ; l'image est
l'original 1 080 px affiché sur la colonne (869 px) au lieu de la réduction
724 px — sans étirement. Arnaud : « j'ai du mal à voir la différence ».

Pour défaire : sauvegardes `~/cntso-AVANT-fonds-20260911-1438.sql.gz` et
`~/cntso-AVANT-chevrons-20260911-1512.sql.gz` ; les images versées sont celles
de numéro supérieur à 3334 (`~/repere-images-fonds.txt`).

## Les « > » partout (11/09/2026)

Arnaud les a vus, pas moi. `repare_richtext_illisible` (15/08) changeait `<br>`
en `<br/>>` : **1 487 « > » dans 262 articles**, pendant près d'un mois.
`retire_chevrons_br` les a retirés (0 restant, versions publiques et
révisions) ; l'expression fautive est corrigée et son test compare désormais
le texte exact.

## La 404 muette de l'écran d'édition (11/09/2026)

L'écran snippet des articles est cloisonné par « site courant », superutilisateur
compris : ouvert depuis un autre syndicat, il répondait 404 sans un mot. Il
bascule désormais sur le syndicat de l'article pour qui a le droit de le
choisir, avec un message. Les rédacteurs restent cloisonnés.

Reste : les articles de **Rhône-Alpes** ne s'ouvrent pas à l'édition tant que
ce syndicat est dépublié (il n'est pas proposé par le sélecteur) — antérieur
à ce chantier.

## Deux erreurs de mesure, pour mémoire

- J'annonçais « ~32 articles absents » du nouveau site. Il y en avait **deux**.
  La comparaison par slug et par la recherche du site ratait les slugs
  normalisés ; seule la logique de l'import lui-même (`slugify(unquote(…))`,
  interrogée sur la base de production) donnait le vrai chiffre.
- La capture « avant » de l'article témoin a disparu au redémarrage de session
  (le brouillon de travail n'est pas conservé). Le texte de l'original
  WordPress a servi de référence — meilleure, car indépendante.

## Reste à faire

- [x] Conversion passée en production le 11/09/2026 (48 articles).
- [x] Fonds converti le 11/09/2026 : 1 811 articles modifiables sur 1 854.
- [x] Import de rattrapage : deux articles seulement manquaient (07/09 conf,
      08/09 Éducation), importés le 11/09.
