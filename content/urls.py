from django.urls import path, re_path, register_converter
from django.views.generic import RedirectView
from . import views
from . import api_views
from .feeds import LatestArticlesFeed, SiteArticlesFeed, CategoryFeed, SiteCategoryFeed


class SectionSlugConverter:
    """Ne matche que les slugs qui correspondent à une SectionPage existante.
    Cela permet aux URLs Wagtail (/mentions-legales/, /cgu/, etc.)
    de ne pas être interceptées par le catch-all <site_slug>/."""
    regex = r'[\w-]+'

    def to_python(self, value):
        from cms.models import SectionPage
        if SectionPage.objects.filter(slug=value).exists():
            return value
        raise ValueError

    def to_url(self, value):
        return value


register_converter(SectionSlugConverter, 'section_slug')


class AncienSlugArticleConverter:
    """L'adresse WordPress `/<slug>/` d'un article que Wagtail ne sert pas là.

    WordPress publiait les articles du site principal à la racine. Les articles
    importés avant l'été sont rangés directement sous l'accueil : Wagtail sert
    encore `/<slug>/`. Ceux repris le 06/09/2026 sont rangés sous la section
    `principal` et vivent donc à `/principal/<slug>/` — leur ancienne adresse,
    la plus partagée puisque la plus récente, répondait 404 depuis la bascule
    DNS du 12/09 (38 articles, mesuré le 14/09/2026).

    Ne correspond que si un article en ligne porte ce slug ET qu'aucune page
    n'est servie par Wagtail à cette adresse : on n'intercepte rien de ce qui
    marche déjà.
    """
    regex = r'[\w-]+'

    def to_python(self, value):
        from wagtail.models import Page, Site
        from cms.models import ArticlePage
        if not ArticlePage.objects.live().filter(slug=value).exists():
            raise ValueError
        racine = (Site.objects.filter(is_default_site=True)
                  .values_list('root_page__url_path', flat=True).first())
        if racine and Page.objects.live().filter(url_path=f'{racine}{value}/').exists():
            raise ValueError
        return value

    def to_url(self, value):
        return value


register_converter(AncienSlugArticleConverter, 'ancien_slug_article')

app_name = 'content'

