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

## Reste à faire

1. En production : vérifier que la section `tas` existe et porte bien son
   `external_url` (la base de dev est désynchronisée de la prod).
2. En production : `pip install -r requirements.txt`, `migrate`, puis le cron
   horaire

       17 * * * * cd /var/www/cntso && venv/bin/python manage.py sync_flux_reseau >> /var/log/cntso/flux.log 2>&1

