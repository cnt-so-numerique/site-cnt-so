# Audit de robustesse — 24/09/2026 (refait)

La liste des 20 points de mise en production, repassée de zéro. Cette version
remplace la première du même jour, qui avait conclu trop vite sur trois points
(limite nginx, délai OVH, plafond d'envoi d'images) faute d'avoir lu les
valeurs par défaut des bibliothèques et la configuration serveur.

**Trois sources, chacune citée :**
- **dépôt** — le code et les réglages versionnés ;
- **défaut** — la valeur appliquée par une bibliothèque quand on ne règle rien,
  lue dans le paquet du `venv` ;
- **prod HTTP** — mesuré depuis l'extérieur sur `https://cnt-so.org`
  (GET publics uniquement).

Ce qui vit dans nginx, supervisor ou systemd et ne se voit pas en HTTP est
marqué **(à confirmer en prod)** : voir la séquence de vérification en fin de
document.

`pip-audit` : **aucune vulnérabilité connue** sur `requirements.txt`.

---

## Le trou le plus grave : la newsletter peut partir deux fois (09)

`content/newsletter_views.py:144` vérifie `status == 'sent'`, puis envoie, puis
**seulement à la fin** (`:263`, `:314`) marque la lettre envoyée — sans verrou
ni transaction. Entre les deux passent l'envoi SMTP et les appels
`get_subscribers()` à OVH. Un deuxième clic sur « Envoyer » dans cet
intervalle franchit le même contrôle : **toute la liste reçoit deux fois.**
Le `confirm()` du bouton ne protège pas, il se redemande au second clic.

