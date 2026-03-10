# Publication automatique sur les réseaux sociaux

## Objectif
Quand un article est publié sur un sous-site, il est automatiquement posté
sur les comptes RS associés à ce site.

---

## Informations à collecter avant de coder

### CNT-SO Confédération (site principal)
- **Bluesky** : `cnt-so.bsky.social` ✅
  - [ ] App Password : Paramètres → App Passwords → Ajouter → copier le mot de passe
- **Telegram** : channel/groupe existant ?
  - [ ] Créer un bot via @BotFather → copier le token
  - [ ] Ajouter le bot au channel et récupérer le `chat_id`
- **Facebook** : page existante ?
  - [ ] URL de la page
  - [ ] Token (via Meta for Developers)
- **Instagram** : compte existant ?
  - [ ] Lié à la page Facebook ? (obligatoire pour l'API)
  - [ ] Token (même app Meta que Facebook)
- **X/Twitter** : ❌ API payante, on skip

### Syndicat du Numérique
- **Bluesky** : compte existant ? handle ?
  - [ ] App Password
- **Telegram** : channel existant ?
  - [ ] Token bot + chat_id
- **Facebook/Instagram** : comptes existants ?

### Autres sous-sites actifs
- [ ] Faire la même liste pour chaque sous-site qui a des RS

---

## Réseaux confirmés

| Réseau    | API              | Coût      | Faisabilité |
|-----------|------------------|-----------|-------------|
| Bluesky   | AT Protocol      | Gratuit   | ✅ Facile   |
| Telegram  | Bot API          | Gratuit   | ✅ Facile   |
| Facebook  | Meta Graph API   | Gratuit   | ⚠️ Moyen   |
| Instagram | Meta Graph API   | Gratuit   | ⚠️ Moyen   |
| X/Twitter | v2 API           | 100$/mois | ❌ Trop cher |

> **X/Twitter** : l'API de publication coûte 100$/mois minimum. À éviter sauf si vous avez le budget.

---

## Ce qui sera développé (une fois les credentials disponibles)

1. **Champs par site** dans le modèle `Site` (ou modèle `SiteSettings` lié) :
   - `bsky_handle`, `bsky_app_password`
   - `telegram_bot_token`, `telegram_chat_id`
   - `facebook_page_id`, `facebook_token`
   - `instagram_account_id` (lié à Facebook)

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

### Telegram
1. Ouvrir Telegram → chercher @BotFather
2. `/newbot` → suivre les instructions → copier le token
3. Ajouter le bot comme admin du channel
4. Récupérer le `chat_id` : envoyer un message dans le channel puis appeler
   `https://api.telegram.org/bot<TOKEN>/getUpdates`

### Facebook
1. developers.facebook.com → Créer une app
2. Ajouter le produit "Pages API"
3. Générer un token de page (longue durée)
— Plus complexe, à faire en dernier —
