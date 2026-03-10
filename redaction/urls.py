from django.urls import path
from . import views

app_name = 'redaction'

urlpatterns = [
    path('login/', views.RedacLoginView.as_view(), name='redac_login'),
    path('logout/', views.RedacLogoutView.as_view(), name='redac_logout'),
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Upload image
    path('upload/image/', views.ImageUploadView.as_view(), name='image_upload'),

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

    # Menus
    path('menus/', views.MenuListView.as_view(), name='menu_list'),
    path('menus/nouveau/', views.MenuItemCreateView.as_view(), name='menu_item_create'),
    path('menus/reorder/', views.MenuReorderView.as_view(), name='menu_reorder'),
    path('menus/<int:pk>/modifier/', views.MenuItemEditView.as_view(), name='menu_item_edit'),
    path('menus/<int:pk>/supprimer/', views.MenuItemDeleteView.as_view(), name='menu_item_delete'),
]
