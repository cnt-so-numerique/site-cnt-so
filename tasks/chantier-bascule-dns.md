# Bascule DNS de cnt-so.org — et l'ancien site conservé en « old »

Écrit le 10/09/2026. Tout ce qui suit a été **mesuré**, pas supposé.
Complète `!DEPLOIEMENT.md` (section « Bascule DNS »), qui reste la référence
pour les commandes serveur.

## État constaté le 10/09/2026

```
cnt-so.org        → 5.196.74.69   200   ← l'ancien WordPress est REVENU
educ.cnt-so.org   → 5.196.74.69   200   ← idem
www.cnt-so.org    → 5.196.74.69   000   DNS existe, mais aucun vhost ne répond
newsite.cnt-so.org→ 51.91.242.64  200   CSP + HSTS présents = HEAD fa4763d déployé
/wp-login.php · /wp-json/          200   PHP et MySQL sont repartis
SSH 22 sur 5.196.74.69             refusé ← toujours aucun accès à la machine
certificat de 5.196.74.69          CN=cnt-so.org, SAN = cnt-so.org SEUL, exp. 19/10/2026
```

Deux faits changent le plan par rapport à la note du 02/09 :

1. **On publie encore sur l'ancien WordPress** : un article le 07/09 (conf),
   un le 08/09 (Éducation). Tant que ça dure, chaque jour creuse l'écart.
2. ~~Il reste ~32 articles absents du nouveau site~~ — **faux, corrigé le
   11/09** : il n'en manquait que deux (07/09 conf, 08/09 Éducation), importés
   ce jour-là. Ma comparaison ratait les slugs normalisés par l'import.

3. **32 adresses de fichiers mourront à la bascule** (remesuré le 11/09, tous
   hôtes `*.cnt-so.org`, après le passage de `normalise_urls_heritees`) : 351
   adresses absolues restent dans les corps, 319 sont couvertes par les 346
   fichiers rapatriés le 02/09 et resteront servies par nginx, **32 ne le sont
   pas** — 30 de 2026 —, sur 24 pages en ligne. Un échantillon de 15 répond
   encore chez l'ancien hébergeur : elles sont récupérables.

---

## ✅ BASCULE FAITE LE 12/09/2026

`cnt-so.org` et `educ.cnt-so.org` servent le nouveau site. Déroulé réel :
sauvegarde (12 Mo), import de rattrapage à blanc (**0 créé, 700 + 102
existants** — rien à rattraper), bascule des deux A par Arnaud, certbot sur les
douze noms, adresse canonique Django, domaine autonome de l'Éducation.

