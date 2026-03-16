from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

app_name = 'redaction'

urlpatterns = [
    path('login/', views.RedacLoginView.as_view(), name='redac_login'),
    path('invitation/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='redaction/invitation_confirm.html',
        success_url='/redac/login/',
        post_reset_login=False,
    ), name='invitation_confirm'),
    path('logout/', views.RedacLogoutView.as_view(), name='redac_logout'),
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Uploads
    path('upload/image/', views.ImageUploadView.as_view(), name='image_upload'),
    path('upload/file/', views.FileUploadView.as_view(), name='file_upload'),

    # Articles
    path('articles/', views.ArticleListView.as_view(), name='article_list'),
    path('articles/nouveau/', views.ArticleCreateView.as_view(), name='article_create'),
    path('articles/<int:pk>/modifier/', views.ArticleEditView.as_view(), name='article_edit'),
    path('articles/<int:pk>/supprimer/', views.ArticleDeleteView.as_view(), name='article_delete'),
    path('articles/<int:pk>/apercu/', views.ArticlePreviewView.as_view(), name='article_preview'),

    # Catégories
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/nouveau/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/modifier/', views.CategoryEditView.as_view(), name='category_edit'),
    path('categories/<int:pk>/supprimer/', views.CategoryDeleteView.as_view(), name='category_delete'),

    # Tags
    path('tags/', views.TagListView.as_view(), name='tag_list'),
    path('tags/nouveau/', views.TagCreateView.as_view(), name='tag_create'),
    path('tags/<int:pk>/modifier/', views.TagEditView.as_view(), name='tag_edit'),
    path('tags/<int:pk>/supprimer/', views.TagDeleteView.as_view(), name='tag_delete'),

    # Commentaires
    path('commentaires/', views.CommentListView.as_view(), name='comment_list'),
    path('commentaires/<int:pk>/moderer/', views.CommentModerationView.as_view(), name='comment_moderate'),

    # Utilisateurs
    path('utilisateurs/', views.UserListView.as_view(), name='user_list'),
    path('utilisateurs/nouveau/', views.UserCreateView.as_view(), name='user_create'),
    path('utilisateurs/<int:pk>/modifier/', views.UserEditView.as_view(), name='user_edit'),

    # Sélecteur de site
    path('site/selectionner/', views.SiteSelectView.as_view(), name='site_select'),
    path('site/effacer/', views.SiteClearView.as_view(), name='site_clear'),

    # Footer
    path('footer/', views.FooterListView.as_view(), name='footer_list'),
    path('footer/nouveau/', views.FooterItemCreateView.as_view(), name='footer_item_create'),
    path('footer/<int:pk>/modifier/', views.FooterItemEditView.as_view(), name='footer_item_edit'),
    path('footer/<int:pk>/supprimer/', views.FooterItemDeleteView.as_view(), name='footer_item_delete'),
    path('footer/reorder/', views.FooterReorderView.as_view(), name='footer_reorder'),

    # Sous-sites
    path('sous-sites/', views.SiteListView.as_view(), name='site_list'),
    path('sous-sites/nouveau/', views.SiteCreateView.as_view(), name='site_create'),
    path('sous-sites/<int:pk>/modifier/', views.SiteEditView.as_view(), name='site_edit'),
    path('sous-sites/<int:pk>/toggle/', views.SiteToggleView.as_view(), name='site_toggle'),

    # Newsletter
    path('newsletter/', views.NewsletterListView.as_view(), name='newsletter_list'),
    path('newsletter/nouveau/', views.NewsletterCreateView.as_view(), name='newsletter_create'),
    path('newsletter/<int:pk>/modifier/', views.NewsletterEditView.as_view(), name='newsletter_edit'),
    path('newsletter/<int:pk>/apercu/', views.NewsletterPreviewView.as_view(), name='newsletter_preview'),
    path('newsletter/<int:pk>/envoyer/', views.NewsletterSendView.as_view(), name='newsletter_send'),
    path('newsletter/<int:pk>/supprimer/', views.NewsletterDeleteView.as_view(), name='newsletter_delete'),

    # Abonnés
    path('abonnes/', views.SubscriberListView.as_view(), name='subscriber_list'),
    path('abonnes/ajouter/', views.SubscriberAddView.as_view(), name='subscriber_add'),
    path('abonnes/import/', views.SubscriberImportView.as_view(), name='subscriber_import'),
    path('abonnes/export/', views.SubscriberExportView.as_view(), name='subscriber_export'),
    path('abonnes/<int:pk>/supprimer/', views.SubscriberDeleteView.as_view(), name='subscriber_delete'),

    # Menus
    path('menus/', views.MenuListView.as_view(), name='menu_list'),
    path('menus/nouveau/', views.MenuItemCreateView.as_view(), name='menu_item_create'),
    path('menus/reorder/', views.MenuReorderView.as_view(), name='menu_reorder'),
    path('menus/<int:pk>/modifier/', views.MenuItemEditView.as_view(), name='menu_item_edit'),
    path('menus/<int:pk>/supprimer/', views.MenuItemDeleteView.as_view(), name='menu_item_delete'),
]
