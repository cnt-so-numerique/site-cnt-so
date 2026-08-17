# Chantier — flux des sites externes dans le cartouche « réseau »

Ouvert le 17/08/2026.

## Le problème

Un syndicat hébergé ailleurs (champ `external_url` sur sa `SectionPage`) n'a
aucune `ArticlePage` dans notre base. Le cartouche « Les nouvelles du réseau »
de l'accueil, qui pioche dans `ArticlePage`, l'ignore donc structurellement —
alors que c'est le seul endroit de l'accueil où les sous-sites s'expriment.

Concernés aujourd'hui : le STAA (`https://staa-cnt-so.org/`, WordPress, flux
vérifié) et le TAS.

## Le principe retenu

Moissonnage périodique en base, jamais de requête HTTP pendant le rendu : si le
serveur voisin tombe ou rame, c'est l'accueil de la confédération qui tombe ou
rame.

## Étapes

- [x] `SectionPage.feed_url` + état de synchro (`feed_etag`, `feed_last_sync`)
      et `get_feed_url()` (repli WordPress : `external_url` + `/feed/`)
- [x] Modèle `content.ExternalArticle` (titre, lien, guid, date) — surtout pas
      une page Wagtail : le contenu ne nous appartient pas, il n'a rien à faire
      dans l'arbre, la recherche ni le sitemap
- [x] Commande `sync_flux_reseau` (timeout court, erreurs journalisées et
      jamais levées, GET conditionnel par etag, purge au-delà de 20 articles)
- [x] Fusion dans `HomeView` : les articles externes entrent dans le tour de
      table du réseau au même titre que les autres
- [x] Gabarit : lien externe en nouvel onglet, signalé au lecteur
- [x] Tests
- [ ] Cron sur le serveur de production (horaire) — à faire au déploiement

## Revue (17/08/2026)

Fait, 945 tests verts (14 nouveaux).

