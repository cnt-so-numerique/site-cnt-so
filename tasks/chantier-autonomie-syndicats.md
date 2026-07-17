# Chantier : autonomie éditoriale des syndicats

Décisions actées avec Arnaud le 2026-07-16 (sept questions tranchées explicitement).

## Modèle cible

**Rôle unique par syndicat — `redacteur_<slug>`** (fusion des anciens `chef_<slug>`) :
- écrit ET **publie directement** articles, pages, événements (le brouillon reste
  un état de travail : « Enregistrer le brouillon » + prévisualisation conservés,
  mais la publication ne demande l'approbation de personne) ;
- modifie la fiche de son syndicat (logo, réseaux sociaux, textes intro/rejoindre/agenda) ;
- gère le menu de navigation de son site ;
- gère ses catégories d'articles (création/renommage, scoppé à sa section) ;
- **dépublie mais ne supprime pas** (suppression définitive = confédéral) ;
- newsletter complète : rédaction, envoi, gestion des abonnés, **export CSV inclus** ;
- gère son formulaire de contact + voit les messages reçus de son syndicat ;
- médias **cloisonnés par syndicat** (Collections Wagtail) ;
- ne voit rien des autres syndicats ni du site confédéral.

**`redacteur_en_chef`** (équipe confédérale) : tout ce qui précède sur tous les
syndicats + site confédéral, sélecteur multi-sites, une confédérale
(`featured_on_conf`), newsletters/menus/formulaires de tous, **création des
comptes rédacteurs** et rattachement au syndicat (/cms/users/).

**Superuser** : technique (domaines, Django admin).

## État des lieux (constats 2026-07-16)

- ✅ **Fait (non commité)** : résolution du site courant via les groupes par
  section (`cms/site_context.py::get_group_scoped_site`, délégation de
  `get_current_site_for_view`, état « aucun syndicat assigné » du dashboard,
  11 tests — suite à 640 verts). Prérequis de tout le reste.
- ⚠️ **Personne ne peut publier d'article sauf superuser** : le workflow Wagtail
  par défaut « Moderators approval » est actif et les boutons « Publier »
  n'apparaissent pour aucun rôle (même `redacteur_en_chef` ne l'a pas sur un
  article existant — bizarrerie à élucider : sa GroupPagePermission publish est
  posée sur la HomePage pk=3, l'article testé pk=62 est sous la SectionPage
  pk=4 ; vérifier si pk=4 est bien un descendant de pk=3, sinon les permissions
  d'arbre sont posées au mauvais endroit).
- ⚠️ Les groupes `redacteur_<slug>`/`chef_<slug>` n'ont PAS les permissions
  Django modèle (`cms.add_articlepage`…) : 302 sur /cms/snippets/cms/articlepage/add/.
  `setup_cms_permissions` ne leur donne que access_admin + GroupPagePermission.
- ⚠️ `MoveMenuItemView` / `ReorderMenuItemsView` (cms/wagtail_hooks.py) : lookup
  par pk brut sans filtre site → à sécuriser AVANT d'ouvrir les menus aux
  rédacteurs (sinon manipulation cross-site des menus).
- ⚠️ `NewsletterSendView` ne bloque que si `current_site` est résolu (garde
  corrigée par la délégation du résolveur, mais re-tester en ouvrant l'accès).
- Le groupe générique `redacteur` (via `Author.site`) reste une voie de
  rattachement valide ; à terme standardiser sur les groupes par section
  (la commande `setup_cms_permissions._migrate_existing_users` fait déjà la
  migration Author.site → redacteur_<slug>).

## Découpage (ordre d'exécution)

1. **[fait, à committer] Résolution de site par groupe** — préalable à tout.
2. **Publication directe** : désactiver le workflow « Moderators approval »
   (supprimer le Workflow par défaut ou `WAGTAIL_WORKFLOW_ENABLED = False`) ;
   élucider/corriger la GroupPagePermission de redacteur_en_chef ; donner
   publish aux `redacteur_<slug>` sur leur SectionPage ; vérifier que le bouton
   « Publier » apparaît pour chaque palier sur articles/pages/fiche syndicat.
3. **Permissions modèle manquantes** : compléter `setup_cms_permissions` (ou
   `create_editorial_groups`) pour donner aux `redacteur_<slug>` les perms
   Django : articlepage/contentpage/event add+change (PAS delete),
   cmscategory add+change+view, images/docs add+change+choose (PAS delete),
   menuitem add+change+view, newsletter add+change+view, subscriber
   add+change+delete+view, contactmessage view+change, formulairecontact
   view+change (+ champs custom). Dépublication : unpublish via GroupPagePermission.
4. **Fusion chef_<slug> → redacteur_<slug>** : migration de données (membres
   déplacés, groupes chef_* supprimés), mise à jour de `setup_cms_permissions`
   pour ne plus les créer, et du pattern dans `site_context` (garder le match
   `chef_` pour la transition, le retirer ensuite).
5. **Ouvrir newsletter/abonnés/export aux rédacteurs de syndicat** : remplacer
   `WagtailChefRequiredMixin` par un mixin « membre d'un syndicat OU chef »
   sur NewsletterSendView/SubscriberExportView, avec scoping strict par
   `get_current_site` (le garde site != current doit devenir bloquant même si
   current est None → refuser). Idem vues contact CMS.
   **Inclut les écrans « Listes mails » OVH** (`/cms/mailing-lists/` :
   voir/ajouter/retirer des abonnés, import/export CSV — demande explicite
   d'Arnaud 2026-07-16) : étendre `_allowed_mailing_lists` pour qu'un non-chef
   avec un syndicat résolu accède aux listes de SON syndicat (la logique
   par-site existe déjà pour les chefs ; le lot 1 résout désormais le syndicat
   des rédacteurs de groupe). Rendre l'entrée de menu « Listes mails » visible
   pour eux (aujourd'hui ChefOnlyMenuItem).
6. **Menus** : sécuriser Move/Reorder (filtrer par `item.site == get_current_site`)
   puis ouvrir l'accès aux rédacteurs (menu admin + perms).
7. **Médias cloisonnés** — FAIT 2026-07-17 : une Collection Wagtail par
   syndicat + « Commun » (choose seul), créées par `setup_cms_permissions`
   (idempotent, robuste au renommage via la collection déjà liée au groupe).
   Aucun hook nécessaire : Wagtail n'écoute que les GroupCollectionPermission
   (les perms Django modèle sont ignorées — avant ce lot, PERSONNE hors
   superuser ne pouvait téléverser ni choisir un média, même redacteur_en_chef).
   Le chooser filtre nativement sur choose et l'upload impose la seule
   collection avec add. redacteur_en_chef → Root (tout) ; groupe générique
   redacteur → choose sur Commun seulement. 9 tests (MediaCollectionsTest).
   Migration des images existantes (toutes dans Root) = lot séparé (gros
   volume, faisable progressivement).
8. **Comptes** : perms wagtailusers pour redacteur_en_chef (add/change user),
   vérifier le formulaire « Syndicat » de /cms/users/ (Author.site + ajout au
   groupe redacteur_<slug> automatique — à synchroniser).
9. **Dashboard** : tuiles abonnés/messages visibles pour les rédacteurs de
   syndicat (aujourd'hui gated `{% if is_chef %}`), entrées de menu adaptées.
10. **Tests** : chaque lot avec ses tests ; scénario complet par palier.
11. **Prod** : déploiement + exécution `setup_cms_permissions` mis à jour +
    création des vrais comptes par syndicat (avec Arnaud).

## Hors périmètre / inchangé
- `is_chef()` garde son sens confédéral (une confédérale, sélecteur multi-sites,
  vues cross-site type SyndicatManageView).
- Génération des sous-domaines, thèmes des sites : rien à voir ici.
