# En attente — vieux serveur WordPress (5.196.74.69)

**Situation (constat 2026-07-12)** : le vieux serveur WordPress est en panne —
erreur « Database Connection » sur tous les sites (cnt-so.org, educ.cnt-so.org),
SSH refusé (port 22). Un copain doit le relancer (MySQL a priori).

⚠️ Ce serveur héberge aussi les **images legacy** (`wp-content/uploads/`) encore
référencées en fallback par les articles non migrés (`any_image_url`). Sa panne
définitive casserait ces images sur le nouveau site → ça renforce l'urgence du
chantier d'import des images dans Wagtail (cf. chantier STUCS).

## À faire dès que le serveur répond de nouveau

- [x] **Remapper les catégories des 100 articles Éducation** (perdues par le bug
  d'import corrigé dans le commit `4dead3d`) :
  ```bash
  ssh debian@51.91.242.64
  cd /var/www/cntso && source venv/bin/activate
  python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education --categories-only --dry-run
  python manage.py import_from_wp_api --url https://educ.cnt-so.org --section education --categories-only
  ```
- [x] **Nettoyer ensuite les catégories en doublon** de la section education
  (44 catégories dont deux jeux parallèles + variantes typographiques « 1er dégré »,
  tirets courts/longs…) : supprimer celles qui restent vides après le remapping.
  Ne PAS les supprimer avant le remapping — il les repeuple.
- [x] **Vérifier la page** https://newsite.cnt-so.org/education/ressources/ :
  les filtres doivent réapparaître (seules les catégories non vides s'affichent).
- [x] **Relancer le chantier d'import des images legacy** dans Wagtail
  (`import_from_wp_api --media-only` section par section) tant que le serveur
  est encore debout — chaque panne peut être la dernière.

---

## ✅ Checklist déroulée le 2026-07-16

1. Catégories Éducation : 100 articles remappés (`--categories-only`), filtres de
   `/education/ressources/` de retour (23 catégories).
2. 21 catégories en doublon supprimées ; 2 URLs du menu Éducation corrigées vers
   les slugs WP réels (`motions_et_autres`, `sante_et_securite_au_travail` —
   attention, slugs avec underscores).
3. Images legacy : la prod était déjà complète (0 fichier manquant). Nouvelle
   commande `recover_legacy_media` disponible en cas de trou futur (et pour
   compléter une copie locale de dev). Ne PAS utiliser `--media-only`
   (réécrirait les corps d'articles retouchés depuis la migration).

Reste hors de cette checklist : bascule DNS finale de cnt-so.org / educ.cnt-so.org.