- `cms/models.py` : `feed_url` (panneau d'édition), `feed_etag` et
  `feed_last_sync` (diagnostic, hors panneaux), `get_feed_url()`.
  `ArticlePage.is_external = False` pour que le gabarit distingue honnêtement
  nos articles de ceux d'ailleurs, sans reposer sur un attribut absent.
- `content/models.py` : `ExternalArticle` — `section`, `guid`, `title`, `url`,
  `published_at`, unicité `(section, guid)`. Expose `section_slug` et
  `get_absolute_url()` : le tour de table du réseau et le gabarit n'ont pas eu
  à changer de logique.
- `content/management/commands/sync_flux_reseau.py` : téléchargement par
  `requests` (timeout 15 s, `If-None-Match`), analyse par `feedparser`,
  `update_or_create` sur le guid, purge au-delà de 20 articles par site. Une
  erreur réseau est journalisée et n'interrompt ni les autres syndicats ni le
  cron : les articles déjà en base restent affichés.
- `content/views.py` : `_candidats_reseau()` fusionne les deux sources et trie
  sur une date commune (`_date_reseau`) avant le tour de table existant.
- `templates/content/home.html` : lien externe en nouvel onglet, marqué d'un ↗
  visible et d'une mention pour lecteurs d'écran.
- `requirements.txt` : `feedparser==6.0.14` (+ `feedparser-sgmllib`).

Vérifié sur le vrai flux du STAA : 10 articles moissonnés, deuxième passage
sans doublon, accueil rendu avec le STAA en tête du cartouche et le tour de
table qui tourne toujours entre syndicats.

## Le TAS (17/08/2026)

`https://www.cnt-tas.org/` — WordPress, flux vérifié, 10 entrées.

À noter pour la suite : **ce site n'est pas CNT-SO**. Il s'intitule « CNT
Travail & Affaires sociales », ne mentionne CNT-SO nulle part et renvoie à
`cnt-f.org` : c'est une fédération de la CNT (Vignoles). Arnaud a tranché le
17/08/2026 pour l'afficher dans le cartouche « réseau » au même titre que les
syndicats CNT-SO, avec son badge et sans mention d'appartenance. Si la
question revient (un lecteur qui prend ces articles pour les nôtres), la
réponse toute prête est un cartouche distinct type « Nos soutiens ».

Section créée en base de développement : slug `tas`, type sectoriel,
`external_url = https://www.cnt-tas.org/`.

## Déploiement (17/08/2026) — fait

`pip install -r requirements.txt`, `migrate`, `fix_cms_sessions` (0 session à
corriger), `collectstatic`, redémarrage supervisor. Accueil en 200, les deux
flux moissonnés (10 + 10 articles), `/staa/` et `/tas/` renvoient bien en 302
vers les sites concernés, le sitemap ne publie aucune URL d'autrui.

Deux découvertes à garder en tête :

**Il n'y a pas de cron sur ce serveur.** Ni binaire `crontab`, ni
`cron.service` — la prod tourne sur des timers systemd (comme certbot). Le
moissonnage est donc un timer, pas une ligne de crontab :

    /etc/systemd/system/cntso-flux.service   (oneshot, User=debian, WorkingDirectory=/var/www/cntso)
    /etc/systemd/system/cntso-flux.timer     (OnCalendar=*:17, Persistent=true)

    systemctl list-timers cntso-flux      # prochaine exécution
    journalctl -u cntso-flux -n 20        # ce qu'a fait la dernière

`Persistent=true` rattrape l'exécution manquée si le serveur redémarre. Minute
17 et non l'heure pile, pour ne pas taper sur les serveurs voisins en même
temps que la moitié du web.

**Ni le STAA ni le TAS n'existaient comme `SectionPage` en production** : ils
n'y étaient que des liens de menu. La
commande `fix_menus_morts` sait créer la section STAA mais n'avait jamais été
lancée en prod. Les deux sections ont été créées à l'identique du dev
(sectoriel, `external_url`, publiées). Créer une `SectionPage` n'ajoute rien
aux menus : la navigation est bâtie sur les `MenuItem`, aucun gabarit ne liste
les sections.

## Reste à faire

- **Le menu `secondary` était rendu nulle part** — `base.html` n'appelle
  `get_menu` que pour `main` et `footer`, et aucun autre gabarit ne l'appelle.
  La prod en portait 10 entrées invisibles sur la conf : « Unions locales »
  (Rhône-Alpes, 13, Auvergne, Poitiers) et « Syndicats sectoriels » (Numérique,
  STAA, Éducation, STUCS), reliquat d'une navigation abandonnée. Elles
  s'éditaient dans `/cms/` sans rien changer au site — de quoi faire perdre
  une demi-journée à un rédacteur.

  **Purgées le 17/08/2026** sur go d'Arnaud, après sauvegarde :
  `/var/www/cntso/logs/menu_secondary_supprime_20260817.json` (restaurable par
  `loaddata`). Les menus visibles n'ont pas bougé : `main` garde ses 7 entrées
  racine, `footer` son « A propos ».

  (J'avais d'abord annoncé « deux entrées STAA en double » : c'était faux, ma
  requête ne filtrait que l'URL. Les deux entrées vivaient dans deux menus
  différents, l'une visible sous « Secteurs », l'autre dans ce menu mort.)

- **Cause refermée le 17/08/2026** : « Menu secondaire » est retiré de
  `MenuItem.MENU_CHOICES` (migration `0032`), le bloc correspondant disparaît
  de l'écran de gestion des menus, et un test relit les gabarits pour vérifier
  que chaque menu proposé aux rédacteurs est bien rendu quelque part. Ne
  rajouter un choix qu'en même temps que le `get_menu` qui l'affiche.
- La base de développement est désynchronisée de la prod (elle a des sections
  `debug-a`, `debug-b`, `test`, et un `legacy_site_slug` sur `staa`/`tas` que
  la prod n'a pas). Sans conséquence ici, mais ne pas s'y fier pour juger de
  l'état réel.

