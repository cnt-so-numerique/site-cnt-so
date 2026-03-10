# Publication automatique sur les réseaux sociaux

## Objectif
Quand un article est publié sur un sous-site, il est automatiquement posté
sur les comptes RS associés à ce site.

---

## Informations à collecter avant de coder

### CNT-SO Confédération (site principal)
- **Bluesky** : `cnt-so.bsky.social` ✅ (compte trouvé)
  - [ ] Générer un **App Password** : Paramètres → App Passwords → Ajouter
  - [ ] Noter le handle exact et l'app password
- **Mastodon** : compte existant ?
  - [ ] Instance (ex: kolektiva.social, social.coop…)
  - [ ] Générer un token : Paramètres → Développement → Nouvelle application
- **Facebook** : page existante ?
  - [ ] URL de la page
  - [ ] Token (via Meta for Developers — plus complexe)

### Syndicat du Numérique
- **Bluesky** : compte existant ? handle ?
  - [ ] App Password
- **Mastodon** : compte existant ?
- **Discord** : déjà configuré (lien existant dans le menu)
  - [ ] Webhook URL pour poster automatiquement dans un salon ?

### Autres sous-sites (Rhône-Alpes, STAA, etc.)
- [ ] Lister les comptes RS de chaque sous-site actif

---

## Réseaux supportés (et coût)

| Réseau   | API        | Coût    | Priorité |
|----------|------------|---------|----------|
| Bluesky  | AT Proto   | Gratuit | ★★★      |
| Mastodon | REST       | Gratuit | ★★★      |
| Facebook | Graph API  | Gratuit | ★★       |
| X/Twitter | v2 API   | 100$/mois | ✗ (skip) |
| LinkedIn | REST       | Gratuit | ★        |

---

## Ce qui sera développé (une fois les credentials disponibles)

1. **Champs par site** dans le modèle `Site` (ou modèle `SiteSettings` lié) :
   - `bsky_handle`, `bsky_app_password`
   - `mastodon_instance`, `mastodon_token`
   - `facebook_page_id`, `facebook_token`

2. **Signal Django** sur `Article.status → publish` :
   - Construit le message : titre + extrait + URL de l'article
   - Appelle les APIs des réseaux configurés pour ce site

3. **Interface dans `/redac/`** :
   - Formulaire par site pour saisir/modifier les tokens RS
   - Indication visuelle des réseaux actifs sur le dashboard

---

## Comment générer les credentials

### Bluesky
1. Connecte-toi sur bsky.app
2. Paramètres → App Passwords → Ajouter une application
3. Nom : "CNT-SO CMS", copier le mot de passe généré

### Mastodon
1. Connecte-toi sur ton instance
2. Préférences → Développement → Nouvelle application
3. Permissions nécessaires : `write:statuses`
4. Copier le token d'accès

### Facebook
1. developers.facebook.com → Créer une app
2. Ajouter le produit "Pages API"
3. Générer un token de page (longue durée)
— Plus complexe, à faire en dernier —
