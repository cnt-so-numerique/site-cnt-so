# Chantier — la newsletter atterrit dans les indésirables

Ouvert le 18/08/2026, à partir d'un signalement d'Arnaud et des en-têtes
complets d'un message classé en indésirable par Gmail.

## Ce que les en-têtes disent

L'authentification n'est **pas** en cause :

```
dkim=pass    header.d=cnt-so.org  s=ovhmo3700625-selector1
spf=pass     smtp.mailfrom=newsletter@cnt-so.org  (178.32.123.152, OVH)
dmarc=pass   (p=NONE)
```

Le DKIM existe donc bel et bien — mes sondages de sélecteurs usuels ne
pouvaient pas deviner `ovhmo3700625-selector1`. **Ne rien activer chez OVH.**

Le message examiné était par ailleurs le **courriel de confirmation
d'inscription**, pas la newsletter, et il part en direct par `ssl0.ovh.net`
sans passer par la liste OVH.

## Les quatre défauts trouvés

1. **Le lien « Se désabonner » répondait 405.** Le pied de chaque newsletter
   pointait vers `/newsletter/inscription/`, une vue en POST seul. Vérifié en
   production. Sans porte de sortie, le seul geste qui reste au lecteur est
   « signaler comme indésirable » — le signal le plus lourd qui soit, et il
   s'auto-entretient d'un envoi à l'autre.
2. **`Message-ID: <…@cnt-so>`.** Django le fabrique depuis le nom d'hôte de la
   machine, et `getfqdn()` renvoie `cnt-so` en production : pas un domaine
   valide, motif de filtrage classique.
3. **`From` nu et aucun `Reply-To`.** `cntso/local_settings.py:48` écrasait le
   `CNT-SO <newsletter@cnt-so.org>` de `settings.py` par l'adresse seule.
4. **Réputation d'envoi abîmée** par les trois semaines de bombardement
   (24/07 → 17/08, ~2 000 boîtes tierces). C'est très probablement le facteur
   dominant, et le seul qu'aucun correctif ne répare d'un coup : il se
   reconstruit sur plusieurs semaines d'envois propres.

## Ce qui a été fait

- **Page de désabonnement** `/newsletter/desabonnement/` (et par sous-site).
  Sans jeton : la newsletter part en un message unique vers les listes, il n'y
  a donc pas de lien personnalisé possible. On saisit son adresse, elle est
  retirée des listes OVH (`ovh_unsubscribe`) et la ligne locale est désactivée.
  **Pas de captcha** : chaque obstacle sur le chemin de la sortie se paie en
  signalements. Une limite de 20/heure/IP protège d'un script — et quand elle
  est atteinte, on **le dit** au lieu d'annoncer un retrait qui n'a pas eu lieu.
- **`List-Unsubscribe`** ne porte plus que cette URL. L'adresse
  `<liste>-unsubscribe@cnt-so.info` annoncée jusqu'ici est une convention
  Mailman, jamais vérifiée chez OVH ; un bouton qui échoue en silence est pire
  que pas de bouton. L'en-tête est aussi posé sur l'envoi abonné par abonné,
  qui n'en avait aucun.
- **`Message-ID`** : `EMAIL_MESSAGE_ID_DOMAIN` (défaut `cnt-so.org`), appliqué
  dans `content.apps._fixer_le_domaine_des_message_id`. Le domaine d'envoi est
  une décision applicative, pas un accident d'hébergement.
- **`Reply-To`** : `NEWSLETTER_REPLY_TO` (défaut `contact@cnt-so.org`) sur la
  confirmation d'inscription et sur les trois chemins d'envoi.

**1 026 tests verts.**

## Reste à faire

- **Rétablir le `From` avec nom affiché** en production : une ligne de
  `cntso/local_settings.py`, fichier hors dépôt.
- **Vérifier auprès d'OVH** si `<liste>-unsubscribe@cnt-so.info` existe. Si
  oui, on peut le remettre en second dans `List-Unsubscribe`.
- **Pas de désabonnement en un clic (RFC 8058).** Il exige une URL qui
  identifie le destinataire sans interaction — impossible avec un message
  unique envoyé à une liste. Le rendre possible supposerait d'envoyer abonné
  par abonné : 5 900 adresses à 18 s d'intervalle, soit ~30 h. À arbitrer.
- **Surveiller la réputation** : Google Postmaster Tools sur cnt-so.org
  donnerait la courbe, et le `rua=newsletter@cnt-so.org` du DMARC reçoit déjà
  les rapports agrégés.
