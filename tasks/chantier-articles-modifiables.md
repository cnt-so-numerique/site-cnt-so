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

## Reste à faire

- [ ] Passer la conversion en production (voir la séquence annoncée en séance).
- [ ] Décider du fonds : 1 100 pages sont dans le même état. La conversion
      change légèrement le rendu public (les images deviennent des blocs
      centrés pleine colonne, avec leur légende). À regarder sur un article
      avant d'engager le lot.
- [ ] Importer les ~32 articles encore absents du nouveau site (voir
      `tasks/chantier-bascule-dns.md`).
