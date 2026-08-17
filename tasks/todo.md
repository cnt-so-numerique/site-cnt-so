# Chantier — la page « Nous rejoindre » des sous-sites

Demandé par Arnaud le 17/08/2026, à partir de https://stucs.cnt-so.org/rejoindre/ :
« revoir cette page en la rendant modifiable et surtout mettre un bouton vers un
formulaire de contact et non mettre le formulaire dans la page ».

## Ce qui cloche aujourd'hui

1. **Le formulaire de contact est en dur dans la page.** Colonne droite de
   `templates/content/site_rejoindre.html` : champs, captcha, envoi. C'est un
   doublon exact de `/<slug>/contact/` — même formulaire dynamique, même
   destinataire, même `_send_contact_email`. Deux chemins à maintenir, et
   `SiteRejoindreView` traîne pour ça un `ContactFormMixin` et un `post()`.
2. **Rien n'est modifiable, ou presque.** Seul `rejoindre_text` l'est, et en
   tout ou rien : tant qu'il est vide, deux cartes écrites en dur s'affichent ;
   dès qu'un rédacteur y écrit un mot, elles disparaissent toutes les deux. Il
   ne voit donc jamais le texte qu'il est en train de remplacer. Sur 14 sites,
   un seul l'a rempli.
3. **Le bandeau « Adhérer » est entièrement figé** : titre, accroche, les trois
   puces, le libellé du bouton.

## Le plan

### A. Le formulaire devient un bouton

- [ ] `site_rejoindre.html` : la colonne droite garde son cartouche « Une
      question avant d'adhérer ? » mais son contenu devient un bouton vers
      `{% section_url 'content:site_contact' site %}`.
- [ ] `SiteRejoindreView` perd `ContactFormMixin` et sa méthode `post()` — la
      page redevient une simple vue en lecture.
- [ ] Le CSS `.rj-form-wrap` / `.success-box` devenu inutile est retiré.

### B. Le corps de la page devient vraiment modifiable

- [ ] Migration de données : pour chaque `SectionPage` dont `rejoindre_text`
      est vide, y écrire le contenu affiché aujourd'hui (les deux cartes, avec
      le nom du syndicat). **Rien ne change à l'écran**, mais le texte existe
      désormais dans `/cms/` et se modifie bloc par bloc.
- [ ] Le gabarit perd sa branche `{% else %}` : il ne rend plus que
      `rejoindre_text`.

### C. Le bandeau « Adhérer » devient modifiable

- [ ] Trois champs sur `SectionPage`, groupés avec `rejoindre_text` dans un
      `MultiFieldPanel` « Page Nous rejoindre » :
      - `rejoindre_accroche` (CharField) — la phrase sous le titre
      - `rejoindre_atouts` (TextField, une ligne = une puce)
      - `rejoindre_bouton` (CharField, défaut « Adhérer maintenant »)
- [ ] La même migration les remplit avec les libellés actuels. Vidés
      volontairement, l'accroche et les puces disparaissent ; le bouton, lui,
      garde son libellé par défaut pour ne jamais casser le parcours d'adhésion.

### D. Tests

- [ ] `test_contact_form_present` → vérifie le **lien** vers `/stucs/contact/`.
- [ ] Les deux tests POST sont remplacés par un test « la page ne reçoit plus
      de POST » et un test « aucun `ContactMessage` créé depuis cette URL ».
- [ ] Nouveau test : un syndicat qui réécrit `rejoindre_text` voit son texte,
      et lui seul.
- [ ] Nouveau test : `rejoindre_bouton` vidé retombe sur le libellé par défaut.

## Hors périmètre

Le titre `<h1>` « Nous rejoindre » et le libellé du cartouche de droite restent
en dur : ils nomment la page et sont repris dans le menu et la barre latérale,
les laisser diverger par site créerait plus de confusion que de liberté.

## Revue — 17/08/2026

Fait, **1 018 tests verts**. Trois pièges rencontrés :

1. **Les révisions Wagtail auraient avalé le semis.** L'éditeur ouvre la page
   via `get_latest_revision_as_object()`, pas la ligne en base : semer
   `rejoindre_text` sans toucher à la révision aurait donné un champ vide à
   l'écran de rédaction, et le texte aurait disparu à la première modification
   de la fiche. La migration 0027 corrige donc la ligne **et** la révision la
   plus récente. Vérifié : `/cms/pages/<pk>/edit/` affiche bien le texte semé.
2. **Les trois champs du bandeau n'ont pas ce problème** : absents des
   révisions existantes, c'est le `default=` du modèle qui parle. D'où le choix
   de vrais défauts plutôt qu'un repli dans le gabarit — le rédacteur voit le
   texte qu'il peut changer.
3. **Le rendu devait rester identique au mot près.** Les puces fléchées de
   `.rj-list` sont reprises par `.rj-info-card ul li`, sinon le texte migré
   serait passé aux puces rondes du navigateur. Contrôlé dans le navigateur :
   fond `#F1F1F1`, bordure 1 px, flèche `→` en rouge de charte `#E81C24`.

Différence assumée : le syndicat Éducation, seul à avoir déjà rempli
`rejoindre_text`, gagne l'encadré gris que son texte n'avait pas — cohérent
avec les treize autres.
