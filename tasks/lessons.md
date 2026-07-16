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