urlpatterns = [
    # Uploads Editor.js (accessible depuis /cms/ et /redac/)

    # API interne — intégration cnt-adhesion
    path('api/newsletter/sync/', api_views.NewsletterSyncView.as_view(), name='newsletter_sync'),

    # Page d'accueil
    path('', views.HomeView.as_view(), name='home'),

    # Recherche
    path('recherche/', views.SearchView.as_view(), name='search'),

    # Espace presse
    path('espace-presse/', views.EspacePresse.as_view(), name='espace_presse'),
    path('<slug:site_slug>/espace-presse/', views.sans_syndicat_externe(views.SiteEspacePresse.as_view()), name='site_espace_presse'),

    # Contact
    path('contact/', views.ContactView.as_view(), name='contact'),
    path('contact/merci/', views.contact_success, name='contact_success'),

    # Newsletter
    path('newsletter/inscription/', views.NewsletterSubscribeView.as_view(), name='newsletter_subscribe'),
    # Seule cette étape inscrit et fait partir un courriel : elle porte le hCaptcha.
    path('newsletter/inscription/valider/', views.NewsletterSubscribeVerifyView.as_view(),
         name='newsletter_subscribe_verify'),
    path('newsletter/confirmer/<uuid:token>/', views.NewsletterConfirmView.as_view(), name='newsletter_confirm'),
    path('newsletter/desinscription/<uuid:token>/', views.NewsletterUnsubscribeView.as_view(), name='newsletter_unsubscribe'),
    # Sortie sans jeton : la newsletter part en un message unique vers les
    # listes OVH, il n'y a donc pas de lien personnalisé à mettre en pied.
    path('newsletter/desabonnement/', views.NewsletterDesabonnementView.as_view(),
         name='newsletter_desabonnement'),

    # Flux RSS
    path('feed/', LatestArticlesFeed(), name='rss_feed'),
    path('feed/rss/', LatestArticlesFeed(), name='rss_feed_alt'),
    path('<slug:site_slug>/feed/', SiteArticlesFeed(), name='site_rss_feed'),
    path('categorie/<slug:slug>/feed/', CategoryFeed(), name='category_rss_feed'),

    # Tags (globaux)
    # `[-\w]+` et pas `<slug:>` : taggit garde les accents dans ses slugs
    # (« rentrée »), que le convertisseur `slug` (ASCII seul) refuse.
    re_path(r'^tag/(?P<slug>[-\w]+)/$', views.TagDetailView.as_view(), name='tag_detail'),

    # Catégories du site principal
    path('categorie/<slug:slug>/', views.CategoryDetailView.as_view(), name='category_detail'),

    # Pages spéciales du site principal
    path('plan-du-site/', views.PlanDuSiteView.as_view(), name='plan_du_site'),
    path('qui-sommes-nous/', views.QuiSommesNousView.as_view(), name='qui_sommes_nous'),
    path('sorganiser-avec-la-cnt-so/', views.SOrganiserView.as_view(), name='s_organiser'),
    # `souscription` était une simple redirection vers l'article, dont l'appel
    # au don se réduisait à un « cliquez ici » en petits caractères. C'est
    # désormais une vraie page, et les sept liens du site qui pointaient déjà
    # sur ce nom d'URL y arrivent sans changement.
    path('souscription/', views.SouscriptionView.as_view(), name='souscription'),
    path('permanences-juridiques/', views.PermanencesJuridiquesView.as_view(),
         name='permanences_juridiques'),
    # Déclarée ici, donc prioritaire sur le service Wagtail de la ContentPage
    # de même slug — dont le corps ne garde que le chapô.
    path('syndicats/', views.SyndicatsView.as_view(), name='syndicats'),

    # Articles et pages du site principal
    path('article/<slug:slug>/', views.ArticleDetailView.as_view(), name='article_detail'),
    # Version affichable d'une fiche pratique : page A4, prête à imprimer.
    path('article/<slug:slug>/tract/', views.ArticleTractView.as_view(), name='article_tract'),
    path('page/<slug:slug>/', views.PageDetailView.as_view(), name='page_detail'),

    # Sous-sites newsletter
    path('<slug:site_slug>/newsletter/inscription/', views.NewsletterSubscribeView.as_view(), name='site_newsletter_subscribe'),
    path('<slug:site_slug>/newsletter/inscription/valider/', views.NewsletterSubscribeVerifyView.as_view(),
         name='site_newsletter_subscribe_verify'),
    path('<slug:site_slug>/newsletter/desabonnement/', views.NewsletterDesabonnementView.as_view(),
         name='site_newsletter_desabonnement'),

    # Sous-sites — pages fonctionnelles génériques
    path('<slug:site_slug>/rejoindre/', views.sans_syndicat_externe(views.SiteRejoindreView.as_view()), name='site_rejoindre'),
    path('<slug:site_slug>/ressources/', views.sans_syndicat_externe(views.SiteRessourcesView.as_view()), name='site_ressources'),
    path('<slug:site_slug>/agenda/', views.sans_syndicat_externe(views.SiteAgendaView.as_view()), name='site_agenda'),
    # Le flux doit précéder la page : sans lui, `<slug:slug>` avalerait
    # « feed » comme s'il s'agissait d'une catégorie.
    path('<slug:site_slug>/categorie/<slug:slug>/feed/', SiteCategoryFeed(), name='site_category_rss_feed'),
    path('<slug:site_slug>/categorie/<slug:slug>/', views.SiteCategoryDetailView.as_view(), name='site_category_detail'),
    path('<slug:site_slug>/contact/', views.sans_syndicat_externe(views.SiteContactView.as_view()), name='site_contact'),
    path('<slug:site_slug>/contact/merci/', views.sans_syndicat_externe(views.site_contact_success), name='site_contact_success'),
    path('<slug:site_slug>/plan-du-site/', views.sans_syndicat_externe(views.PlanDuSiteView.as_view()), name='site_plan_du_site'),
    path('<section_slug:site_slug>/', views.SiteHomeView.as_view(), name='site_home'),
    path('<ancien_slug_article:slug>/', views.AncienneAdresseArticleView.as_view(), name='ancienne_adresse_article'),
    path('<slug:site_slug>/article/<slug:slug>/', views.SiteArticleDetailView.as_view(), name='site_article_detail'),
    path('<slug:site_slug>/article/<slug:slug>/tract/', views.ArticleTractView.as_view(), name='site_article_tract'),
    path('<slug:site_slug>/page/<slug:slug>/', views.SitePageDetailView.as_view(), name='site_page_detail'),

    # Redirections anciennes URLs WordPress (format: /2024/01/slug/)
    re_path(r'^(?P<year>\d{4})/(?P<month>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_redirect'),
    re_path(r'^(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_redirect_day'),
    # Redirections sous-sites (format: /13/2024/01/slug/)
    re_path(r'^(?P<site_path>[\w-]+)/(?P<year>\d{4})/(?P<month>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_subsite_redirect'),
]
