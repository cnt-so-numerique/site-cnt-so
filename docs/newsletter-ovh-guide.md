# Guide — Newsletters et listes mails OVH

**Site :** CNT-SO / newsite.cnt-so.org  
**Mis à jour :** juin 2026

---

## Comment ça fonctionne

```
Visiteur s'abonne sur le site
        ↓
  Email de confirmation envoyé
        ↓
  Visiteur clique sur le lien de confirmation
        ↓
  Abonné enregistré en base (is_active = true)
        ↓  ← synchronisation automatique
  Ajouté à la liste OVH du syndicat
        ↓
  Rédacteur envoie une newsletter depuis le CMS
        ↓
  1 seul email → actu-stucs-cntso@cnt-so.info
        ↓
  OVH redistribue à tous les abonnés de la liste
```

---

## Prérequis (déjà en place)

- Compte OVH avec accès au domaine **cnt-so.info**
- Clés API OVH configurées sur le serveur (`/var/www/cntso/.env` et `local_settings.py`)
- Application disponible sur **newsite.cnt-so.org**

---

## Étape 1 — Créer la liste mail sur OVH

1. Se connecter sur [manager.ovh.com](https://manager.ovh.com)
2. **Emails** → **cnt-so.info** → **Listes de diffusion**
3. Créer une nouvelle liste

**Convention de nommage :**
```
actu-[nom-syndicat]-cntso
```
Exemples : `actu-stucs-cntso`, `actu-sipn-cntso`, `actu-ur-idf-cntso`

**Paramètres recommandés :**
| Paramètre | Valeur |
|-----------|--------|
| Modération des abonnements | Désactivée |
| Modération des messages entrants | Désactivée **OU** ajouter `newsletter@cnt-so.org` comme expéditeur autorisé |
| Politique de réponse | Adresse de la liste |

> ⚠️ Si la modération des messages est activée sans ajouter l'expéditeur, les newsletters seront bloquées en attente de validation.

---

## Étape 2 — Lier la liste au syndicat dans le CMS

1. Aller sur [newsite.cnt-so.org/cms/](https://newsite.cnt-so.org/cms/)
2. **Structure du site** → **Mon syndicat** → cliquer sur le syndicat à configurer
3. Onglet **Newsletter OVH**
4. Remplir le champ **Liste mail OVH** avec le nom de la liste **sans** `@cnt-so.info`

```
✓ actu-stucs-cntso
✗ actu-stucs-cntso@cnt-so.info
```

5. Sauvegarder

**C'est terminé.** La liaison est active immédiatement.

---

## Étape 3 — Envoyer une newsletter

1. CMS → **Contenu** → **Newsletters** → créer une newsletter
2. Remplir : sujet, texte d'introduction, sélectionner des articles
3. Cliquer sur **Envoyer** (bouton dans la liste ou dans la fiche)
4. La page de confirmation affiche le mode d'envoi :

**Mode OVH** (liste configurée) :
> Encadré jaune — "Mode OVH : un seul e-mail sera envoyé à **actu-stucs-cntso@cnt-so.info**"
> Nombre d'abonnés OVH affiché

**Mode direct** (pas de liste configurée) :
> Envoi email par email aux abonnés confirmés en base

5. Cliquer sur **Envoyer via OVH → actu-stucs-cntso@cnt-so.info**

Un seul email part. OVH redistribue à tous les abonnés.

---

## Gérer les abonnés

### Depuis l'interface CMS

URL : `/cms/mailing-lists/`

| Rôle | Accès |
|------|-------|
| Superadmin | Toutes les listes OVH |
| Rédacteur-en-chef | Uniquement la liste de son syndicat |
| Rédacteur | Aucun accès |

Depuis la page d'une liste : ajouter une adresse, retirer un abonné, filtrer par recherche.

### Synchronisation automatique

Quand un visiteur confirme son inscription sur le site → ajouté automatiquement à la liste OVH.

> ⚠️ Les désabonnements depuis le lien dans la newsletter retirent l'abonné de la base du site mais **pas** de la liste OVH. Retirer manuellement depuis `/cms/mailing-lists/<nom>/` si nécessaire.

---

## Fusionner plusieurs listes existantes

Si un syndicat avait plusieurs anciennes listes et veut tout regrouper :

1. Exporter les abonnés de chaque ancienne liste depuis OVH (manager.ovh.com)
2. Les importer dans la nouvelle liste depuis `/cms/mailing-lists/<nom>/` (bouton Ajouter, un par un ou par batch)
3. Mettre à jour le champ **Liste mail OVH** dans le CMS avec le nom de la nouvelle liste
4. Supprimer les anciennes listes sur OVH une fois la migration vérifiée

---

## Récapitulatif des URLs

| Page | URL |
|------|-----|
| Tableau de bord CMS | `/cms/` |
| Toutes les listes OVH | `/cms/mailing-lists/` |
| Détail d'une liste | `/cms/mailing-lists/actu-stucs-cntso/` |
| Newsletters | `/cms/snippets/content/newsletter/` |
| Abonnés en base | `/cms/snippets/content/subscriber/` |
| Paramètres du syndicat | `/cms/snippets/cms/sectionpage/` |

---

## Résolution de problèmes courants

| Problème | Cause probable | Solution |
|----------|----------------|----------|
| Newsletter bloquée, pas distribuée | Modération OVH activée | Désactiver la modération ou ajouter `newsletter@cnt-so.org` comme expéditeur autorisé dans OVH |
| "Invalid ApplicationSecret" dans le CMS | Clés OVH manquantes | Vérifier `/var/www/cntso/cntso/local_settings.py` sur le serveur |
| Abonné confirmé sur le site mais absent de la liste OVH | Champ "Liste mail OVH" vide dans le CMS | Renseigner le champ dans la fiche du syndicat |
| Page listes mails affiche "403" | Utilisateur sans rôle chef | Se connecter avec un compte rédacteur-en-chef ou superadmin |
| Nombre d'abonnés affiché = "?" | API OVH temporairement indisponible | Réessayer plus tard, le fonctionnement n'est pas bloqué |
