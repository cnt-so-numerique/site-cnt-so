# Documentation CMS — CNT-SO

**Site :** newsite.cnt-so.org  
**CMS :** Wagtail 7 / Django 5.2  
**Mis à jour :** juin 2026

---

## Sommaire

1. [Architecture générale](#1-architecture-générale)
2. [Rôles et droits](#2-rôles-et-droits)
3. [Créer et gérer un compte utilisateur](#3-créer-et-gérer-un-compte-utilisateur)
4. [Naviguer dans le CMS](#4-naviguer-dans-le-cms)
5. [Articles](#5-articles)
6. [Pages de contenu](#6-pages-de-contenu)
7. [Catégories](#7-catégories)
8. [Agenda / Événements](#8-agenda--événements)
9. [Menus de navigation](#9-menus-de-navigation)
10. [Newsletter](#10-newsletter)
11. [Listes mails OVH](#11-listes-mails-ovh)
12. [Adhésions](#12-adhésions)
13. [Formulaire de contact](#13-formulaire-de-contact)
14. [Mon syndicat (paramètres)](#14-mon-syndicat-paramètres)
15. [Syndicats — gestion globale (superadmin)](#15-syndicats--gestion-globale-superadmin)
16. [Images et documents](#16-images-et-documents)
17. [Référence des URLs](#17-référence-des-urls)

---

## 1. Architecture générale

Le site est organisé en **syndicats** (appelés `SectionPage` en interne). Chaque syndicat est une entité autonome avec ses propres articles, pages, menus, abonnés et événements.

**Trois types de syndicats :**

| Type | Label affiché | Description |
|------|--------------|-------------|
| `principal` | Site confédéral | Le site CNT-SO principal |
| `regional` | Union régionale | UR Île-de-France, UR Bretagne… |
| `sectoral` | Syndicat sectoriel | STUCS, SIPN… |

**Règle fondamentale :** tout contenu appartient à un syndicat. Un rédacteur ne voit et ne modifie que le contenu de son syndicat.

---

## 2. Rôles et droits

### Vue d'ensemble

| Fonctionnalité | Rédacteur | Rédacteur-en-chef | Superadmin |
|----------------|:---------:|:-----------------:|:----------:|
| Accès au CMS | ✓ | ✓ | ✓ |
| Créer un article | ✓ (son syndicat) | ✓ (son syndicat) | ✓ (tous) |
| Modifier un article | ✓ (son syndicat) | ✓ (son syndicat) | ✓ (tous) |
| Supprimer un article | ✗ | ✓ | ✓ |
| Publier / dépublier | ✓ | ✓ | ✓ |
| Créer une page de contenu | ✓ | ✓ | ✓ |
| Gérer les catégories | ✗ | ✓ | ✓ |
| Gérer l'agenda | ✓ (voir) | ✓ | ✓ |
| Gérer les menus | ✗ | ✓ | ✓ |
| Gérer la newsletter | ✗ | ✓ | ✓ |
| Gérer les abonnés | ✗ | ✓ | ✓ |
| Listes mails OVH | ✗ | ✓ (sa liste) | ✓ (toutes) |
| Gérer les adhésions | ✗ | ✓ | ✓ |
| Changer de syndicat actif | ✗ | ✓ | ✓ |
| Modifier les paramètres syndicat | ✗ | ✓ (son syndicat) | ✓ (tous) |
| Gérer tous les syndicats | ✗ | ✗ | ✓ |
| Créer des utilisateurs | ✗ | ✗ | ✓ |
| Accès à l'admin Django (`/admin/`) | ✗ | ✗ | ✓ |

### Détail par rôle

#### Rédacteur (`redacteur`)

Compte de base destiné aux membres qui contribuent du contenu.

- **Portée :** son syndicat uniquement, défini par son profil auteur (`Author.site`)
- **Peut :** créer et modifier des articles et pages de contenu, uploader des images et documents
- **Ne peut pas :** supprimer du contenu, gérer les catégories, les menus, la newsletter, les adhésions, changer de syndicat actif
- **Champ `section_slug`** sur ses articles : verrouillé automatiquement sur son syndicat (champ caché)

#### Rédacteur-en-chef (`redacteur_en_chef`)

Compte de gestion pour les responsables numériques d'un syndicat.

- **Portée :** son syndicat courant (changeable via le sélecteur en haut du CMS)
- **Peut :** tout ce que fait le rédacteur + supprimer, gérer catégories, menus, newsletter, abonnés, liste mail OVH de son syndicat, adhésions, paramètres du syndicat
- **Ne peut pas :** créer des utilisateurs, accéder aux autres syndicats sans y être assigné, accéder à l'admin Django

#### Superadmin

Compte technique avec accès total.

- **Portée :** tous les syndicats
- **Peut :** tout, y compris créer des utilisateurs, gérer tous les syndicats, accéder à `/admin/`, voir toutes les listes OVH
- **Sélecteur de syndicat :** peut basculer vers n'importe quel syndicat

---

## 3. Créer et gérer un compte utilisateur

> ⚠️ Réservé aux superadmins.

### Créer un compte

1. Aller sur `/cms/users/` (menu **Paramètres** → **Utilisateurs** dans la barre latérale Wagtail)
2. Cliquer sur **Ajouter un utilisateur**
3. Remplir : nom d'utilisateur, prénom, nom, email, mot de passe
4. **Rôles :** cocher le groupe correspondant dans la section "Rôles"
   - `redacteur` → rédacteur de base
   - `redacteur_en_chef` → responsable numérique
   - Aucun groupe + "Statut superutilisateur" → superadmin
5. Sauvegarder

### Assigner un rédacteur à un syndicat

Un rédacteur est lié à un syndicat via son **profil auteur** :

1. Aller sur `/cms/snippets/content/author/`
2. Trouver ou créer le profil auteur correspondant à l'utilisateur
3. Dans le champ **Site**, sélectionner le syndicat
4. Lier le champ **Utilisateur** au compte Django de la personne
5. Sauvegarder

> Un rédacteur-en-chef n'a pas besoin de profil auteur — son syndicat actif est géré par la session.

---

## 4. Naviguer dans le CMS

**URL d'accès :** `https://newsite.cnt-so.org/cms/`

### Sélecteur de syndicat

En haut de chaque page du CMS, une barre permet de choisir le syndicat actif. Tous les contenus affichés sont filtrés selon ce choix.

- **Rédacteur-en-chef :** peut basculer entre les syndicats auxquels il a accès
- **Rédacteur :** pas de sélecteur — son syndicat est fixe

### Structure du menu latéral

```
Tableau de bord
│
├── Contenu
│   ├── Articles
│   ├── Pages
│   ├── Catégories
│   └── Agenda
│
├── Articles & Pages (legacy)    ← ancien système, ignorer
│
├── Newsletter
│   ├── Newsletters
│   └── Abonnés
│
├── Contact
│   ├── Messages reçus
│   └── Config formulaire
│
├── Modération
│   └── Commentaires
│
├── Adhésions
│   ├── Adhésions
│   ├── Formulaires
│   └── Zones géographiques
│
├── Navigation
│   └── Menus
│
├── Structure du site
│   └── Mon syndicat
│
└── Syndicats                    ← superadmin uniquement
```

---

## 5. Articles

### Créer un article

**Chemin :** `CMS → Contenu → Articles → + Ajouter`  
**URL directe :** `/cms/snippets/cms/articlepage/add/`

**Champs obligatoires :**
- **Titre** — apparaît en titre de page et dans les listings
- **Section** — rempli automatiquement selon le syndicat actif (ou verrouillé pour les rédacteurs)

**Onglet Métadonnées :**

| Champ | Description | Qui peut le voir |
|-------|-------------|-----------------|
| Section (slug) | Syndicat auquel appartient l'article | Chef (modifiable) / Rédacteur (caché, auto) |
| Date de publication | Date affichée sur le site | Tous |
| Mis en avant | Apparaît dans la sélection de la homepage confédérale | Tous |
| Mis en avant (confédéral) | Apparaît dans le bloc confédéral du site principal | Chefs uniquement |
| En carrousel | Apparaît dans le carrousel de la homepage du syndicat sectoriel | Tous (syndicats secto.) |
| Résumé | Texte court affiché dans les listings | Tous |
| Image à la une | Photo principale de l'article | Tous |
| Catégories | Tags thématiques (filtrés par syndicat) | Tous |
| Tags | Mots-clés libres | Tous |

**Onglet Contenu :**
- Éditeur riche (Draftail) — texte, titres, listes, liens, images, documents

### Publier / dépublier

- **Publié** = visible sur le site (`live = true`)
- **Brouillon** = invisible (`live = false`)
- Bouton **Publier** / **Dépublier** en bas du formulaire

### Modifier un article existant

**Chemin :** `CMS → Contenu → Articles` → cliquer sur le titre  
**URL directe :** `/cms/snippets/cms/articlepage/`

### Supprimer un article

> Disponible pour les chefs et superadmins uniquement.

Dans la liste des articles → icône poubelle à droite de la ligne, ou bouton **Supprimer** en bas du formulaire d'édition.

---

## 6. Pages de contenu

Pages statiques du syndicat (ex. "Qui sommes-nous", "Nous contacter").

**Chemin :** `CMS → Contenu → Pages`  
**URL directe :** `/cms/snippets/cms/contentpage/`

**Champs :**
- Titre
- Section (slug) — même logique que les articles
- Auteur (nom libre)
- Image à la une
- Corps (éditeur riche)

Les pages sont accessibles sur le site via `/{site_slug}/pages/{slug}/`.

---

## 7. Catégories

Permettent de classer les articles par thème. Chaque catégorie appartient à un syndicat.

**Chemin :** `CMS → Contenu → Catégories`  
**URL directe :** `/cms/snippets/cms/cmscategory/`

> Réservé aux rédacteurs-en-chef et superadmins.

**Champs :**
- Nom
- Slug (généré automatiquement)
- Section (slug) — syndicat propriétaire
- Catégorie parente (optionnel, pour une hiérarchie)

---

## 8. Agenda / Événements

**Chemin :** `CMS → Contenu → Agenda`  
**URL directe :** `/cms/snippets/cms/event/`

**Créer un événement :**

| Champ | Description |
|-------|-------------|
| Syndicat | Le syndicat organisateur |
| Titre | Nom de l'événement |
| Date de début | Date au format JJ/MM/AAAA |
| Date de fin | Optionnel |
| Heure | Optionnel |
| Lieu | Adresse ou nom du lieu |
| Latitude / Longitude | Remplis automatiquement via l'autocomplétion du champ Lieu |
| Description | Texte libre |
| URL | Lien externe vers plus d'info (optionnel) |

**Géocodage automatique :** en tapant une adresse dans le champ **Lieu**, une liste de suggestions apparaît (API adresse.data.gouv.fr). Cliquer sur une suggestion remplit automatiquement latitude et longitude — l'événement apparaîtra alors sur la carte de la page agenda.

**Affichage sur le site :** page agenda du syndicat → `/{site_slug}/agenda/`  
- Événements à venir affichés avec carte interactive
- Événements passés dans une section dédiée

---

## 9. Menus de navigation

**Chemin :** `CMS → Navigation → Menus`  
**URL directe :** `/cms/menus/`

> Réservé aux rédacteurs-en-chef et superadmins.

### Types de menus

| Type | Emplacement sur le site |
|------|------------------------|
| `main` | Menu principal (en-tête) |
| `footer` | Pied de page |
| `secondary` | Menu secondaire (si applicable) |

### Gérer les éléments

Depuis la page menus, chaque élément peut être :
- **Monté / descendu** (flèches ↑↓) pour changer l'ordre
- **Indenté / désindent** pour créer des sous-menus
- **Supprimé**

### Types d'éléments de menu

Un item de menu peut pointer vers :
- Une **URL externe** (ex. `https://cnt-so.org`)
- Une **catégorie** du syndicat
- Une **page de contenu** du syndicat
- Un **article** spécifique
- Un **autre syndicat** (lien vers son site)

---

## 10. Newsletter

### Créer une newsletter

**Chemin :** `CMS → Newsletter → Newsletters → + Ajouter`  
**URL directe :** `/cms/snippets/content/newsletter/add/`

> Réservé aux rédacteurs-en-chef et superadmins.

**Champs :**
- **Sujet** — objet de l'email
- **Texte d'introduction** — paragraphe introductif
- **Articles sélectionnés** — choisir les articles à inclure (ordonnables)

### Envoyer une newsletter

1. Dans la liste des newsletters, cliquer sur la newsletter
2. Bouton **Envoyer** (visible uniquement si statut = Brouillon)
3. Page de confirmation — deux modes :

**Mode OVH** (liste mail configurée sur le syndicat) :
- Encadré jaune avec l'adresse de la liste et le nombre d'abonnés
- Un seul email envoyé → OVH redistribue à tous
- Bouton : **Envoyer via OVH → actu-stucs-cntso@cnt-so.info**

**Mode direct** (pas de liste OVH configurée) :
- Envoi email par email à chaque abonné confirmé en base
- Bouton : **Envoyer à N abonné(s)**

**Envoi de test :** envoyer à une adresse de test avant l'envoi réel (panneau de gauche).

> ⚠️ L'envoi est irréversible. Une newsletter envoyée ne peut pas être renvoyée (statut passe à "Envoyée").

### Gérer les abonnés

**Chemin :** `CMS → Newsletter → Abonnés`  
**URL directe :** `/cms/snippets/content/subscriber/`

- Liste des abonnés confirmés et en attente
- Filtrables par statut (confirmé / non confirmé)
- **Export CSV** : `CMS → Newsletter → Abonnés → Exporter CSV` ou `/cms/abonnes/export/`

### Flux d'abonnement côté visiteur

```
Visiteur remplit le formulaire d'abonnement sur le site
        ↓
Email de confirmation envoyé automatiquement
        ↓
Visiteur clique sur le lien dans l'email
        ↓
Abonné confirmé (is_active = true)
        ↓ signal automatique
Ajouté à la liste OVH si configurée
```

---

## 11. Listes mails OVH

Documentation complète : `docs/newsletter-ovh-guide.md`

**Chemin :** `CMS → Newsletter → Listes mails OVH`  
**URL directe :** `/cms/mailing-lists/`

### Accès

| Rôle | Accès |
|------|-------|
| Superadmin | Toutes les listes du domaine cnt-so.info |
| Rédacteur-en-chef | Uniquement la liste de son syndicat courant |
| Rédacteur | Aucun accès (403) |

### Lier une liste OVH à un syndicat

1. `CMS → Structure du site → Mon syndicat` → éditer le syndicat
2. Champ **Liste mail OVH** : saisir le nom **sans** `@cnt-so.info`
   - ✓ `actu-stucs-cntso`
   - ✗ `actu-stucs-cntso@cnt-so.info`
3. Sauvegarder

### Synchronisation automatique

Quand un visiteur confirme son abonnement → ajouté automatiquement à la liste OVH du syndicat.

> ⚠️ La désabonnement via le lien dans la newsletter retire l'abonné de la base du site mais **pas** de la liste OVH. Retirer manuellement depuis `/cms/mailing-lists/<nom>/` si nécessaire.

---

## 12. Adhésions

> Module disponible uniquement si le formulaire d'adhésion est activé pour le syndicat.

### Configurer le formulaire d'adhésion

**Chemin :** `CMS → Adhésions → ⚙️ Formulaire d'adhésion`  
**URL directe :** `/cms/adhesion-config/`

Options configurables :
- Activer/désactiver le formulaire
- Montants des cotisations (multiple paliers possibles)
- Champs personnalisés supplémentaires
- Zones géographiques (pour les formulaires régionaux)

### Consulter les adhésions

**Chemin :** `CMS → Adhésions → Liste des adhésions`  
**URL directe :** `/cms/adhesions/`

**Statuts possibles :**

| Statut | Description |
|--------|-------------|
| `pending` | Paiement en attente |
| `actif` | Adhésion confirmée et payée |
| `inactif` | Adhésion expirée ou annulée |

**Export CSV :** `/cms/adhesions/export/`

**Relance :** `/cms/adhesions/relance/` — envoyer un rappel aux adhésions en attente.

---

## 13. Formulaire de contact

### Configurer le formulaire

**Chemin :** `CMS → Contact → Config formulaire`  
**URL directe :** `/cms/contact-config/`

Options :
- Activer/désactiver le formulaire
- Ajouter des champs personnalisés (texte, choix, case à cocher…)
- Email destinataire des messages

### Consulter les messages

**Chemin :** `CMS → Contact → Messages reçus`  
**URL directe :** `/cms/snippets/content/contactmessage/`

Les messages non lus sont signalés par un badge rouge sur le tableau de bord.

---

## 14. Mon syndicat (paramètres)

**Chemin :** `CMS → Structure du site → Mon syndicat`  
**URL directe :** `/cms/snippets/cms/sectionpage/`

> Rédacteur-en-chef : son syndicat uniquement. Superadmin : tous les syndicats.

### Onglets disponibles

**Informations générales :**
| Champ | Description |
|-------|-------------|
| Titre | Nom du syndicat affiché sur le site |
| Slug | Identifiant URL (`/stucs/`, `/ur-idf/`…) |
| Type | Confédéral / Union régionale / Syndicat sectoriel |
| Description | Sous-titre affiché dans l'en-tête |
| Logo | Image du logo (format recommandé : carré, PNG/WebP) |
| Email de contact | Destinataire des messages du formulaire de contact |

**Contenu éditorial :**
| Champ | Description |
|-------|-------------|
| Texte d'intro | Paragraphe d'introduction de la homepage |
| Texte rejoindre | Texte de la page "Nous rejoindre" |
| Texte agenda | Introduction de la page agenda |
| Texte ressources | Introduction de la page ressources |
| URL Framaforms | Lien vers le formulaire d'adhésion externe (si pas de module adhésion) |
| URL Linkstack | Lien vers la page Linkstack du syndicat |

**Réseaux sociaux :**
- Mastodon, Bluesky, Twitter/X, Facebook, Instagram, LinkedIn, YouTube

**Newsletter OVH :**
- Champ **Liste mail OVH** : nom de la liste sur cnt-so.info (sans `@cnt-so.info`)

**SEO :**
- Titre SEO, description meta, image OG

---

## 15. Syndicats — gestion globale (superadmin)

**Chemin :** `CMS → Syndicats`  
**URL directe :** `/cms/syndicats/`

Vue d'ensemble de tous les syndicats avec statistiques (articles, abonnés) et liens d'accès rapide.

### Créer un nouveau syndicat

1. `/cms/syndicats/` → bouton **Nouveau syndicat**
2. Remplir les informations (titre, slug, type)
3. Le syndicat apparaît dans le sélecteur dès la création

### Slug hérité WordPress (`legacy_site_slug`)

Champ technique visible uniquement en édition avancée. Permet de faire correspondre un syndicat avec l'ancien identifiant WordPress pour les redirections et le filtrage des articles importés.

---

## 16. Images et documents

### Uploader une image

- Lors de la création d'un article, cliquer sur le champ **Image à la une** → **Choisir une image** → **Uploader**
- Ou depuis la médiathèque Wagtail : barre latérale → **Images**

**Formats acceptés :** JPEG, PNG, WebP, GIF  
**Recommandation :** 1200×800px minimum pour les images à la une

### Uploader un document

- Dans l'éditeur de contenu → bouton **Document** → **Insérer un document**
- Ou depuis la barre latérale → **Documents**

**Formats acceptés :** PDF, DOCX, ODT, XLSX, ZIP…

---

## 17. Référence des URLs

### CMS (administration)

| Section | URL |
|---------|-----|
| Tableau de bord | `/cms/` |
| Articles | `/cms/snippets/cms/articlepage/` |
| Nouvel article | `/cms/snippets/cms/articlepage/add/` |
| Pages de contenu | `/cms/snippets/cms/contentpage/` |
| Catégories | `/cms/snippets/cms/cmscategory/` |
| Agenda | `/cms/snippets/cms/event/` |
| Menus | `/cms/menus/` |
| Newsletters | `/cms/snippets/content/newsletter/` |
| Abonnés | `/cms/snippets/content/subscriber/` |
| Export abonnés CSV | `/cms/abonnes/export/` |
| Listes mails OVH | `/cms/mailing-lists/` |
| Messages de contact | `/cms/snippets/content/contactmessage/` |
| Config contact | `/cms/contact-config/` |
| Adhésions | `/cms/adhesions/` |
| Config adhésion | `/cms/adhesion-config/` |
| Mon syndicat | `/cms/snippets/cms/sectionpage/` |
| Syndicats (global) | `/cms/syndicats/` |
| Utilisateurs | `/cms/users/` |
| Images | `/cms/images/` |
| Documents | `/cms/documents/` |
| Admin Django | `/admin/` |

### Site public

| Page | URL |
|------|-----|
| Accueil confédérale | `/` |
| Article confédéral | `/articles/{slug}/` |
| Accueil syndicat | `/{site_slug}/` |
| Article syndicat | `/{site_slug}/articles/{slug}/` |
| Agenda syndicat | `/{site_slug}/agenda/` |
| Page rejoindre | `/{site_slug}/rejoindre/` |
| Ressources | `/{site_slug}/ressources/` |
| Inscription newsletter | `/newsletter/inscription/` |
| Inscription newsletter syndicat | `/{site_slug}/newsletter/inscription/` |
| Désinscription newsletter | `/newsletter/desinscription/{token}/` |

---

## Annexes

### Serveur de production

```
SSH  : ssh debian@51.91.242.64
Dossier : /var/www/cntso/
Service  : sudo supervisorctl restart cntso
Logs     : tail -f /var/log/cntso.log
Env      : /var/www/cntso/cntso/local_settings.py
```

### Guide newsletter OVH

Voir `docs/newsletter-ovh-guide.md` pour la configuration complète des listes mails.

### Déploiement

Voir `!DEPLOIEMENT.md` à la racine du projet.
