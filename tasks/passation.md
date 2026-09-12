# Où en est le chantier — 12/09/2026

Note de passation. **À relire en début de séance.** Remplace celle du 03/09.

## En production, déployé et vérifié

```
HEAD 81b785e · django 6.1.1 · wagtail 7.4.3 LTS · 1294 tests verts
```

### Le contenu est prêt pour la bascule

- **1 811 articles sur 1 854 ont un corps modifiable** (758 le matin du 11/09) :
  954 images versées en médiathèque, chacune dans la collection de son
  syndicat. Restent 21 pages en partie ou en tout en HTML brut : tableaux et
  vidéos, laissés intacts exprès.
- **1 487 « > » parasites retirés** de 262 articles. Ils venaient de la
  réparation du 15/08, dont l'expression laissait le chevron fermant.
- **Deux articles importés** (07/09 conf, 08/09 Éducation) : il n'en manquait
  que deux, pas trente-deux.
- **Quatre articles STUCS rendus à leur syndicat**, plus HISTOROCK après
  abandon de son brouillon.

### Le CMS

- **L'éditeur de pages renvoie vers l'écran « Articles »** pour les articles et
  les pages de contenu : il proposait sinon les 216 rubriques de huit syndicats.
- **L'écran d'édition bascule sur le syndicat de l'objet** si l'utilisateur a le
  droit de le choisir, au lieu d'une 404 muette. Les rédacteurs restent
  cloisonnés.

### La bascule

- **Mode « old » en place** : copie statique complète de l'ancien WordPress
  (1 827 articles sur 1 827, neuf sites, ~4,4 Go), rendue autonome — styles,
  polices et documents rapatriés, `srcset` retirés, adresses réécrites. Servie
  par le vhost `old-cntso`, en `noindex`.
- **HSTS : `includeSubDomains` coupé** avant la bascule (il aurait cassé
  `mail.cnt-so.org` chez tous les visiteurs).
- **`www` → `cnt-so.org`** en 301, chemin conservé.
- **32 fichiers rapatriés** dans `legacy/` : plus aucune adresse de fichier ne
  meurt à la bascule.

## Décisions prises (ne pas les rouvrir)

- **Wagtail 8 : NON** (wagtail-2fa plante, wagtail-seo exige `<8.0`). 7.4 est LTS.
- **Catégories vides : on garde tout.** Taxonomie du 13 : pas des doublons.
- **Déploiement automatique par GitHub Actions : non.** Tests PostgreSQL et
  `pip-audit` hebdomadaire : en place depuis le 03/09.
- **Images des articles : on verse l'original**, pas la réduction WordPress
  (12/09, Arnaud : « j'ai du mal à voir la différence »).
- **Articles STAA et Rhône-Alpes restés sous la conf : on n'y touche pas.**
  Rhône-Alpes est dépublié ; les y ranger les ferait disparaître du public.
- **Sous-site WordPress n° 4 : abandonné** (12/09). Dossier vide, aucune trace.

## Ce qui reste — côté Arnaud

1. DNS : `old.cnt-so.org` → 51.91.242.64 ; TTL de `www` et `educ` à 60 s.
2. Certificat : clé d'API OVH pour une émission en DNS-01 avant la bascule
   (recommandé), ou certbot aussitôt après, avec quelques minutes d'erreur.
3. hCaptcha : comparer le tableau de bord aux onze noms d'hôte, puis un envoi
   d'essai depuis chaque formulaire de syndicat.
4. Nextcloud : sauvegarde des données, et contrôle du renouvellement du
   certificat vers le 1er octobre.

Tout le détail, la séquence du jour J et le retour arrière :
`tasks/chantier-bascule-dns.md`. Le chantier des articles :
`tasks/chantier-articles-modifiables.md`.

## Pièges appris le 11 et le 12/09

- **Un chiffre mesuré en dev n'est pas un fait.** « 1 061 articles en HTML
  brut » venait de la base de développement ; il y en avait 114.
- **Vérifier l'écran que le rédacteur ouvre vraiment** (`/cms/snippets/…`), pas
  un écran voisin qui affiche le même objet.
- **Un test de transformation de texte compare la sortie exacte**, jamais la
  présence de fragments : c'est ainsi que 1 487 « > » sont passés un mois.
- **`systemctl reload nginx` rend la main avant d'avoir rechargé** : un contrôle
  lancé dans la foulée teste encore l'ancienne configuration.
- **`pgrep -f` se détecte lui-même** quand le motif est dans sa propre ligne de
  commande : vérifier par le numéro de processus.
- **gpg-agent ne garde la clé SSH que 30 minutes** : au-delà, il refuse de
  signer sans pouvoir demander la phrase de passe. `ssh debian@… true` dans un
  terminal la redemande.
- **Une copie de site « complète » en nombre de pages peut être inutilisable** :
  `wget` écarte les ressources à `?ver=` si l'on rejette les `?`, et ne suit pas
  `srcset`.