Vérifié après coup : apex et `educ` en **200**, `http://` redirigé en 301 vers
HTTPS, `www` → apex, archive `old` en 302 vers le miroir avec `noindex`,
`/cms/` qui renvoie à sa page de connexion, HSTS `max-age=31536000` **seul**,
sitemap **733 entrées toutes en `https://cnt-so.org`**, accueil peuplé
(40 liens d'article), fichiers hérités `/13/wp-content/uploads/…` servis en 200
jusqu'à 2,3 Mo.

### Le piège qui a fait une vraie panne

**certbot n'a jamais posé les redirections HTTP→HTTPS de l'apex ni d'`educ`.**
Il avorte sa phase d'*enhancement* dès le premier conflit — le nôtre sur `www`
— et n'ajoute donc AUCUNE des redirections suivantes. Le bloc port 80 se
terminant par `return 404`, `http://cnt-so.org` a répondu **404 aux visiteurs**
pendant quelques minutes, alors même que `https://` fonctionnait.

Remède appliqué : ajouter à la main, dans le bloc port 80 de
`sites-enabled/cntso`, les deux `if ($host = …) { return 301 https://$host$request_uri; }`.
**À refaire si certbot est relancé** — il les effacera peut-être.

Et le piège connu a resservi : `systemctl reload nginx` rend la main **avant**
que la configuration soit reprise. La vérification immédiate montrait encore
404 ; une minute plus tard, 301. Ne jamais conclure sur un contrôle joué dans
la foulée du rechargement.

### Deux vérifications de cette note étaient fausses

- `curl … sitemap.xml | grep -c "<loc>"` compte des **lignes**, or le XML tient
  sur quelques lignes très longues : il renvoie `1`. Compter les occurrences :
  `grep -o '<loc>' | wc -l` → **733** attendues.
- `curl … old.cnt-so.org/ | grep -c 'old.cnt-so.org'` attendait `> 0` : le
  miroir utilise des liens **relatifs** (`href="category/…/index.html"`), donc
  `0` est le bon résultat. Les 7 seules adresses absolues restantes sont de la
  tuyauterie WordPress (`/feed/`, `/wp-json/`, `xmlrpc.php`) dans l'en-tête,
  qu'aucun lecteur ne clique.

### Reste à faire

- **hCaptcha** : ajouter `cnt-so.org`, `www.cnt-so.org`, `educ.cnt-so.org` aux
  noms d'hôtes autorisés. La clé servie est bien la clé de production, mais un
  hôte non déclaré fait échouer l'envoi **en silence** — seul un envoi réel le
  révèle.
- Prévenir les six titulaires de compte de passer par « Mot de passe oublié ? ».
- `sites-available/cntso`, périmé, à supprimer ou resynchroniser.

## Ce qui reste à faire

### A. Contenu — à finir avant la bascule

- [ ] **Import de rattrapage final**, au plus près du jour J :
      ```bash
      python manage.py import_from_wp_api --url https://cnt-so.org \
             --section principal --tous-syndicats --dry-run
      python manage.py import_from_wp_api --url https://educ.cnt-so.org \
             --section education --tous-syndicats --dry-run
      python manage.py normalise_urls_heritees --dry-run
      python manage.py repare_entites_html --dry-run
      ```
      (puis sans `--dry-run`). `--tous-syndicats` est obligatoire : sans lui,
      30 relais du site confédéral se dupliquent sous « principal ».
- [x] **32 fichiers rapatriés le 11/09/2026** dans `/var/www/cntso/legacy/`,
      même arborescence (30 PDF et visuels de 2026, 2 du 13), sans écraser
      aucun fichier : **32/32 servis en 200** par le nouveau serveur. Plus
      aucune adresse de fichier ne mourra à la bascule.
- [x] **Gel éditorial** (confirmé par Arnaud le 11/09 ; dernière publication
      sur l'ancien WordPress le 08/09, importée — **à revérifier le jour J**) : prévenir les syndicats que l'ancien WordPress ne doit
      plus recevoir de publication à partir d'une date annoncée. Sans ce gel,
      un article publié après le dernier import est perdu pour le public le
      jour où le nom bascule.

### B. Le mode « old » — à préparer avant de toucher au DNS

Voir la section dédiée ci-dessous. À faire dans cet ordre : miroir statique
d'abord (assurance), vhost `old.` ensuite.

### C. Bascule elle-même — le jour J

Séquence détaillée ci-dessous.

### D. Non bloquant, à faire après

- [x] (fait le 03/09/2026, vérifié le 12/09 : `.github/workflows/tests.yml`,
      PostgreSQL 16 et `pip-audit` chaque lundi) GitHub Actions : suite de tests sur **PostgreSQL** + `pip-audit`
      hebdomadaire (la prod est sur PostgreSQL, les tests sur SQLite).
- [x] **FAIT le 12/09/2026** — détail dans `chantier-categories-lancement.md`
      §§ 7-8 : « Premiere Page » (résidu WordPress porté par 91 articles)
      retirée puis supprimée, 23 articles rangés dans les rubriques que le menu
      nommait déjà, quatre rubriques de lutte créées et remplies (Austérité et
      budget 15, Militarisation – SNU 7, Féminisme 6, Antifascisme et
      antiracisme 3), et **neuf entrées de menu** visent désormais une
      **clé de rubrique** au lieu d'une adresse tapée. Restent les deux liens
      morts et la faute « dégré » dans deux noms de rubriques.

      Le constat d'origine, conservé parce qu'il dit pourquoi le travail était
      un reclassement et non une réparation de liens :

      **Menu de l'Éducation — mesuré le 12/09/2026**, mes chiffres précédents
      étaient faux (« 25 entrées, trois sans cible ») :
      - **37 entrées, dont 36 tapées à la main** (une adresse au clavier plutôt
        qu'une rubrique désignée). Le 13 n'en a qu'une sur 55 ; le STUCS, 10
        sur 10 ; le Numérique, 6 sur 8 ;
      - **deux vrais liens morts** seulement : « Textes officiels » et
        « Supérieur – Recherche » (`#`, sans enfant). Les huit autres `#` sont
        des **en-têtes de sous-menu** — légitimes ;
      - **le vrai défaut** : sept entrées de rubrique mènent à **un seul
        article**, souvent ancien — « 1er degré » → droits syndicaux,
        « 2nd degré » → grilles de salaires, « Primaire » → une motion du 13,
        « Secondaire », « Supérieur », « Vie scolaire – AESH », « Pédagogie ».
        Le visiteur attend une liste, il reçoit un texte daté.
      - **et surtout, les rubriques visées sont vides.** Neuf des onze
        intitulés ont bien une rubrique du même nom (« 1er dégré »,
        « Primaire », « Supérieur », « Vie scolaire - AESH »…), mais
        **83 des 102 articles de l'Éducation ne portent que « Premiere Page »
        et/ou « Actualités - Luttes »**. Faire pointer le menu vers ces
        rubriques donnerait des pages à un ou deux articles.

      Le travail n'est donc pas de réparer des liens, mais de **reclasser les
      articles** — décision éditoriale du syndicat. Ensuite seulement, désigner
      les rubriques dans le menu au lieu d'écrire des adresses. Restent deux
      intitulés sans rubrique : « Textes officiels » et « Supérieur – Recherche »,
      à créer ou à retirer.

      Aide possible : proposer un classement à partir des titres, à valider
      article par article avant d'être appliqué.

      *Ce qui a été fait ensuite, et ce que ça a appris :* le classement par
      mots-clés **proposait** mais ne **classait** pas — il donnait quatre
      articles « antifascistes » en ramassant « réactionnaire » et « répression
      antisyndicale ». La relecture titre par titre en a laissé un seul, d'où
      une rubrique renommée « Antifascisme et antiracisme » pour décrire ce
      qu'elle contient vraiment. Et 60 articles sont restés dans le seul fil
      d'actualité, à raison : ce sont des appels à la grève.
- [ ] `cntso/middleware.py:85` : la double barre oblique (`//13/…`) construit un
      hôte inexistant. Sans objet depuis que nginx sert `/wp-content/uploads/`,
      mais cinq lignes et un test d'hygiène.
- [x] (11/09/2026, vérifiée) Redirection `www.cnt-so.org` → `cnt-so.org` en 301 dans nginx (aujourd'hui
      les deux noms serviraient le même contenu).

---

## Articles d'autres syndicats restés sous la conf (mesuré le 11/09/2026)

Articles du site confédéral portant la catégorie WordPress d'un autre syndicat.
Ceux du STUCS lui ont été rendus (`rend_au_syndicat`). Pour les autres,
**recommandation : ne rien déplacer.**

- **STAA** (catégorie 168) : 3 sous la conf — lancement du syndicat (2020),
  festival BD d'Angoulême (2021), continuité de revenus des artistes-auteurs
  (2023). Le STAA a son propre site (flux « réseau », `sync_flux_reseau`) et sa
  section chez nous est vide.
- **Rhône-Alpes** (catégorie 151) : 11 sous la conf. Le syndicat est
  **dépublié** : y ranger ses articles les ferait disparaître du public
  (`ContenuDeSyndicatMixin`) et les rendrait inouvrables à l'édition (le
  sélecteur ne propose que les syndicats en ligne). À reconsidérer s'il est
  republié.

## Le mode « old » : pourquoi le réflexe évident ne marche pas

> **Mis à jour le 11/09/2026 — le relais décrit plus bas est impossible** : le
> nginx du serveur est compilé sans `http_sub_module` (`nginx -V`). Ce qui
> était « l'assurance » est devenu la solution : une copie statique, en place.

### La copie statique, faite le 11/09/2026

- `/var/www/cntso/archive-wp/`, environ 4,4 Go, prise pendant que l'ancienne
  machine répondait : **1 827 articles sur 1 827** des neuf sites de l'ancien
  WordPress — conf 700, 13 525, Auvergne 261, Poitiers 193, educ 102,
  Rhône-Alpes 32, STAA 10, Éducation 3, Numérique 1. Auvergne, Rhône-Alpes,
  STAA, Éducation et Numérique n'étaient reliés par aucun lien : ils ont dû
  être copiés un par un, et le contrôle article par article l'a révélé.
- **Rendue autonome** par une passe de finition : 565 feuilles de style,
  scripts, polices, images et documents rapatriés, adresses absolues
  réécrites vers la copie, **26 575 attributs `srcset` retirés**. Sans elle,
  après la bascule, les styles auraient été cherchés sur le nouveau serveur
  (écartés à la copie à cause de leur `?ver=`), et les images en tailles
  alternatives auraient cassé — un navigateur qui choisit une taille de
  `srcset` ne se rabat pas sur `src`.
- Contrôle final : 0 article manquant, 0 `srcset`, toutes les feuilles de
  style servies en local sur les sept accueils testés par `old.`.
- Laissés hors de la copie, volontairement : flux RSS, API, pages d'auteurs
  et d'étiquettes, 636 pages de pièces jointes (l'image, elle, est copiée),
  et environ 300 liens déjà morts sur l'ancien site lui-même.
- Vhost `/etc/nginx/sites-available/old-cntso` : `old.cnt-so.org/` renvoie
  vers `/cnt-so.org/`, en-tête `X-Robots-Tag: noindex`, `robots.txt` qui
  interdit tout.
- **Sous-site n° 4 : abandonné, décision d'Arnaud le 12/09/2026** (« si tu as
  tout récupéré, on s'en fout de ce sous-site »). Un huitième dossier existe
  bien sur l'ancien serveur (`uploads/sites/4/`, qui répond 403 quand un
  dossier absent répond 500), mais il est **vide** — aucune année, donc aucune
  image publiée —, il n'a laissé aucune trace en base ni dans la copie, et
  soixante noms essayés n'ont rien donné. On ne peut prouver qu'il n'avait
  aucun texte ; seule la table `wp_blogs` de l'ancien WordPress le dirait.
  **Ne pas rouvrir le sujet.**
