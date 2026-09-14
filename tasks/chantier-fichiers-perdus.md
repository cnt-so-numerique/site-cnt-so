# Chantier : les fichiers joints perdus à l'import

Constaté le 14/09/2026 sur
<https://cnt-so.org/article/election-tpe-tpa-2021-avec-la-cnt-so-pour-lalternative-syndicale/> :
les 9 professions de foi (PDF) n'apparaissent plus que comme des noms nus
(`cnt_so_tpe_2021_btp`), sans lien.

## Cause

Le lien a été perdu **au tout premier import WordPress → EditorJS** (app `content`,
modèle legacy `Article`) : la copie d'origine en base porte déjà
`{"type": "paragraph", "data": {"text": "cnt_so_tpe_2021_btp"}}`. La reprise dans
Wagtail puis `cms/conversion_html.py` n'y sont pour rien — rejoué le 14/09 : la
conversion garde les `href`.

## Ampleur (base de dev, désynchronisée : à remesurer en prod)

- **205 articles, 256 liens** réduits à un nom de fichier (PDF surtout, quelques
  mp3/mp4/odt). Heuristique : `<p>` dont tout le texte est un nom avec `_`.
- Le rapatriement du 02/09 (346 fichiers) **ne les couvre pas** : il ne visait que
  les adresses encore présentes dans les corps, or celles-ci avaient disparu.
- **Ces fichiers n'existent plus que sur l'ancien serveur** (5.196.74.69,
  `testwp.cnt-so.org`), qui sert encore les fichiers statiques avec **listing de
  dossiers activé**. Ses pages HTML redirigent vers cnt-so.org : plus de source
  pour les liens des sous-sites. Le miroir `old` ne couvre que le site principal.

## Inventaire de l'ancien serveur (14/09/2026)

722 dossiers, **1 302 documents, ~1,1 Go** : 1 255 pdf, 16 odt, 10 mp3, 5 ogg,
4 zip, 4 txt, 4 mp4, 3 docx, 1 xls. Liste : `tasks/donnees/documents_ancien_serveur.txt`
(script : `tasks/donnees/inventaire_documents_ancien_serveur.py`).

Rapprochement nom nu → inventaire (256) : 132 exacts, 47 exacts mais présents dans
plusieurs dossiers, 23 par préfixe, 25 préfixe ambigu, 29 introuvables.
⚠️ **Le préfixe se trompe** (`tract_1er_mai.pdf` → `Tract-1er-mai-2025.pdf`) :
jamais de relien automatique sur préfixe sans une source qui le confirme.

## Plan

1. [x] **Assurance — FAIT le 14/09/2026** : `legacy/` passe de 378 à 1 668 fichiers
   (+1 290, les 12 autres existaient déjà), 0 erreur wget, PDF BTP servi en 200 sur
   cnt-so.org à la taille d'origine (675 352 octets). **L'ancien serveur peut s'arrêter
   sans perte de documents.** Détail d'origine : : rapatrier les 1 302 documents dans
   `/var/www/cntso/legacy/` (même arborescence ; la règle nginx
   `wp-content/uploads/` les sert déjà). `wget -x -nH -nc` : n'écrase rien.
   Vérifier l'espace disque avant.
2. [x] Ampleur **en prod** : identique à la dev — 205 articles, 256 liens.
3. [x] Commande `repare_liens_fichiers` écrite le 14/09/2026 (simulation par défaut,
   `--appliquer`, `--rapport x.csv`) ; 10 tests, validés par 6 mutations ; suite 1 356 OK.
   Relie en bloc « Fichier à télécharger ». Spécification d'origine : source des liens =
   miroir `old` pour le site principal (href d'origine, sûr) ; sinon nom exact
   unique dans l'inventaire ; tout le reste → liste pour relecture humaine.
   Lien vers un Document Wagtail (médiathèque), pas vers l'ancienne adresse.
4. [ ] **Famille à part, mesurée en dev le 14/09** : 67 liens vers l'ancien site SPIP
   (`http://www.cnt-so.org/Titre-En-Majuscules`, 404) dans 44 articles. À relier par
   titre vers les articles Wagtail — pas dans `repare_liens_fichiers`. Exemple : sur l'article TPE, « Voir notre profession de foi » pointe vers
   une adresse SPIP morte (`/Election-TPE-TPA-2021-profession`, 404) ; l'article
   `election-tpe-tpa-2021-profession-de-foi-de-la-cnt-so` existe.
