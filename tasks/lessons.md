# Leçons

## 2026-07-12 — Attribution de sortie dans les commandes enchaînées

**Erreur :** audit annonçant `db.sqlite3` versionné dans git (avec recommandation de purge d'historique) alors qu'il ne l'a jamais été. La commande `git ls-files | grep ... ; git check-ignore db.sqlite3` avait été lue comme si « db.sqlite3 » venait de `ls-files`, alors que c'était la sortie de `check-ignore` (qui affiche le chemin quand le fichier est ignoré).

**Règle :** avant d'annoncer un problème grave (fuite de données, faille), re-vérifier avec une commande *isolée et sans ambiguïté* (`git ls-files -s -- <path>`, `git ls-tree HEAD <path>`). Ne jamais enchaîner plusieurs commandes dont les sorties peuvent se confondre quand le résultat conditionne une action lourde (purge d'historique, réécriture de SHA).

## 2026-07-12 — Ne pas déployer cnt-adhesion depuis cette machine

**Erreur :** dans le cadre de la checklist preprod du site, commit + push de l'index `Adhesion.status` vers les remotes `github` et `prod` du clone local `~/PycharmProjects/cnt-adhesion`, puis tentative de migrate/restart sur le serveur. Or un dépôt autonome pour adhesion a été créé le matin même : le clone local et ses remotes n'étaient plus la bonne référence.

**Règle :** cnt-adhesion est un projet séparé avec son propre cycle de vie (dépôt autonome, checklist AVANT_PUBLICATION.md, app de paiement). Ne jamais y committer/pousser/déployer depuis une session consacrée au site cnt, même pour un « petit » changement listé dans preprod.md — signaler le besoin et laisser Arnaud le faire dans le bon contexte. Avant tout push vers un projet tiers, confirmer que le clone local est bien le dépôt de référence actuel.

## 2026-07-16 — Guide : réduire la consommation de tokens inutile

**Constat :** sur une session longue (refonte contact/adhésion, audit SEO, redesign), beaucoup de tokens perdus sur des choses évitables : sorties de commandes collées brutes dans le contexte (HTML complet, JSON, logs de tests), captures d'écran Puppeteer utilisées alors qu'une vérification textuelle suffisait, et surtout du churn de débogage (redémarrages répétés du serveur de dev, `pkill` mal compris) qui a fait perdre plusieurs allers-retours pour rien.

**Règle — à appliquer par défaut sur ce projet, sans qu'Arnaud ait à le redemander :**
1. **Rediriger, ne pas coller.** Toute sortie de commande volumineuse (page HTML, JSON, sortie de `manage.py test`) → rediriger vers un fichier (`> /tmp/...` ou le scratchpad) puis `grep`/`tail`/`head` uniquement ce qui est utile. Ne jamais laisser une commande déverser une réponse HTTP complète ou un log de 150 lignes dans le contexte si 3 lignes suffisent à répondre à la question.
2. **Captures d'écran seulement pour du visuel réel.** Puppeteer/screenshots réservés aux vérifications de mise en page, de design, de rendu — jamais pour confirmer un fait vérifiable en texte (statut HTTP, présence d'une classe CSS, contenu d'une balise meta). Dans ce cas, `curl` + `grep` suffit et coûte une fraction du prix.
3. **Diagnostiquer avant de réessayer.** Face à un comportement inattendu (serveur qui ne répond pas, commande qui échoue), chercher la cause once (`ps aux`, lire le log du process) plutôt que relancer plusieurs fois à l'aveugle — chaque essai raté coûte un aller-retour complet.
4. **Déléguer les explorations larges à un subagent** (Explore/general-purpose) : son transcript reste isolé, seul le résumé revient dans la conversation principale. À privilégier dès qu'une recherche dépasse 2-3 commandes.
5. **Sessions trop longues = mémoire, pas de scroll infini.** Le système de mémoire (`~/.claude/projects/.../memory/`) existe pour porter la continuité entre sessions — pas besoin de garder tout un historique de plusieurs jours dans un seul fil. Pour un nouveau chantier sans lien direct avec la conversation en cours, privilégier une nouvelle conversation (mémoire + `tasks/lessons.md` suffisent à reprendre le contexte).

