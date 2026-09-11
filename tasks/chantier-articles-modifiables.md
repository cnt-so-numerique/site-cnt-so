# Rendre modifiables les articles importés de WordPress

Ouvert le 10/09/2026.

## Le défaut

L'import range tout le contenu d'un article dans un **unique bloc « HTML brut
(import legacy) »**. Or ce bloc est masqué du menu de l'éditeur
(`CorpsBlock.BLOCS_MASQUES`, `cms/models.py`) : le rédacteur qui ouvre un
article importé tombe sur une zone de code source. Il ne peut pas corriger une
faute sans lire du HTML, ni déplacer une image, ni insérer un encadré.

C'est le cas des **51 articles repris le 06/09/2026** — et, mesuré en base de
développement, de **1 061 articles et 48 pages** au total.

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

## Remise en ordre et réimport, le 11/09/2026

- article du 07/09 supprimé puis réimporté avec le code corrigé (id 1971) :
  rubrique « Actions », **ses deux PDF**, aucun lien vers l'ancien serveur,
  éditeur et page publique en 200 ;
- les 40 rubriques recréées supprimées (toutes vides, repérées par comparaison
  avec la sauvegarde de la veille) ; « Actions » compte 111 articles ;
- réimport : **0 rubrique créée**, 38 reconnues, 37 sans équivalent signalées ;
- `normalise_urls_heritees` passée pour la première fois : **84 adresses
  réécrites sur 41 pages**, 104 laissées faute de fichier chez nous.

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
- [ ] Décider du fonds : 1 100 pages sont dans le même état. La conversion
      change légèrement le rendu public (les images deviennent des blocs
      centrés pleine colonne, avec leur légende). À regarder sur un article
      avant d'engager le lot.
- [x] Import de rattrapage : deux articles seulement manquaient (07/09 conf,
      08/09 Éducation), importés le 11/09.