Déjà relevé le 17/09 (`audit-2026-09-17.md` §3.2, sous l'angle d'un worker
tué en cours d'envoi) ; **toujours ouvert**.

**Branche sans liste OVH — dormante en prod** (vérifié le 24/09 : les 4
sites sans liste ont 0 abonné en base, et les 6 abonnés en base du site
principal passent par sa liste OVH). Le défaut reste dans le code : (`:280-311`) : un `time.sleep(18)` par
destinataire **dans la requête web**. gunicorn tue par défaut un worker muet
au bout de 30 s — **(à confirmer en prod)**, rien dans le dépôt ne règle
`--timeout`. Au-delà de deux destinataires, le worker serait abattu en plein
envoi, le statut resterait `draft`, et un nouvel essai renverrait aux
premiers. En dev, le site principal n'a pas de liste OVH et porte 5 670
abonnés en base : 28 heures dans une seule requête. En prod la conf passe par
OVH ; reste à compter les abonnés en base des sites **sans** liste.

**Correctif** : basculer le statut en `sending` par un `UPDATE … WHERE
status='draft'` atomique avant tout envoi (le second clic trouve 0 ligne et
s'arrête), et sortir la boucle lente de la requête web.

---

## Tableau d'ensemble

| # | Point | État | Source |
|---|---|---|---|
| 01 | Limite par visiteur | Partiel | dépôt + mémoire prod 18/09 |
| 02 | Plafond d'appels d'API | Fait | dépôt |
| 03 | Plafond de dépenses | Sans objet | — |
| 04 | Message quand ça plante | Partiel | dépôt |
| 05 | Chargement plutôt qu'écran blanc | Sans objet | dépôt |
| 06 | Rien à afficher | Fait | dépôt |
| 07 | Requêtes qui échouent | Presque fait | dépôt |
| 08 | API qui ne répondent pas | Partiel | dépôt + défauts |
| 09 | Double clic sur « envoyer » | **Manque grave** | dépôt |
| 10 | Double paiement | Sans objet ici | — |
| 11 | Ne charger que l'affiché | Fait | mesuré en dev |
| 12 | Index | Fait | dépôt |
| 13 | Pagination | Fait | dépôt |
| 14 | Compression | Partiel | prod HTTP |
| 15 | Poids des fichiers envoyés | **Plafond de 1 Mo** (nginx) | prod SSH |
| 16 | Cache de ce qui ne change pas | Refus délibéré | dépôt |
| 17 | Alerte si le site tombe | Fait en interne, **sonde extérieure manquante** | prod SSH |
| 18 | Trace de chaque erreur | Fait | dépôt |
| 19 | Test à plusieurs visiteurs | Manque | dépôt |
| 20 | Sauvegarde restaurable | Fraîcheur surveillée, **restauration périmée** | docs + prod SSH |

---

## Détail

### 01 — Limite par visiteur : partiel
- **Connexion `/cms/` et `/admin/`** : nginx, `limit_req` 5/min par IP,
  `burst=5 nodelay`, réponse `429`, sur `$binary_remote_addr` donc non
  falsifiable (`conf.d/limitation-connexion.conf`, mesuré en prod le 18/09).
- **Newsletter** : 3 inscriptions et 20 désabonnements par heure et par IP,
  sur un `DatabaseCache` partagé entre les workers, IP lue au **dernier**
  élément de `X-Forwarded-For`.
- **À découvert** : le formulaire de contact (hCaptcha seul) et la
  **recherche**, la page la plus coûteuse du site (1,4 s en dev sous SQLite ;
  0,56 s en prod, trajet réseau compris). Aucune limite par IP.
- Pas de verrouillage **par compte** après N échecs : la limite nginx ne voit
  pas une attaque répartie sur plusieurs adresses.

### 02 — Plafond d'appels d'API : fait
`NEWSLETTER_SEND_DELAY = 18` s (200 envois/h), cache de 5 min sur les listes
et les abonnés OVH, `sleep(0.2)` dans les imports. Aucune API n'est appelée
en boucle depuis une page publique.

### 03 — Plafond de dépenses : sans objet
Aucune API payante dans ce dépôt. OVH (listes) est compris dans
l'abonnement, et hCaptcha est gratuit dans l'offre utilisée.

### 04 — Message quand ça plante : partiel
- **Pas de `500.html`**, nulle part. Avec `DEBUG = False`, Django sert alors
  une page nue « Server Error (500) », sans menu ni lien de retour.
- `404.html` existe.
- Échecs d'envoi (contact, newsletter) : le visiteur n'est pas bloqué, le
  message reste dans `/cms/`, et l'échec est journalisé avec sa cause.

### 05 — Chargement plutôt qu'écran blanc : sans objet
Tout est rendu côté serveur. Un seul `fetch` dans tout le projet, côté admin
(voir 07).

### 06 — Rien à afficher : fait
16 `{% empty %}` et 21 gabarits portant un message « Aucun… ».

### 07 — Requêtes qui échouent : presque fait
- **Chaque** appel OVH est enveloppé côté appelant (`api_views`,
  `wagtail_hooks`, `ovh_sync`) ; une panne est rapportée, pas levée.
- `sync_flux_reseau` : `raise_for_status()`, délai de 15 s, flux illisible
  journalisé et sauté.
- **Exception** : le réordonnancement des menus
  (`templates/cms/menus/menu_tree.html:178`) envoie son `fetch` **sans lire la
  réponse**. Session expirée, 403 ou 500 : le rédacteur voit son menu
  réordonné et croit l'avoir enregistré. Il le découvre au rechargement.

### 08 — API qui ne répondent pas : partiel
| Appel | Délai | Source |
|---|---|---|
| hCaptcha | 5 s | défaut `django-hCaptcha` |
| Flux réseau | 15 s | dépôt |
| OVH (listes) | **180 s** | défaut `python-ovh` |
| SMTP (contact, newsletter) | **aucun** | défaut Django `EMAIL_TIMEOUT = None` |

Deux délais trop longs pour une requête web : un OVH lent ou un SMTP muet
occupe un worker sur trois jusqu'à ce que gunicorn l'abatte. `EMAIL_TIMEOUT`
n'est réglé ni dans `settings.py` ni dans le `local_settings.py` de prod
(vérifié le 24/09) : **aucun délai**, gunicorn abat le worker à 30 s.

### 09 — Double clic : manque grave
Voir en tête pour la newsletter. Sur le **formulaire de contact**, le motif
POST → redirection empêche le renvoi par actualisation, mais aucun bouton
n'est désactivé à l'envoi : un double clic crée deux messages et deux
courriels. Gênant, pas grave.

### 10 — Double paiement : sans objet ici
Aucun paiement dans ce dépôt. Le don de la souscription part vers une
plateforme externe (`we-solidaire.com`, `SouscriptionView.URL_DON`) ;
l'adhésion, vers cnt-adhesion. Le double paiement se joue chez eux.

### 11 — Ne charger que l'affiché : fait (mesuré)
Pages de la base de dev, requêtes SQL par page :

| Page | Requêtes | Temps |
|---|---|---|
| Accueil | 37 | 331 ms (1er appel) |
| Article | 37 | 134 ms |
| Catégorie | 26 | 129 ms |
| Accueil de sous-site | 24 à 33 | 119 à 194 ms |
| Agenda | 33 | 126 ms |
| Recherche | 18 | **1 429 ms** |

Aucun N+1 : un défaut de ce type donnerait des centaines de requêtes. La
recherche est lente par le moteur (`database` sous SQLite), pas par le nombre
de requêtes ; en prod, sous PostgreSQL, elle répond en 0,56 s.

### 12 — Index : fait
`section_slug` indexé sur `ArticlePage`, `ContentPage` et `CmsCategory` ;
`slug` l'est par Wagtail ; `unique_together` sur les couples site + slug. Ce
sont bien les colonnes filtrées (19 `slug=`, 14 `section_slug`). Volume :
1 710 articles, 1 802 pages — rien qui justifie davantage.

### 13 — Pagination : fait
`paginate_by = 10` sur les 8 vues de liste, recherche comprise.

### 14 — Compression : partiel (mesuré en prod)
- **HTML : compressé** par nginx (gzip, 37 Ko transférés pour l'accueil).
- **Statiques : ni compression ni `Cache-Control`** — cause trouvée : dans
  nginx, `gzip on` mais `gzip_types` **commenté**, donc seul le HTML est
  compressé ; les blocs `location /static/` n'ont pas d'`expires`., alors que leurs noms
  portent une empreinte (`carrousel-auto.244f4cb7a86b.js`) qui autoriserait
  un cache d'un an. Faible enjeu : quelques Ko.
- **Images : le vrai poids.** L'accueil sert **11 images, 3 Mo, toutes des
  originaux** (`/media/original_images/…`, aucune miniature Wagtail), dont
  deux à 743 et 940 Ko. Même motif `{% image … original %}` sur les pages
  d'article et de contenu. C'est de loin le gain le plus net de la liste.

### 15 — Poids des fichiers envoyés : partiel
- **Images** : Wagtail plafonne à **10 Mo** et 128 mégapixels par défaut.
- **Documents** : aucun plafond applicatif (`WAGTAILDOCS_MAX_UPLOAD_SIZE`
  vaut `None`).
- **Formulaires publics** : aucun champ fichier.
- **nginx : aucun `client_max_body_size`** (vérifié par `nginx -T` le 24/09),
  donc la valeur par défaut de **1 Mo** s'applique à tout le site, `/cms/`
  compris. C'est elle qui borne en pratique : le plafond de 10 Mo de Wagtail
  n'est jamais atteint. **Une photo de téléphone (3 à 5 Mo) ou un tract PDF de
  plus d'1 Mo déposé depuis `/cms/` est refusé par nginx en `413`**, avant
  Django, donc sans message d'erreur Wagtail lisible. **Déjà arrivé : 3 refus
  `413` dans les journaux d'accès conservés** (24/09).

### 16 — Cache de ce qui ne change pas : refus délibéré
Pas de cache de pages : décision documentée le 27/08 dans `settings.py`
(cache mémoire × 3 workers = purge incohérente ; pages déjà rendues en
30 à 70 ms en prod). Cache de 5 min sur les appels OVH.

### 17 — Alerte si le site tombe : fait en interne, sonde extérieure manquante
`verifier-sites.timer` (toutes les 10 min, `/usr/local/bin/verifier-sites.sh`)
vérifie que les sites répondent en 200, que les services supervisor tournent,
que le disque reste sous 85 % et qu'une sauvegarde PostgreSQL de moins de
2 jours existe. Il n'écrit qu'en cas de problème, et une seule fois par
problème (`alerter.py`). Bien conçu.

Deux trous :
- **Il sonde `newsite.cnt-so.org`, pas `cnt-so.org`** ni les domaines des
  fédérations. Depuis la bascule du 12/09, c'est `cnt-so.org` que lisent les
  visiteurs, et il a son propre bloc serveur et son propre certificat. Or
  c'est précisément là que certbot avait laissé un 404 sur le domaine
  principal : le cas qui a déjà eu lieu est celui que la sonde ne voit pas.
- **Il tourne sur la machine qu'il surveille** — limite écrite dans le script
  lui-même. Serveur éteint, réseau coupé, OVH en panne : silence. Seule une
  sonde **extérieure** couvre ce cas.

### 18 — Trace de chaque erreur : fait
`LOGGING` explicite, fichier tournant 5 Mo × 3, et toute 500 part par courriel
via `cntso.alertes.AlerteLimitee` (une par heure et par signature). `ADMINS`
rejette les entrées sans adresse.

### 19 — Test à plusieurs visiteurs : manque
1 468 tests fonctionnels, aucun test de charge. Avec trois workers et une
recherche à 0,5 s, une dizaine de recherches simultanées suffirait à faire
attendre tout le monde — hypothèse à mesurer, pas un constat.

### 20 — Sauvegarde restaurable : fraîcheur surveillée, restauration périmée
Depuis l'audit du 17/09, `verifier-sites.sh` alerte si aucune sauvegarde de
moins de 2 jours n'existe : la chaîne ne peut plus s'arrêter en silence. Il
vérifie qu'un fichier existe, pas qu'il se restaure.
La chaîne est bien conçue (le NAS tire, secrets chiffrés, rétention 60 j),
mais le **dernier test de restauration date du 12/07/2026** : avant le
cluster PostgreSQL dédié (`:5433`), avant la bascule DNS du 12/09 et avant
tout le chantier de contenu de septembre. L'audit du 17/09 le signalait
déjà. Et la surveillance de la chaîne est notée « optionnelle » dans
`docs/sauvegarde-nas.md`.

---

## Ordre proposé

1. **Newsletter en double (09)** — statut basculé atomiquement avant envoi.
   Le seul défaut qui touche des milliers de personnes d'un coup.
2. **`client_max_body_size` (15)** — une ligne dans nginx ; les rédacteurs
   s'y heurtent déjà (3 refus relevés).
3. **Test de restauration (20)** — le seul dont l'échec serait définitif.
4. **Sondes (17)** — ajouter `cnt-so.org` à `verifier-sites.sh`, et une sonde
   extérieure pour le cas « serveur muet ».
5. **Images de l'accueil et des articles (14)** — miniatures au lieu des
   originaux : 3 Mo en jeu sur la page la plus vue. Au passage, `gzip_types`
   et `expires` sur `/static/`.
6. **Petites corrections groupées** : `500.html` (04), `EMAIL_TIMEOUT` et délai
   OVH courts (08), `fetch` des menus qui lit sa réponse (07), bouton
   désactivé à l'envoi (09), limite par IP sur contact et recherche (01).

## Vérifié en prod le 24/09 (SSH, lecture seule)

- **gunicorn** : `--workers 3`, **pas de `--timeout`** → 30 s. Confirmé.
- **`EMAIL_TIMEOUT`** absent de `local_settings.py` → aucun délai SMTP. Confirmé.
- **nginx** : `limit_req` 5/min sur la connexion, confirmé ; `gzip_types`
  commenté ; **aucun `client_max_body_size`** (1 Mo par défaut).
- **Minuteurs** : `pg-backup` a tourné à 01h30 ; `cntso-flux` toutes les
  heures ; et deux sondes **dont le rôle reste à lire** : `verifier-sites.timer`
  (toutes les 10 min) et `sante-adhesion.timer` (toutes les 15 min). Si
  `verifier-sites` sonde les domaines et alerte, le point 17 est **en partie**
  couvert — en partie seulement, puisqu'une sonde logée sur le serveur se tait
  avec lui.
- **Abonnés en base par site** : **échec**, `www-data` ne peut pas lire
  `local_settings.py`. Pas de variante improvisée.

## Vérifié en prod le 24/09, second passage

- `verifier-sites` : sonde interne sérieuse (voir 17) ; ne vise pas `cnt-so.org`.
- **3 refus `413`** dans les journaux nginx conservés (voir 15).
- Abonnés en base : aucun site sans liste OVH n'en a (voir 09). Les listes
  OVH sont désormais renseignées sur **10 sites sur 14**.

Plus rien à vérifier en prod pour cet audit.

## Suite du 24/09 — fait dans le dépôt (non déployé)

- **01** : le formulaire de contact est limité à 5 messages/h/IP (`CONTACT_MAX_PAR_IP`),
  sur le même compteur partagé que la newsletter (`_quota_epuise`, factorisé).
  Seuls les envois valides comptent. Réponse 429 avec un message.
- **04** : `templates/500.html`, autonome (aucune balise maison, aucune requête).
- **08** : délai OVH explicite `(5, 10)` dans `cms/ovh_client.py`.
- **09** : blocage du second envoi dans `base.html`, pour tous les formulaires
  POST publics (vérifié dans Chrome : 3 envois → 1 parti).
  **Trouvé en passant, plus grave** : l'envoi de la newsletter pouvait partir
  **deux fois**. Le statut « envoyée » n'était posé qu'après l'envoi, donc
  deux clics servis par deux workers voyaient chacun un brouillon. L'envoi est
  désormais réservé avant le premier courriel (statut `sending`, `UPDATE`
  conditionnel), et la lettre redevient brouillon si rien n'est parti.
  Migration `content/0037`.
- Tests : 8 nouveaux, chacun validé par mutation. Suite : 1 487 verts.

## Constats en prod (lecture du 24/09)

- **15** : aucun `client_max_body_size` → nginx plafonne **tout** envoi à 1 Mo,
  `/cms/` compris. Aucun formulaire public n'accepte de fichier : ce n'est pas un
  trou de sécurité, c'est une gêne probable pour les rédacteurs (affiches, PDF).
- **14** : `gzip on` mais `gzip_types` commenté → seul le HTML est compressé.
- **17** : un `verifier-sites.timer` tourne toutes les 10 min **sur le serveur
  lui-même**. À lire avant de conclure ; s'il sonde la disponibilité, il tombe
  avec la machine et ne peut pas signaler une panne du serveur.

## Appliqué en prod le 24/09

- Déploiement `6d3e89c` : migration `content/0037` appliquée, 7 pages de contrôle OK.
- nginx, `/etc/nginx/conf.d/robustesse.conf` (retrait = supprimer le fichier) :
  `client_max_body_size 20m` et `gzip_types`. Mesuré de l'extérieur : un POST de
  5 Mo sur `/cms/` atteint Django (403 CSRF, plus de 413) ; 25 Mo reste en 413 ;
  le JS statique part en `Content-Encoding: gzip`.
- `verifier-sites.sh` sonde désormais `https://cnt-so.org/` (copie
  `.bak-20260924`). Reste la sonde **extérieure**.

## 19 — Test de charge (24/09, en prod, depuis le poste d'Arnaud)

`ab`, requêtes GET seules, paliers de 20 s, User-Agent `cnt-test-de-charge`.
**Zéro erreur à tous les paliers.**

| Page | Simultanés | req/s | médiane | p95 |
|---|---|---|---|---|
| Accueil | 1 | 1,4 | 753 ms | 797 ms |
| Accueil | 5 | 8,3 | 565 ms | 751 ms |
| Accueil | 10 | 8,7 | 1,1 s | 1,2 s |
| Accueil | 25 | 8,5 | 2,8 s | 3,0 s |
| Accueil | 50 | 8,8 | 5,3 s | 5,6 s |
| Article | 25 | 14,1 | 1,7 s | 1,8 s |
| CSS statique (nginx) | 50 | 167 | 148 ms | 1,2 s |

**Lecture.** Le goulot est Django : **3 workers gunicorn synchrones**, soit
environ 8,5 accueils/s au maximum. Au-delà de 5 visiteurs simultanés, les
requêtes font la queue : le temps de réponse croît en ligne droite, mais rien ne
casse (pas de 502 ni de 504 à 50 simultanés). Le statique est servi par nginx
(`alias`) ; son plafond à 167/s tient surtout au poste de test (une poignée de
main TLS par requête, sans keep-alive).

**Ordre de grandeur réel** : ~615 requêtes/jour. Un envoi de newsletter à 5 900
personnes ou un partage viral donne quelques requêtes/s au pic : dans la marge,
mais avec 2 à 5 s d'attente si 25 à 50 personnes arrivent en même temps.

**Pistes, par coût croissant :**
1. `--workers 9` (8 cœurs, 32 Go, ~150 Mo par worker) : débit ×3 attendu, une
   ligne dans la config supervisor. À mesurer après coup avec le même protocole.
2. `expires 1y` sur `/static/` : les noms portent une empreinte, donc aucun
   risque de servir un fichier périmé, et les visites suivantes ne redemandent
   plus rien.
3. Accueil à 0,55 s de calcul, dont 223 ms de SQL : `EXPLAIN ANALYZE` des
   requêtes sur ArticlePage.

⚠️ Les ~3 500 requêtes du test apparaissent dans les statistiques GoAccess
pendant 14 jours (User-Agent `cnt-test-de-charge`, un seul « visiteur »).