**Compromis assumé :** filtrer/déléguer plus agressivement prive parfois de contexte utile en cas de bug inattendu (par exemple si l'info dont on a besoin n'était pas dans les 3 lignes qu'on a gardées). À doser selon la criticité — sur un correctif de prod ou un diagnostic de bug, mieux vaut garder plus de contexte que d'économiser des tokens.

## 2026-08-05 — Ne pas deviner ce que désigne un sigle

**Erreur :** ayant trouvé 7 catégories orphelines portant `section_slug='staa'`, j'ai
écrit dans le journal d'audit et dans un rapport à Arnaud qu'il s'agissait d'un
« syndicat agro-alimentaire absent de l'arborescence ». Pure invention à partir des
lettres. **STAA = Syndicat des Travailleur·euses Artistes-Auteurs**, syndicat bien
vivant de la CNT-SO qui a simplement son propre site (`staa-cnt-so.org`).

Le plus gênant : **l'information était dans le dépôt**, à deux endroits que je n'avais
pas interrogés — `content/context_processors.py:74` contient le libellé complet
« syndicat-des-travailleur-euse-s-artistes-auteurs-staa », et la base de dev a une
`SectionPage` `'STAA (Artistes-Auteurs)'` avec son `external_url`. J'avais requêté
`SectionPage` en prod (où la section n'existe pas) et conclu de cette seule absence.

**Règle :** un sigle inconnu se résout, il ne se devine pas. Avant d'écrire ce que
désigne un identifiant opaque trouvé en base — surtout dans un document qui fait
référence — chercher le libellé en clair : `grep -ri "<sigle>"` sur le dépôt entier
(gabarits, processeurs de contexte, fixtures, docs), et interroger la base de **dev**
autant que celle de prod, car dev garde des sections que la prod n'a pas. À défaut,
écrire « slug non identifié » et demander — jamais une étymologie plausible.

**Corollaire, plus large :** l'absence d'une ligne en production ne prouve pas
l'inexistence de la chose. Ici l'absence de la section STAA en prod était l'anomalie
à expliquer, pas la preuve que le syndicat avait disparu.

## 2026-08-05 — `git checkout --` n'est pas une restauration

**Erreur :** pour une contre-épreuve, j'ai retiré un `select_related` à la main
dans `cms/wagtail_hooks.py`, lancé le test (échec attendu, la preuve était
faite), puis « restauré » le fichier avec `git checkout -- cms/wagtail_hooks.py`.
Cette commande restaure depuis le **dernier commit**, pas depuis l'état de
travail : elle a emporté tout ce qui n'était pas commité dans ce fichier —
itérateur groupé, CSS, tri hiérarchique, méthode de bornage. Une heure de
travail effacée par une commande de « retour en arrière ».

**Règle :** pour une contre-épreuve, toujours `git stash push -- <fichier>` puis
`git stash pop`. `git checkout --` ne revient jamais à « avant ma
manipulation » — il revient au dernier commit, et détruit le reste sans
avertissement. Si le fichier n'est pas suivi par git (fichier neuf), le déplacer
(`mv`) et le remettre, jamais `checkout`.

**Ce qui a sauvé la mise :** les tests vivaient dans un AUTRE fichier, donc
intacts. Ils ont validé que la reconstruction était fidèle, au lieu de me faire
dépendre de ma mémoire. Corollaire : garder tests et code dans des fichiers
séparés a une valeur au-delà de l'organisation.

**Meilleur réflexe encore :** committer en local avant toute contre-épreuve
destructive. Un commit est réversible, un `checkout` non.

## 2026-08-15 — corriger l'utilisateur à partir d'une base périmée

**Erreur :** Arnaud demande d'ajouter des catégories « dans les secteurs ». Je
lui réponds qu'il n'existe pas de rubrique « Secteurs » et que ça s'appelle
« Syndicats ». C'était faux : en **production** la rubrique s'appelle bien
« Secteurs », c'est ma base de dev qui porte encore l'ancien nom. Le premier
`--dry-run` en prod n'a donc rien créé. J'ai corrigé l'utilisateur sur un point
où il connaissait l'état réel du site mieux que moi.

**Règle :** avant de reprendre l'utilisateur sur un nom d'objet visible dans
l'interface (rubrique, catégorie, libellé, syndicat), vérifier **en prod**, pas
en local. Quand son vocabulaire ne correspond pas au mien, l'hypothèse par
défaut est que ma source est périmée, pas qu'il se trompe. Il regarde le site,
moi une copie du 05/08.

**Corollaire déjà connu, encore vérifié :** la base de dev est désynchronisée de
la prod. C'est la 3e fois de la journée que la prod contredit mon local.

## 2026-08-15 — « 0 article » ne veut pas dire « doublon »

**Erreur :** j'ai qualifié « Syndicat national des transports et de
l'aménagement du territoire » (0 article) de doublon vide de
« Transport – Logistique », d'après la ressemblance des noms et le compteur à
zéro. Arnaud a confirmé sur cette base. En réalité, c'en est le **parent** :
0 article parce que c'est un nœud de hiérarchie, comme « Syndicalisme ». La
suppression aurait détaché la fille de la hiérarchie **sans rien lever**,
`CmsCategory.parent` étant en `SET_NULL`.

**Règle :** avant de proposer une suppression, regarder les relations
entrantes ET sortantes de l'objet, pas seulement son contenu. Un compteur à zéro
est autant le signe d'un conteneur que d'un rebut. Et quand un feu vert repose
sur mon diagnostic, c'est mon diagnostic qu'il faut vérifier avant d'agir, pas
le feu vert.

**Ce qui a sauvé la mise :** le contrôle d'inertie écrit dans la commande
(0 article ET 0 menu ET 0 sous-catégorie) a refusé sur les données réelles.
Écrire le garde-fou dans la commande plutôt que de vérifier à la main l'a rendu
opposable à ma propre erreur.

---

## 2026-08-16 — `{# #}` ne commente qu'une seule ligne

**Erreur :** j'ai écrit un commentaire d'explication sur cinq lignes dans
`templates/content/home.html` en `{# … #}`. Cette syntaxe Django est
**mono-ligne** : seule la première ligne a été mangée, les quatre suivantes se
sont affichées en clair sur la page d'accueil, en haut du carrousel. C'est la
capture d'écran qui l'a révélé, pas les tests — aucun test ne lit le texte
rendu de l'accueil.

**Règle :** un commentaire de template sur plusieurs lignes s'écrit
`{% comment %} … {% endcomment %}`. `{# #}` est réservé aux notes tenant sur
une ligne.

**Plus général :** une modification de template n'est pas vérifiée par la suite
de tests seule. Regarder la page rendue — ici, un `curl | grep` sur une phrase
du commentaire aurait suffi à le prouver en une seconde.

**Récidive (18/08/2026), troisième fois.** Encore dans un template, encore un
commentaire d'explication de deux lignes. `CommentaireDeGabaritTest` l'a
attrapé — la garde tient, mais je continue de la déclencher. La règle à
appliquer sans réfléchir : **dans un template, ne jamais écrire `{# #}`**.
Toujours `{% comment %}`, même pour une ligne. Le choix entre les deux syntaxes
n'apporte rien et coûte un aller-retour à chaque fois.

---

## 2026-08-16 — À spécificité égale, c'est l'ordre qui tranche

**Erreur :** pour rendre leurs proportions aux affiches en colonne unique,
j'ai écrit `height: auto` dans un `@media (max-width: 480px)` placé **avant**
la règle `.hp-manchette .hp-mcard:nth-child(-n+2) img { height: 280px }`.
Même spécificité, donc c'est la dernière écrite qui gagne : mon override a été
battu en silence. La capture d'écran était inchangée et j'ai failli conclure
que la règle ne s'appliquait pas du tout.

**Règle :** dans une feuille de style longue, un `@media` n'ajoute aucune
spécificité. Un override doit être écrit **après** la règle qu'il corrige, ou
porter un sélecteur plus spécifique.

**Ce qui a tranché :** lire `getComputedStyle().height` (280px) plutôt que de
raisonner sur la capture. Une propriété du même bloc (`max-height`) avait bien
pris — preuve que le sélecteur matchait et que le problème était la cascade,
pas le média.

---

## Ne pas parser du HTML à l'expression régulière (17/08/2026)

**Le piège :** pour convertir les cartes HTML de `/syndicats/` en fiches, j'ai
écrit une regex exigeant `<a href> … <img src> … titre … description`. Deux
cartes n'ont pas d'image mais un aplat de couleur : elles ont été **sautées en
silence**. Pire, le `.*?` peut franchir la frontière d'une carte et apparier le
titre de l'une avec la description de la suivante — l'import aurait été faux
sans rien signaler. J'ai cru la page à 13 cartes ; elle en comptait 19.

**Règle :** dès qu'il s'agit de lire du HTML existant, utiliser BeautifulSoup
(déjà dans `requirements.txt`). Une regex ne dit pas ce qu'elle n'a pas vu.

**Corollaire :** toute conversion de contenu doit s'annoncer avant d'écrire —
un `--dry-run` listant ce qui a été reconnu. C'est lui qui a révélé les six
cartes manquantes, sur la base de production et non en dev.

---

## Une lecture immédiate ne dit rien d'un système asynchrone (17/08/2026)

**Le piège :** après avoir ajouté une adresse à une liste OVH, le retrait a
échoué avec « does not exist ». J'ai annoncé à Arnaud une découverte « grave » —
un bug d'encodage d'URL dans `remove_subscriber` qui aurait empêché tout
désabonnement. C'était faux : les opérations OVH sont **asynchrones**, l'ajout
n'était pas encore appliqué. Même cause pour le compteur `nbSubscribers`
périmé, et pour l'adresse de test qui n'apparaissait pas dans `news3` avant
une minute.

**Règle :** face à une API distante, ne jamais diagnostiquer sur une lecture
qui suit immédiatement une écriture. Refaire la mesure après un délai avant
d'accuser le code.

**Corollaire :** je l'avais annoncé comme « grave » avant de vérifier. Une
hypothèse alarmante se qualifie d'abord, se communique ensuite — sinon on fait
courir l'utilisateur après un bug qui n'existe pas.

## Un test qui cherche une chaîne dans le gabarit ne teste rien (26/08/2026)

`assertIn('PAGES_VISEES = [1, 2]', html)` a été écrit pour couvrir l'exigence
« le tract fait 1 ou 2 pages, jamais entre les deux ». Il ne la couvre pas : il
vérifie qu'un littéral figure dans le fichier. Il reste vert si la pagination
sort trois pages, et devient rouge si quelqu'un ajoute une espace. Même chose
pour `assertIn('.zone { flex: 1 1 auto; overflow: hidden; }', html)`, qui
épingle un espacement de CSS.

**Règle** : quand l'exigence porte sur un résultat observable, le test doit
observer le résultat. Pour du JavaScript, cela veut dire un vrai navigateur
(`_pages_du_tract` dans `content/tests.py` : Chrome sans interface, `--dump-dom`,
lecture de `data-pages`), sauté proprement là où il n'y en a pas. Un test sauté
et annoncé vaut mieux qu'un test vert qui ne mesure rien.

**Et toujours vérifier par mutation** : casser volontairement le code et
regarder le test rougir. Les trois correctifs de cet audit ont été validés
ainsi ; sans ça je n'aurais pas su lesquels de mes tests étaient tautologiques.

## Vérifier qu'une fonction s'exécute avant de croire ce qu'elle dit (26/08/2026)

`aerer()` répartissait le blanc restant en bas de chaque page du tract. Elle le
mesurait par `zone.clientHeight - zone.scrollHeight`. Sur un conteneur qui ne
déborde pas, ces deux valeurs sont égales **par définition** : le « restant »
valait toujours 0 et la fonction sortait à la première ligne. Vingt lignes de
code, un commentaire explicatif, zéro effet — et personne ne l'a vu parce que
le résultat sans aération est simplement… du texte en haut de page.

**Règle** : une fonction dont l'effet est invisible à l'œil doit être vérifiée
par la mesure, pas par la relecture. Ici : compter les marges réellement posées
dans le DOM (`grep -c 'style="margin-bottom'`).

## `pkill -f` / `pgrep -f` se retournent contre mon propre shell (31/08/2026)

Trois fois dans la même session, `pkill -f "runserver 8978"` a tué la commande
en cours au lieu du serveur : la ligne de commande de mon propre shell contient
le motif recherché, puisque c'est moi qui viens de l'écrire. Résultat, la suite
de tests lancée juste après mourait avec un code 144 avant d'avoir rien produit,
et j'ai perdu trois passages à chercher pourquoi.

**Règle :** ne jamais chercher un processus par un motif que ma propre commande
contient. Soit lancer le serveur en notant son PID, soit filtrer explicitement :

```bash
PID=$(pgrep -f "manage\.py runserver 8978" | grep -v "^$$\$" | head -1)
```

Le plus simple reste de ne pas mélanger : arrêter le serveur dans une commande,
lancer les tests dans une autre.
