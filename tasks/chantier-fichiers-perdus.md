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

## Simulation en production (14/09/2026, commit 7e99a60 déployé)

1 397 documents indexés (les 1 302 + 95 du 02/09), miroir présent. **180 pages à
modifier ; 225 liens sur 256 reliés** : 124 d'après le miroir, 101 par nom exact
(10 ne diffèrent que par la casse ou un point final, contrôlés un à un). 196
documents à verser. Rapport : `tasks/donnees/liens-fichiers-simulation-2026-09-14.csv`.

Restent **31 pour relecture humaine** :
- 2 douteux : deux copies différentes (site principal / `sites/2`) —
  `cnt_so_educ_30_10_20.pdf`, `caisse_de_greve_nh-3.pdf` ;
- 29 introuvables, surtout 13 (2014-2020) : 12 ont un nom approchant sur l'ancien
  serveur (ex. `cnt_so_retraites_dec_2019` ~ `…_dec_2019-4.pdf`), 17 rien du tout ;
  ⚠️ `tract_1er_mai.pdf` ~ `Tract-1er-mai-2025.pdf` est un FAUX ami.
- Sur l'article TPE, la profession de foi générale (« Profession de foi - CNT-SO »,
  `cnt_so_tpe_2021_4_p_11112020_-_merged-1.pdf`) n'est pas un nom nu : non traitée.

## Passage réel en production (14/09/2026, 16 h 52)

Sauvegarde préalable : `~/cntso-avant-liens-fichiers-20260914-1652.sql.gz` (12 Mo).
**180 pages modifiées, 225 liens reliés, 196 documents versés** en médiathèque.
Contrôle par nouvelle simulation : 0 page à modifier ; restent les 2 douteux et les
29 introuvables, plus **3 « brouillon en cours »** — déduction : ce sont des liens
de pages **hors ligne**, dont la réparation a été enregistrée en révision sans
publication (le premier passage n'avait compté aucun brouillon).
Contrôle public : article TPE = 8 encadrés « Télécharger », PDF BTP en 200
(675 352 octets, identique à l'original) ; `13.cnt-so.org` et `86.cnt-so.org`
servent aussi leurs PDF en 200.

Retour arrière : révision précédente page par page dans /cms/, ou la sauvegarde.

## Les 8 rapprochements validés à la main (17/09/2026)

Sauvegarde : `~/cntso-avant-fichiers-choisis-20260917-1403.sql.gz`.
`relie_fichiers_choisis --csv tasks/donnees/fichiers-choisis.csv --appliquer` :
**7 pages, 8 liens**, 6 documents versés et 2 réutilisés. Contrôle public : les
encadrés « Télécharger » s'affichent et les PDF se téléchargent (200) sur 13.cnt-so.org.

**Reste 26 cas** (au lieu de 31) : 2 douteux, 21 introuvables, 3 dans des pages à
brouillon. Les 17 sans aucun fichier approchant ne sont pas récupérables ;
`tract_1er_mai.pdf` reste un faux ami à ne PAS relier au tract de 2025.

## Compte STUCS (17/09/2026)

Compte `spectacle` / spectacle@cnt-so.org, groupe `redacteur_stucs`, liste OVH du
syndicat posée à `actu-stucs-cntso` (152 abonnés). Courriel de réinitialisation
envoyé par le formulaire **de Wagtail** (`/cms/password_reset/`).
⚠️ Piège : `PasswordResetForm` de Django échoue ici (`NoReverseMatch:
password_reset_confirm`) — les URLs d'auth de Django ne sont pas branchées, seul
le circuit Wagtail existe. Passer par le formulaire, pas par le formulaire Django.
