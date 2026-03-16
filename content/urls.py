from django.urls import path, re_path
from django.views.generic import RedirectView
from . import views
from .feeds import LatestArticlesFeed, SiteArticlesFeed, CategoryFeed

app_name = 'content'

urlpatterns = [
    # Page d'accueil
    path('', views.HomeView.as_view(), name='home'),

    # Recherche
    path('recherche/', views.SearchView.as_view(), name='search'),

    # Espace presse
    path('espace-presse/', views.EspacePresse.as_view(), name='espace_presse'),
    path('<slug:site_slug>/espace-presse/', views.SiteEspacePresse.as_view(), name='site_espace_presse'),

    # Contact
    path('contact/', views.ContactView.as_view(), name='contact'),
    path('contact/merci/', views.contact_success, name='contact_success'),

    # Newsletter
    path('newsletter/inscription/', views.NewsletterSubscribeView.as_view(), name='newsletter_subscribe'),
    path('newsletter/confirmer/<uuid:token>/', views.NewsletterConfirmView.as_view(), name='newsletter_confirm'),
    path('newsletter/desinscription/<uuid:token>/', views.NewsletterUnsubscribeView.as_view(), name='newsletter_unsubscribe'),

    # Flux RSS
    path('feed/', LatestArticlesFeed(), name='rss_feed'),
    path('feed/rss/', LatestArticlesFeed(), name='rss_feed_alt'),
    path('<slug:site_slug>/feed/', SiteArticlesFeed(), name='site_rss_feed'),
    path('categorie/<slug:slug>/feed/', CategoryFeed(), name='category_rss_feed'),

    # Tags (globaux)
    path('tag/<slug:slug>/', views.TagDetailView.as_view(), name='tag_detail'),

    # Catégories du site principal
    path('categorie/<slug:slug>/', views.CategoryDetailView.as_view(), name='category_detail'),

    # Pages spéciales du site principal
    path('plan-du-site/', views.PlanDuSiteView.as_view(), name='plan_du_site'),
    path('qui-sommes-nous/', views.QuiSommesNousView.as_view(), name='qui_sommes_nous'),
    path('souscription/', RedirectView.as_view(url='/article/souscription/', permanent=True), name='souscription'),

    # Articles et pages du site principal
    path('article/<slug:slug>/', views.ArticleDetailView.as_view(), name='article_detail'),
    path('page/<slug:slug>/', views.PageDetailView.as_view(), name='page_detail'),

    # Sous-sites newsletter
    path('<slug:site_slug>/newsletter/inscription/', views.NewsletterSubscribeView.as_view(), name='site_newsletter_subscribe'),

    # Sous-sites
    path('<slug:site_slug>/agenda/', views.SiteAgendaView.as_view(), name='site_agenda'),
    path('<slug:site_slug>/categorie/<slug:slug>/', views.SiteCategoryDetailView.as_view(), name='site_category_detail'),
    path('<slug:site_slug>/contact/', views.SiteContactView.as_view(), name='site_contact'),
    path('<slug:site_slug>/contact/merci/', views.site_contact_success, name='site_contact_success'),
    path('<slug:site_slug>/plan-du-site/', views.PlanDuSiteView.as_view(), name='site_plan_du_site'),
    path('<slug:site_slug>/', views.SiteHomeView.as_view(), name='site_home'),
    path('<slug:site_slug>/article/<slug:slug>/', views.SiteArticleDetailView.as_view(), name='site_article_detail'),
    path('<slug:site_slug>/page/<slug:slug>/', views.SitePageDetailView.as_view(), name='site_page_detail'),

    # Redirections anciennes URLs WordPress (format: /2024/01/slug/)
    re_path(r'^(?P<year>\d{4})/(?P<month>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_redirect'),
    re_path(r'^(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_redirect_day'),
    # Redirections sous-sites (format: /13/2024/01/slug/)
    re_path(r'^(?P<site_path>[\w-]+)/(?P<year>\d{4})/(?P<month>\d{2})/(?P<slug>[\w-]+)/$', views.WordPressRedirectView.as_view(), name='wp_subsite_redirect'),
]
