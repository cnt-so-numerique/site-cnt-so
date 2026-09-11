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
- [ ] **Rapatrier les 32 fichiers manquants** dans `/var/www/cntso/legacy/`,
      même arborescence, comme les 346 du 02/09 — **tant que l'ancien
      WordPress répond**. Les mêmes adresses resteront valables après la
      bascule, sans réécrire un seul article.
- [ ] **Gel éditorial** : prévenir les syndicats que l'ancien WordPress ne doit
      plus recevoir de publication à partir d'une date annoncée. Sans ce gel,
      un article publié après le dernier import est perdu pour le public le
      jour où le nom bascule.

### B. Le mode « old » — à préparer avant de toucher au DNS

Voir la section dédiée ci-dessous. À faire dans cet ordre : miroir statique
d'abord (assurance), vhost `old.` ensuite.

### C. Bascule elle-même — le jour J

Séquence détaillée ci-dessous.

### D. Non bloquant, à faire après

- [ ] GitHub Actions : suite de tests sur **PostgreSQL** + `pip-audit`
      hebdomadaire (la prod est sur PostgreSQL, les tests sur SQLite).
- [ ] Menu de l'Éducation : 25 entrées en URL écrites à la main, dont trois
      sans cible réelle. À refaire avec le syndicat.
- [ ] `cntso/middleware.py:85` : la double barre oblique (`//13/…`) construit un
      hôte inexistant. Sans objet depuis que nginx sert `/wp-content/uploads/`,
      mais cinq lignes et un test d'hygiène.
- [ ] Redirection `www.cnt-so.org` → `cnt-so.org` en 301 dans nginx (aujourd'hui
      les deux noms serviraient le même contenu).

---

## Le mode « old » : pourquoi le réflexe évident ne marche pas

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
   (Un `certbot -d nouveau-nom` isolé remplace le certificat multi-noms dans le
   vhost et casse le HTTPS de tous les autres — incident du 17/07/2026.)
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
