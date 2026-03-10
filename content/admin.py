from django.contrib import admin
from .models import Site, Author, Category, Tag, Media, Article, Page, MenuItem, Comment, ContactMessage


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'path', 'site_type', 'wp_blog_id', 'is_active']
    list_filter = ['site_type', 'is_active']
    search_fields = ['name', 'slug', 'path']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ['username', 'display_name', 'email', 'wp_id']
    search_fields = ['username', 'display_name', 'email']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'site', 'slug', 'parent', 'wp_id']
    list_filter = ['site', 'parent']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'wp_id']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ['title', 'site', 'mime_type', 'uploaded_at', 'wp_id']
    list_filter = ['site', 'mime_type']
    search_fields = ['title', 'original_url']


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'site', 'author', 'status', 'published_at', 'is_sticky']
    list_filter = ['site', 'status', 'categories', 'author', 'is_sticky']
    search_fields = ['title', 'content', 'excerpt']
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ['categories', 'tags']
    date_hierarchy = 'published_at'

    fieldsets = (
        (None, {
            'fields': ('site', 'title', 'slug', 'content', 'excerpt')
        }),
        ('Publication', {
            'fields': ('status', 'author', 'published_at', 'is_sticky')
        }),
        ('Classification', {
            'fields': ('categories', 'tags', 'featured_image')
        }),
        ('Métadonnées WordPress', {
            'fields': ('wp_id', 'wp_date', 'comment_status'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ['title', 'site', 'author', 'status', 'parent', 'menu_order']
    list_filter = ['site', 'status', 'author', 'template']
    search_fields = ['title', 'content']
    prepopulated_fields = {'slug': ('title',)}

    fieldsets = (
        (None, {
            'fields': ('site', 'title', 'slug', 'content', 'excerpt')
        }),
        ('Publication', {
            'fields': ('status', 'author', 'published_at')
        }),
        ('Hiérarchie', {
            'fields': ('parent', 'menu_order', 'template')
        }),
        ('Métadonnées WordPress', {
            'fields': ('wp_id', 'wp_date'),
            'classes': ('collapse',)
        }),
    )


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'menu', 'parent', 'order', 'is_active']
    list_filter = ['menu', 'is_active']
    search_fields = ['title', 'url']
    list_editable = ['order', 'is_active']


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['author_name', 'article', 'status', 'created_at', 'wp_date']
    list_filter = ['status', 'article__site']
    search_fields = ['author_name', 'author_email', 'content']
    list_editable = ['status']
    date_hierarchy = 'created_at'
    raw_id_fields = ['article', 'parent']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['subject', 'name', 'email', 'created_at', 'is_read']
    list_filter = ['is_read', 'created_at']
    search_fields = ['name', 'email', 'subject', 'message']
    list_editable = ['is_read']
    date_hierarchy = 'created_at'
    readonly_fields = ['name', 'email', 'subject', 'message', 'created_at']
