from django.templatetags.static import static

from cms.models import ArticlePage, CmsCategory, SectionPage


def _organization_structured_data(main_site, base_url):
    """Dict JSON-LD Organization (schema.org) — sérialisé côté template via
    le filtre `json_ld` (content_tags), affiché sur toutes les pages."""
    data = {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        'name': 'CNT-SO',
        'alternateName': 'Confédération Nationale du Travail — Solidarité Ouvrière',
        'url': f'{base_url}/',
        'logo': f"{base_url}{static('image/CNT SO.jpg')}",
    }
    if main_site:
        same_as = [
            url for url in (
                main_site.social_facebook, main_site.social_twitter,
                main_site.social_instagram, main_site.social_bluesky,
                main_site.social_mastodon, main_site.social_youtube,
            ) if url
        ]
        if same_as:
            data['sameAs'] = same_as
    return data


def menu_context(request):
    """Ajoute les données de menu à tous les templates"""

    # Site principal
    try:
        main_site = SectionPage.objects.get(slug='principal')
    except SectionPage.DoesNotExist:
        main_site = None

    # Tous les sous-sites
    subsites = SectionPage.objects.filter(live=True).exclude(slug='principal')

    # Catégories du site principal pour le menu
    categories = {}
    if main_site:
        for cat in CmsCategory.objects.filter(section_slug='principal').order_by('name'):
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
                ('education', 'Éducation & Recherche'),
                ('activites-postales-et-telecommunications', 'Activités postales et Télécom'),
                ('livreurs-travailleurs-euses-des-plateformes', 'Livreurs & plateformes'),
                ('services-a-la-personne', 'Services à la personne'),
                ('librairie', 'Librairie'),
                ('syndicat-des-travailleur-euse-s-artistes-auteurs-staa', 'STAA (Artistes-Auteurs)'),
                ('communication-culture-spectacle', 'STUCS (Culture & Spectacle)'),
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
    regional_sites = subsites.filter(section_type='regional')
    sectoral_sites = subsites.filter(section_type='sectoral')

    # Données sidebar partagées (ArticlePage — nouveau modèle)
    base_qs = (ArticlePage.objects.live()
               .filter(section_slug='principal')
               .select_related('featured_image')
               .prefetch_related('cms_categories')) if main_site else ArticlePage.objects.none()

    campagnes_articles = base_qs.filter(
        cms_categories__slug__in=['international', 'solidarites', 'campagne']
    ).distinct()[:5]

    manques_articles = base_qs[:5]

    # URL canonique de la page : domaine autonome si la requête est servie
    # dessus (request.section_page posé par SectionDomainMiddleware),
    # sinon l'origine publique du site principal.
    from django.conf import settings as _settings
    _section = getattr(request, 'section_page', None)
    if _section is not None and _section.custom_domain:
        _canonical_base = _section.base_url
    else:
        _canonical_base = getattr(_settings, 'MAIN_SITE_BASE_URL', '')
    canonical_url = f'{_canonical_base}{request.path}' if _canonical_base else ''

    # Home du site principal : absolue sur un domaine autonome (un href="/"
    # y bouclerait sur la home du sous-site), relative partout ailleurs.
    if _section is not None and _section.custom_domain:
        _main = getattr(_settings, 'MAIN_SITE_BASE_URL', '')
        main_site_url = f'{_main}/' if _main else '/'
    else:
        main_site_url = '/'

    org_base_url = _canonical_base or getattr(_settings, 'MAIN_SITE_BASE_URL', '') or 'https://cnt-so.org'

    return {
        'canonical_url': canonical_url,
        'site_base_url': _canonical_base,
        'org_structured_data': _organization_structured_data(main_site, org_base_url),
        'main_site_url': main_site_url,
        'main_site': main_site,
        'sites': subsites,
        'regional_sites': regional_sites,
        'sectoral_sites': sectoral_sites,
        'main_categories': categories,
        'menu_structure': menu_structure,
        'campagnes_articles': campagnes_articles,
        'manques_articles': manques_articles,
    }
