# Chantier — l'inscription newsletter servait de relais à courriels

Ouvert et refermé le 17/08/2026, parti d'une question d'Arnaud : « il y a
env. 1200 abonnés, ils sortent d'où ? »

## Ce qu'on a trouvé

Ils ne sortaient de nulle part. Du **24/07 au 17/08/2026**, un botnet a posté
50 à 115 fois par jour sur `/newsletter/inscription/` depuis **25 adresses IP**
(plages d'hébergeurs américains, `User-Agent` bidon qui tournent, référents
variables). Sur 2 103 lignes en base, **2 099 venaient de là** ; seules 4
étaient antérieures.

`NewsletterSubscribeView.post` lisait `request.POST` directement : ni
formulaire, ni captcha, ni limite, ni champ piège. Chaque requête créait
l'abonné **et envoyait un courriel de confirmation à l'adresse postée**. Le
site servait donc de relais à du *list bombing* : ~2 000 boîtes tierces
bombardées depuis les serveurs de la CNT-SO, avec le risque de blacklistage de
l'envoi OVH dont dépend la vraie newsletter.

Les 188 « confirmés » n'étaient pas des consentements : **0 adresse en .fr**,
0 nom renseigné, **127 confirmations en moins de 60 secondes**, sur des
domaines d'entreprises (`agila.de`, `paki-logistics.com`, `vpcgroup.com`…).
Ce sont les passerelles antispam de ces entreprises qui ont déroulé le lien.

## Ce qui a été fait

**L'inscription passe en deux temps.** Le formulaire public — présent sur
l'accueil, chaque article et trois barres latérales — ne crée plus rien : il
mène à `newsletter_subscribe_verify.html`, qui porte le hCaptcha, et
**seule cette page inscrit et envoie**. Le captcha n'est pas dans le formulaire
lui-même parce que son script se serait alors chargé sur tout le site.

S'y ajoutent un **champ piège** (`site_web`) dans les quatre formulaires
publics et une **limite de 3 inscriptions/heure/IP**. Cette limite s'appuie sur
un cache `limites` (`DatabaseCache`) **partagé entre les workers gunicorn** :
dans le cache local par défaut elle en aurait valu 9 et serait repartie de zéro
à chaque redémarrage.

**Purge** : 2 100 lignes supprimées, 4 gardées. Export préalable dans
`/var/www/cntso/logs/abonnes_avant_purge_20260817.json`.

**Nettoyage OVH** : un abonné confirmé est poussé sur la liste OVH par un
signal (`cms/apps.py`), et une suppression en base ne le retire pas. 128
adresses de robots y étaient parties — 85 sur `news`, 43 sur `auvergne` — et
ont été retirées. `news` : 5 000 → 4 915. `auvergne` : 60 → 17.

## Les listes OVH, ce qu'il faut savoir

Les adresses ne vivent **pas** dans la base du site mais chez OVH, service
« mailing lists » du domaine **cnt-so.info** (50 listes). Manager OVH :
Web Cloud → Emails → cnt-so.info → Mailing lists.

**Trois pièges, tous vérifiés le 17/08/2026 :**

1. **`nbSubscribers` ment.** OVH ne le recalcule qu'épisodiquement :
   `nbSubscribersUpdateDate` de la liste `news` datait du **16 janvier 2023**.
   Il annonçait 1 260 abonnés là où l'énumération en trouve 5 000, et 0 pour
   `news2` qui en compte 980. Toujours énumérer
   (`/mailingList/<nom>/subscriber`), jamais lire le compteur.
2. **Plafond dur de 5 000 abonnés par liste.** `news` y était, donc pleine —
   erreur API explicite : « Maximum subscribers quota reached ». Or
   `pick_list` lisait le compteur périmé, croyait la liste disponible, et
   chaque ajout échouait en silence (`except` avalant l'erreur) : **la
   newsletter ne pouvait plus gagner un seul abonné**. Corrigé.
3. **Les opérations sont asynchrones.** Un ajout ou un retrait est pris en
   compte avec un délai (constaté : une minute). Ne pas conclure sur une
   lecture immédiate — c'est ce qui m'a fait croire à tort à un bug
   d'encodage dans `remove_subscriber`.

## L'état des listes confédérales

| Liste | Rôle | Adresses |
|---|---|---|
| `news` | héritée de l'ancien site, **pleine** | 4 915 |
| `news2` | débordement de `news` | 980 |
| `news3` | **inscrits venus du site** (créée le 17/08/2026) | 0 |

La newsletter part aux trois (`ovh_mailing_list = news,news2,news3`). Les
nouvelles inscriptions atterrissent sur `news3` seule, via le nouveau champ
`ovh_liste_inscription` — pour tenir le consentement vérifié à part des
milliers d'adresses héritées dont on ne connaît ni l'origine ni l'accord.
Chaîne vérifiée de bout en bout le 17/08/2026.

## Reste à faire

- **Vérifier auprès d'OVH** que trois semaines d'envois vers des boîtes
  tierces n'ont pas abîmé la réputation du compte d'envoi.
- L'observation grandeur nature du blocage attend la prochaine tentative du
  botnet : il s'est tu à 12h58, vingt minutes avant le déploiement. Le
  mécanisme, lui, est prouvé — leur geste exact rejoué en production ne crée
  plus rien.
