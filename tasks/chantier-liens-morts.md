# Chantier : les liens morts

## 1. Anciennes adresses d'articles en 404 depuis la bascule — CORRIGÉ ET DÉPLOYÉ (14/09/2026, d0641d0)

Mesuré le 14/09/2026 de l'extérieur : sur les 680 articles du site principal
(plan du site), **46 répondent 404 à `cnt-so.org/<slug>/`**, dont **38 existaient
sous WordPress** à cette adresse (vérifié dans le miroir `old`) — presque tous de
2026, donc les plus partagés récemment.

Cause : les articles repris le 06/09/2026 sont rangés sous la section `principal`
(`/principal/<slug>/` répond 200) ; les anciens sont directement sous l'accueil,
où Wagtail sert encore `/<slug>/`.

Correctif : `AncienSlugArticleConverter` + `AncienneAdresseArticleView`
(content/urls.py, content/views.py) → 301 vers `/article/<slug>/`, seulement si
un article en ligne porte ce slug et que Wagtail ne sert rien à cette adresse.
Tests : `AncienneAdresseArticleTest` (cms/tests.py).

Contrôle après déploiement, de l'extérieur : **les 46 adresses répondent 301 vers
`/article/<même slug>/`, qui répond 200** ; 20 témoins tirés au sort parmi les 633
qui marchaient répondent toujours 200 sans redirection.

## 2. Liens morts dans les corps d'articles (base de dev, testés contre la prod)

169 adresses absolues `*.cnt-so.org` distinctes ; **94 ne répondent pas 200,
136 occurrences, ~100 pages**. Familles :

- **SPIP « propres »** `http://www.cnt-so.org/Titre-Tronque` (~45) : à relier par
  préfixe de slug vers l'article Wagtail (`Election-TPE-TPA-2021-profession` →
  `election-tpe-tpa-2021-profession-de-foi-de-la-cnt-so`) ;
- **SPIP numériques** `www.cnt-so.org/13/spip.php?articleNNN` (17) : aucune
  table id → titre connue, probablement irréparables ;
- **SPIP fichiers** `www.cnt-so.org/IMG/pdf/…` (9) : chercher le nom dans les
  documents rapatriés (voir chantier-fichiers-perdus) ;
- **WordPress** : catégories de sous-sites (`/auvergne/category/…`), pages
  disparues (`en-2022-on-sorganise`), 2 liens `educ.cnt-so.org` à slug encodé,
  2 adresses e-mail collées dans un href.

À remesurer en prod avant tout correctif.

### Commande `repare_liens_morts` (14/09/2026)

Simulation par défaut, `--appliquer`, `--rapport`. Ne traite que les liens qui
répondent **réellement** en erreur au moment où elle tourne. Familles réparées :
SPIP (préfixe de titre), WordPress (slug exact), catégories, fichiers SPIP
(documents rapatriés), courriels collés. 14 tests, 15 mutations détectées.

Simulation sur la base de dev : 92 adresses en erreur, **47 liens réparables sur
132**. Deux pièges trouvés en relisant le rapport, et corrigés :
- **titres SPIP numérotés** (`Nettoyage-grilles-des-salaires653`) : SPIP avait
  des homonymes, la date ne suffit pas à trancher → jamais reliés (6 écartés) ;
- **articles redatés par l'import SPIP → WordPress** : la profession de foi TPE
  est datée du 10/02/2021 mais citée le 14/11/2020 → tolérance de six mois
  (`DELAI_REDATATION`), qui a rendu 5 liens justes, dont celui de l'article TPE.
