# Leçons

## 2026-07-12 — Attribution de sortie dans les commandes enchaînées

**Erreur :** audit annonçant `db.sqlite3` versionné dans git (avec recommandation de purge d'historique) alors qu'il ne l'a jamais été. La commande `git ls-files | grep ... ; git check-ignore db.sqlite3` avait été lue comme si « db.sqlite3 » venait de `ls-files`, alors que c'était la sortie de `check-ignore` (qui affiche le chemin quand le fichier est ignoré).

**Règle :** avant d'annoncer un problème grave (fuite de données, faille), re-vérifier avec une commande *isolée et sans ambiguïté* (`git ls-files -s -- <path>`, `git ls-tree HEAD <path>`). Ne jamais enchaîner plusieurs commandes dont les sorties peuvent se confondre quand le résultat conditionne une action lourde (purge d'historique, réécriture de SHA).
