/*
 * Le défilement automatique d'un carrousel, et tout ce qui va avec.
 *
 * Deux carrousels existent — l'accueil confédéral et celui des syndicats —,
 * écrits séparément. Leur défilement a été demandé le 17/09/2026 ; l'écrire
 * deux fois, c'était deux occasions de rater une des règles d'accessibilité.
 *
 * WCAG 2.2.2 (niveau A) : un contenu qui bouge seul plus de cinq secondes doit
 * pouvoir être arrêté. D'où, ici et pour les deux : un bouton pause, l'arrêt au
 * survol et quand le clavier entre dans le carrousel, l'arrêt quand l'onglet
 * passe en arrière-plan, et rien du tout si le système demande de limiter les
 * animations.
 *
 * Usage :
 *   var auto = carrouselAuto({
 *       section: leConteneurQuiPrendLeFocus,
 *       survol:  laZoneSurvolee,           // facultatif, défaut : section
 *       avance:  function () { ... },      // passer au visuel suivant
 *       bouton:  leBoutonPause,            // facultatif mais attendu
 *       delai:   3000                      // facultatif
 *   });
 *   auto.relance();   // après un clic sur une flèche : repartir du plein délai
 */
(function (global) {
    'use strict';

    var LIBELLE_PAUSE = 'Mettre le défilement en pause';
    var LIBELLE_REPRISE = 'Reprendre le défilement';
    var SIGNE_PAUSE = '❚❚';   // deux barres
    var SIGNE_LECTURE = '▶';       // triangle

    global.carrouselAuto = function (options) {
        var section = options.section;
        var survol = options.survol || section;
        var avance = options.avance;
        var bouton = options.bouton || null;
        // 3 s par visuel, à l'essai (Arnaud, 24/09/2026 ; 6 s auparavant).
        // Le bouton pause, l'arrêt au survol et au clavier restent ce qui rend
        // un défilement automatique acceptable (WCAG 2.2.2).
        var delai = options.delai || 3000;

        var minuterie = null;
        var arreteParLUtilisateur = false;
        var animationsReduites = global.matchMedia
            && global.matchMedia('(prefers-reduced-motion: reduce)').matches;

        function demarre() {
            if (animationsReduites || arreteParLUtilisateur || minuterie) return;
            minuterie = setInterval(avance, delai);
        }
        function arrete() {
            if (minuterie) { clearInterval(minuterie); minuterie = null; }
        }
        function relance() { arrete(); demarre(); }

        if (bouton && !animationsReduites) {
            bouton.hidden = false;
            bouton.addEventListener('click', function () {
                arreteParLUtilisateur = !arreteParLUtilisateur;
                if (arreteParLUtilisateur) {
                    arrete();
                    bouton.textContent = SIGNE_LECTURE;
                    bouton.setAttribute('aria-pressed', 'true');
                    bouton.setAttribute('aria-label', LIBELLE_REPRISE);
                    bouton.setAttribute('title', LIBELLE_REPRISE);
                } else {
                    bouton.textContent = SIGNE_PAUSE;
                    bouton.setAttribute('aria-pressed', 'false');
                    bouton.setAttribute('aria-label', LIBELLE_PAUSE);
                    bouton.setAttribute('title', LIBELLE_PAUSE);
                    demarre();
                }
            });
        }

        // Lire une manchette demande du temps : le survol et le clavier suspendent.
        if (survol) {
            survol.addEventListener('mouseenter', arrete);
            survol.addEventListener('mouseleave', demarre);
        }
        if (section) {
            section.addEventListener('focusin', arrete);
            section.addEventListener('focusout', demarre);
        }
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) { arrete(); } else { demarre(); }
        });

        demarre();
        return { relance: relance, arrete: arrete, demarre: demarre };
    };
})(window);