- Outils relançables : `tasks/outils/copie-ancien-wp/` (finition, contrôle).
  Sauvegardes des pages avant chaque finition : `~/archive-wp-html-avant-finition-*.tgz`.

**Reste** : l'enregistrement DNS `old.cnt-so.org` → 51.91.242.64 (chez OVH) ;
son HTTPS le jour J, `old.cnt-so.org` figurant déjà dans la commande certbot.
La copie est figée au 11/09 : si l'ancien WordPress publiait encore, la
reprendre.


Le réflexe est de créer `old.cnt-so.org → 5.196.74.69` et de renvoyer les gens
dessus. **Mesuré : ça donne une page blanche.**

```
Host: cnt-so.org       → 5.196.74.69   301 vers https://cnt-so.org/   (normal)
Host: old.cnt-so.org   → 5.196.74.69   200 · corps VIDE · 0 octet
```

WordPress est en multisite : il route sur le **nom d'hôte**. Un nom qu'il ne
connaît pas ne correspond à aucun blog, il ne sert rien. Et on ne peut pas le
lui apprendre : SSH est refusé sur cette machine, on ne peut toucher ni Apache,
ni la table `wp_blogs`, ni installer un certificat — le sien ne couvre que
`cnt-so.org`, donc `https://old.cnt-so.org` afficherait en plus une alerte de
sécurité.

