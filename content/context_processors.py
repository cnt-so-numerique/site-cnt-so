from .models import Site, Category, Article


def menu_context(request):
    """Ajoute les données de menu à tous les templates"""

    # Site principal
    try:
        main_site = Site.objects.get(slug='principal')
    except Site.DoesNotExist:
        main_site = None

    # Tous les sous-sites
    subsites = Site.objects.filter(is_active=True).exclude(slug='principal')

    # Catégories du site principal pour le menu
    categories = {}
    if main_site:
        for cat in Category.objects.filter(site=main_site).order_by('name'):
            categories[cat.slug] = cat

    # Structure du menu principal
    menu_structure = {
        'confederation': {
            'title': 'La Confédération',
            'items': [
                ('reflexions', 'Réflexions'),
                ('orientations-presentation', 'Orientations – Présentation'),
                ('actualites-luttes', 'Actualités – luttes'),
            ]
        },
        'syndicats': {
            'title': 'Syndicats et fédérations',
            'items': [
                ('transport-logistique', 'Transport – logistique'),
                ('batiment-travaux-publics-bois-carrieres-materiaux', 'Bâtiment – TP – Bois'),
                ('commerce', 'Commerce'),
                ('hotellerie-restauration-tourisme', 'Hôtellerie – restauration'),
                ('industrie', 'Industrie'),
                ('nettoyage', 'Nettoyage'),
                ('numerique', 'Numérique'),
                ('sante-social', 'Santé & social'),
                ('education-recherche', 'Éducation & Recherche'),
                ('activites-postales-et-telecommunications', 'Activités postales et Télécom'),
                ('livreurs-travailleurs-euses-des-plateformes', 'Livreurs & plateformes'),
                ('services-a-la-personne', 'Services à la personne'),
                ('librairie', 'Librairie'),
                ('syndicat-des-travailleur-euse-s-artistes-auteurs-staa', 'STAA (Artistes-Auteurs)'),
                ('syndicat-des-travailleur%c2%b7euses-uni%c2%b7es-de-la-culture-et-du-spectacle-stucs', 'STUCS (Culture & Spectacle)'),
            ]
        },
        'autres': {
            'title': 'Autres',
            'items': [
                ('travailleurs-euses-sans-papiers', 'Travailleurs.euses sans-papiers'),
                ('banque-dimage', "Banque d'image"),
                ('droit', 'Droit'),
                ('international', 'International'),
                ('t-p-e', 'T.P.E'),
                ('solidarites', 'Solidarités'),
            ]
        }
    }

    # Sous-sites régionaux
    regional_sites = subsites.filter(site_type='regional')
    sectoral_sites = subsites.filter(site_type='sectoral')

    # Données sidebar partagées
    base_qs = Article.objects.filter(
        site=main_site, status='publish'
    ).select_related('featured_image').prefetch_related('categories') if main_site else Article.objects.none()

    campagnes_articles = base_qs.filter(
        categories__slug__in=['international', 'solidarites', 'campagne']
    ).distinct()[:5]

    manques_articles = base_qs[:5]

    return {
        'main_site': main_site,
        'sites': subsites,
        'regional_sites': regional_sites,
        'sectoral_sites': sectoral_sites,
        'main_categories': categories,
        'menu_structure': menu_structure,
        'campagnes_articles': campagnes_articles,
        'manques_articles': manques_articles,
    }
