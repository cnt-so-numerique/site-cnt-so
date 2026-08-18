# Chantier — fiches pratiques et tracts à afficher

18/08/2026. Parti d'une demande d'Arnaud : intégrer un article sur le forfait
jours dans les ressources du syndicat Numérique, puis « fabriquer un format
d'article de fiche pratique que les gens peuvent aussi télécharger en format
tract pour afficher dans leur boîte ».

## L'article

Le texte venait d'une page HTML autonome. Plutôt que de la déposer dans un bloc
« HTML brut » — illisible et intouchable pour un rédacteur — elle est découpée
en **12 blocs du CMS** : titres, listes, encadrés. Seul le tableau des positions
reste en HTML, le texte riche du site ne connaissant pas les tableaux.

Le syndicat Numérique n'avait que deux catégories, « Banque d'images » et
« Non classé ». La commande crée **« Nos droits »** (`droit`), du même nom que
sur la confédération, et y classe l'article.

Import : `python manage.py cree_article_forfait_jours [--dry-run]`, idempotente.

## Le format « fiche pratique »

Une case **`fiche_pratique`** sur `ArticlePage`, dans l'onglet Contenu. Cochée,
elle ajoute sous l'article un encart « Affiche-la au travail » et un bouton
« Télécharger le tract », et ouvre la route
`/<syndicat>/article/<slug>/tract/`. Décochée, cette adresse répond 404 —
sinon chaque brève aurait une adresse fantôme.

Valable pour **tous les articles de tous les syndicats**.

## Le tract

**En couleur** (arbitrage d'Arnaud : « si les gens veulent les imprimer en n&b
ils choisiront »). Bandeau rouge en tête, titres de section en rouge sombre,
pied en aplat rouge. `print-color-adjust: exact` est indispensable : sans lui,
les navigateurs suppriment les aplats et le tract sort blanc.

**Deux pages maximum**, jamais plus — « au-delà ce n'est plus un tract mais une
brochure ». Toutes les tailles sont en `em`, relatives au corps de la feuille,
et un script réduit ce corps par paliers de 0,2 pt jusqu'à ce que la fiche
tienne. Plancher à 7,5 pt : en dessous, la rédaction est prévenue dans la barre
d'outils plutôt que de recevoir un tract illisible.

⚠️ **Le calage se mesure sur la géométrie A4 forcée** (classe `.feuille.mesure`),
jamais sur celle de l'écran : mesuré dans la mise en page mobile, il figeait une
taille fausse pour l'impression. Défaut trouvé et corrigé le jour même.

**Allégé des références.** `ArticleTractView.TITRES_EXCLUS` écarte les blocs qui
s'ouvrent sur un titre « Sources », « Références », « Mentions légales »… Elles
restent sur l'article en ligne : elles font sa crédibilité, pas celle d'une
affiche. La comparaison porte sur le titre seul, normalisé — « Sourcing et
recrutement » n'est pas écarté, ni un paragraphe qui commence par « Sources : ».

**Le pied nomme le syndicat et donne le contact** : `contact_email` du syndicat,
à défaut celui de la confédération. Un tract sans contact ne sert à rien.

Résultat pour la fiche « Forfait jours » : **1,77 page**, sans réduction.

## Le « téléchargement »

Aucune bibliothèque PDF n'est installée, et en ajouter une ferait entrer des
dépendances système (cairo, pango) sur le serveur pour un seul usage. Le bouton
« Imprimer / Enregistrer en PDF » ouvre la fenêtre d'impression, dont la
fonction « Enregistrer au format PDF » est native partout. Le fichier obtenu est
un PDF comme un autre. Servir un vrai fichier depuis le site reste possible :
c'est une décision d'installation, à prendre séparément.