### La solution : `old.` est servi par le NOUVEAU serveur, qui relaie

`old.cnt-so.org` pointe sur **51.91.242.64**. nginx y répond avec notre propre
certificat, relaie vers l'ancienne machine en se présentant comme
`cnt-so.org` — le seul nom qu'elle sache servir — et réécrit les adresses
absolues dans la page pour que la navigation reste sur `old.`.

Aucun accès à l'ancienne machine n'est nécessaire. Rien n'y est modifié.

**Prérequis à vérifier avant** (le module de réécriture n'est pas dans toutes
les compilations de nginx) :
```bash
nginx -V 2>&1 | grep -o with-http_sub_module || echo "ABSENT → passer au miroir statique"
```

Nouveau fichier `/etc/nginx/sites-available/old-cntso` (bloc **séparé** : il ne
doit pas hériter de la règle `location ~ wp-content/uploads/` du vhost cntso,
qui sert les fichiers rapatriés en local) :

```nginx
server {
    listen 80;
    server_name old.cnt-so.org old-educ.cnt-so.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name old.cnt-so.org;
    # ssl_certificate … : ajouté par certbot à l'étape 5 du jour J

    # L'archive ne doit pas concurrencer le nouveau site dans les moteurs
    add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    location = /robots.txt { return 200 "User-agent: *\nDisallow: /\n"; }

    location / {
        proxy_pass https://5.196.74.69;
        proxy_set_header Host cnt-so.org;      # le seul nom qu'Apache sache servir
        proxy_ssl_server_name on;
        proxy_ssl_name cnt-so.org;
        proxy_set_header Accept-Encoding "";   # sans ça, sub_filter ne voit rien
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # WordPress renvoie des adresses absolues : on les ramène sur « old. »
        proxy_redirect https://cnt-so.org/ https://old.cnt-so.org/;
        sub_filter_once off;
        sub_filter_types text/html text/css application/javascript application/json;
        sub_filter "https://cnt-so.org" "https://old.cnt-so.org";
        sub_filter "http://cnt-so.org"  "https://old.cnt-so.org";
        sub_filter "https:\/\/cnt-so.org" "https:\/\/old.cnt-so.org";  # JSON échappé
    }
}
```

`old-educ.cnt-so.org` se fait à l'identique, avec `proxy_set_header Host
educ.cnt-so.org` et les `sub_filter` correspondants. Le certificat de
l'ancienne machine ne couvre pas ce nom, mais nginx ne vérifie pas le
certificat amont par défaut : le relais fonctionne quand même.

⚠️ **`/wp-admin/` à travers le relais : ne pas le promettre.** WordPress fixe
le domaine de ses cookies de session ; la connexion peut échouer. Le mode
« old » est une **archive en lecture**, pas un WordPress de secours.

### L'assurance : un miroir statique, pris pendant que la machine répond

Cette machine est tombée deux fois, personne n'y a d'accès, et elle peut
retomber sans prévenir — auquel cas `old.` tombe avec elle. À faire **avant**
la bascule, depuis le nouveau serveur :

```bash
cd /var/www/cntso && mkdir -p archive-wp && cd archive-wp
wget --mirror --page-requisites --convert-links --adjust-extension \
     --no-parent --reject-regex '(\?|wp-admin|wp-login)' \
     --wait=1 --random-wait https://cnt-so.org/ 2>&1 | tail -5
du -sh cnt-so.org/    # attendu : quelques centaines de Mo
```

Si l'ancienne machine meurt, `old.cnt-so.org` bascule sur le miroir en
remplaçant le `location /` par `root /var/www/cntso/archive-wp/cnt-so.org;` —
une ligne, sans dépendance extérieure.

---

## Deux pièges du jour J : le certificat et le HSTS (vérifié le 11/09/2026)

### 1. Une fenêtre d'erreur de certificat

Le vhost `cntso` déclare **déjà** `cnt-so.org`, `www` et `educ`, mais avec le
certificat `newsite`, qui ne les porte pas (il couvre newsite + 13, 34, 86,
auvergne, numerique, rhone-alpes, stucs). Dès que le DNS bascule, ces trois
noms servent un certificat au mauvais nom, jusqu'à ce que certbot tourne. Et
certbot ne peut pas l'émettre avant : il n'a que les greffons nginx, standalone
et webroot, et HTTP-01 exige que le nom pointe déjà ici.

Deux façons de faire :

1. **Pré-émettre en DNS-01** — `python3-certbot-dns-ovh` et une clé d'API OVH
   avec droits sur `/domain/zone/cnt-so.org/*`. Le certificat existe avant la
   bascule : aucune fenêtre. Voie propre. (Les clés `OVH_*` du site servent aux
   listes de diffusion ; une clé dédiée, bornée à la zone, est préférable.)
2. **Basculer puis émettre aussitôt** — faisable parce que le TTL de
   `cnt-so.org` est déjà à **60 s**. Mais **`www` et `educ` sont à 3 600 s** :
   les abaisser à 60 s **au moins une heure avant**, sinon ils traîneront une
   heure derrière l'apex.

L'ancien site n'envoie **aucun** HSTS et le domaine n'est pas préchargé :
pendant la fenêtre, l'erreur resterait franchissable (un avertissement, pas un
blocage). La messagerie n'est pas concernée : MX `mx1/2/3.mail.ovh.net`, SPF
`include:mx.ovh.com`.

### 2. Le HSTS du nouveau site verrouillera tous les sous-domaines

Django envoie `Strict-Transport-Security: max-age=31536000; includeSubDomains`
(`SECURE_HSTS_INCLUDE_SUBDOMAINS = True`, durci le 09/09 ; nginx n'en ajoute
aucun). Sans danger aujourd'hui sur `newsite.cnt-so.org`. **Mais dès que
`cnt-so.org` sera servi ici, chaque visiteur verra tous les `*.cnt-so.org`
forcés en HTTPS pendant un an, sans pouvoir passer outre.**

Sous-domaines sondés le 11/09 sans HTTPS valide : **`mail`** (alias de
`ssl0.ovh.net`, dont le certificat ne porte pas ce nom — l'accès au webmail
par ce nom casserait), `ftp`. (`smtp`, `imap`, `autodiscover`, `autoconfig`
servent des clients de messagerie, que le HSTS ne concerne pas.)

→ **Avant la bascule : `SECURE_HSTS_INCLUDE_SUBDOMAINS = False`**, ou un
`max-age` court, et ne réactiver `includeSubDomains` qu'une fois chaque
sous-domaine vérifié en HTTPS. C'est aussi le prérequis du préchargement,
reporté (note de la mémoire cnt-adhesion, `project_hsts_preload_differe`).

**Fait le 11/09/2026** (commit `8f28f0f`) : `includeSubDomains` coupé, en-tête
servi vérifié en production — `max-age=31536000`, seul.

## Le jour J, dans l'ordre

**Avant** — `www` et `educ` à **60 s** de TTL (l'apex y est déjà) ; choisir
entre certificat pré-émis en DNS-01 et émission aussitôt après ; couper
`includeSubDomains` du HSTS (voir « Deux pièges du jour J »). Sans TTL court,
un retour arrière met des heures à se propager.

1. **Sauvegarde** de la base (voir `!DEPLOIEMENT.md` : `sudo -u postgres pg_dump`,
   vérifier que le fichier pèse une dizaine de Mo et pas 20 octets).
2. **Miroir statique** de l'ancien site (ci-dessus), pendant que `cnt-so.org`
   désigne encore l'ancienne machine.
3. **Import de rattrapage final** + `normalise_urls_heritees` +
   `repare_entites_html`, puis annonce du gel éditorial.
4. **DNS chez OVH** — zone `cnt-so.org` :
   - `cnt-so.org` (A) → `51.91.242.64`
   - `www` (A) → `51.91.242.64`
   - `educ` (A) → `51.91.242.64`
   - `old` (A) → `51.91.242.64`  *(et `old-educ` si l'Éducation le souhaite)*

   ⚠️ **Ne toucher ni aux MX, ni aux TXT (SPF/DKIM/DMARC).** Les 98 boîtes
   `@cnt-so.org` sont chez OVH et ne dépendent pas des enregistrements A. Une
   erreur ici coupe le courrier du syndicat, formulaires de contact compris.

   ⚠️ **Ne toucher pas davantage aux A de `nextcloud`, `forum`, `testwp`, `ftp`.**
   `nextcloud.cnt-so.org` est un **Nextcloud en service** sur l'ancienne machine
   (Apache 2.4.59, page de connexion en 200 le 12/09/2026). Arnaud, 12/09 :
   « il faut qu'il reste accessible ». Son enregistrement doit rester sur
   5.196.74.69.

   Attendre la propagation : `dig +short cnt-so.org www.cnt-so.org educ.cnt-so.org old.cnt-so.org`
5. **nginx** — ajouter `old.cnt-so.org` (+ `old-educ`) au vhost neuf, vérifier
   que les 3 noms de la bascule sont bien dans les DEUX blocs du vhost cntso
   (fait le 02/09), activer `old-cntso`, `sudo nginx -t`.
6. **certbot, APRÈS le DNS** — repasser **tous** les noms, jamais un seul :
   ```bash
   sudo certbot --nginx --cert-name newsite.cnt-so.org --expand -n \
     -d newsite.cnt-so.org -d cnt-so.org -d www.cnt-so.org -d educ.cnt-so.org \
     -d old.cnt-so.org -d 13.cnt-so.org -d 34.cnt-so.org -d 86.cnt-so.org \
     -d auvergne.cnt-so.org -d numerique.cnt-so.org -d rhone-alpes.cnt-so.org \
     -d stucs.cnt-so.org
   ```
   **Fait le 12/09/2026 : `www` et `old` sont DÉJÀ dans le certificat.** Ils
   pointaient déjà sur cette machine, donc HTTP-01 pouvait les valider avant la
   bascule. Le certificat porte dix noms et court jusqu'au **11 décembre 2026**
   (le renouvellement du 15 octobre est absorbé). Il n'en reste que **deux à
   ajouter le jour J** — `cnt-so.org` et `educ.cnt-so.org` —, qui eux ne peuvent
   pas l'être avant, faute de greffon DNS.

   ⚠️ **certbot sortira en code 1 alors qu'il aura réussi.** Il tente d'insérer
   sa propre redirection HTTP→HTTPS pour `www.cnt-so.org` et bute sur la nôtre,
   celle du 11/09 qui envoie `www` vers l'apex canonique. La nôtre est la bonne,
   on la garde. Le certificat est bel et bien émis ET déployé malgré ce code de
   retour : **vérifier le certificat servi, jamais le code de sortie**
   (`openssl s_client -servername …`, ou `certbot certificates`). Ne PAS suivre
   la suggestion `certbot install --cert-name newsite.cnt-so.org` : inutile, et
   elle rejouerait le même conflit. Contrôlé le 12/09 — renouvellement
   `--dry-run` réussi, minuterie intacte.

   ⚠️ **Ne jamais lire `/etc/nginx/sites-available/cntso` : il est PÉRIMÉ.**
   `sites-enabled/cntso` est un vrai fichier, pas un lien, et c'est lui qui est
   servi. Le fichier de `sites-available` ignore `cnt-so.org`, `www`, `educ`,
   `34` et les règles `/media/` — il m'a fait conclure à tort, le 12/09, que la
   bascule était mal préparée. Lire `sudo nginx -T`, qui montre la
   configuration effective.

   (Un `certbot -d nouveau-nom` isolé remplace le certificat multi-noms dans le
   vhost et casse le HTTPS de tous les autres — incident du 17/07/2026.)
   certbot ajoute aussi, dans le bloc du port 80, la redirection HTTP→HTTPS de
   chaque nom certifié : jusque-là, ce bloc répond **404** aux noms qu'il ne
   connaît pas — `http://cnt-so.org` y compris.
7. **Django** — `/var/www/cntso/cntso/local_settings.py` :
   ```python
   ALLOWED_HOSTS = ['cnt-so.org', 'www.cnt-so.org', 'educ.cnt-so.org',
                    'newsite.cnt-so.org', '51.91.242.64']
   MAIN_SITE_BASE_URL = 'https://cnt-so.org'
   ```
   (ce fichier **écrase** l'`ALLOWED_HOSTS` de `settings.py` : le modifier là
   et nulle part ailleurs), puis `sudo supervisorctl restart cntso`.
8. **Éducation** — dans /cms/, fiche du syndicat, panneau « Domaine autonome » :
   `educ.cnt-so.org`, puis Publier. **Pas avant** le DNS et le certificat :
   posé trop tôt, il redirige `/education/` vers un domaine qui n'est pas à nous.
9. **hCaptcha** — ajouter `cnt-so.org`, `www.cnt-so.org` et `educ.cnt-so.org`
   dans le tableau de bord. Sans ça, **aucun formulaire public ne part** (c'est
   exactement la panne du 02/09, restée invisible trois mois).

### Vérifications

```bash
for u in https://cnt-so.org/ https://www.cnt-so.org/ https://educ.cnt-so.org/ \
         https://old.cnt-so.org/ https://cnt-so.org/cms/ ; do
  printf "%-34s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' "$u")"
done
curl -sI https://cnt-so.org/ | grep -i strict-transport
curl -s https://cnt-so.org/sitemap.xml | grep -c "<loc>"        # ~816
curl -s https://old.cnt-so.org/ | grep -c 'old.cnt-so.org'      # > 0 = réécriture OK
curl -sI https://old.cnt-so.org/ | grep -i x-robots-tag         # noindex
```
Puis, à la main : un envoi réel de formulaire de contact sur `cnt-so.org` et sur
`educ.cnt-so.org` (hCaptcha ne se teste pas en curl), et une adresse
`/wp-content/uploads/` d'un article ancien.

### Retour arrière

Remettre les A vers `5.196.74.69` (TTL 300 s), vider `custom_domain` sur la
fiche Éducation, remettre `MAIN_SITE_BASE_URL` sur `newsite.cnt-so.org`,
redémarrer. Le certificat multi-noms n'a pas besoin d'être défait.

---

## Le Nextcloud vit sur l'ancienne machine (12/09/2026)

La bascule ne le touche pas : son enregistrement DNS ne change pas, et le HSTS
du nouveau site n'impose plus rien aux sous-domaines depuis le 11/09.

Ce qui le menace, c'est la machine elle-même : deux pannes en un mois (MySQL),
aucun accès SSH de notre côté, et un certificat Let's Encrypt qui ne se
renouvelle que si elle tourne — échéance **31/10/2026**, et il couvre aussi
`testwp.cnt-so.org`.

À prévoir, hors chantier de bascule :

- demander à qui administre cette machine une **sauvegarde des données**
  Nextcloud (fichiers et base) ;
- vérifier vers le **1er octobre** que le certificat s'est renouvelé ;
- envisager de **déplacer le Nextcloud sur le serveur OVH** (88 Go libres) :
  ce serait le dernier service vivant à quitter l'ancienne machine.

## Reproduire la liste des articles absents

```bash
python3 - <<'EOF'
import urllib.request, json, re
g=lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent':'audit'}), timeout=30)
sm=g('https://newsite.cnt-so.org/sitemap.xml').read().decode()
arts=[l for l in re.findall(r'<loc>([^<]+)</loc>', sm) if '/article/' in l]
for host in ('cnt-so.org','educ.cnt-so.org'):
    page=1
    while True:
        arr=json.load(g(f'https://{host}/wp-json/wp/v2/posts?per_page=100&page={page}&_fields=slug,date,title'))
        if not arr: break
        for p in arr:
            if not any(a.endswith(f"/article/{p['slug']}/") for a in arts):
                print(host, p['date'][:10], re.sub('<[^>]+>','',p['title']['rendered'])[:70])
        page+=1
EOF
```
Attention : ce test compare les **slugs**. Une partie des écarts sont des
variantes typographiques (point médian encodé `%c2%b7`) ; recouper par titre
avant de conclure qu'un article manque — j'ai fait l'erreur une fois ce jour-là.
