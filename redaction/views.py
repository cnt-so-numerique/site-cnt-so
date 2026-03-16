import csv
import io
import json
import time
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.db.models import Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DeleteView
)

from content.models import Article, Author, Category, Tag, Comment, Media, Site, MenuItem, Newsletter, NewsletterArticle, Subscriber
from .forms import ArticleForm, CategoryForm, TagForm, UserCreateForm, UserEditForm, MenuItemForm, SiteForm, NewsletterForm, SubscriberImportForm
from .mixins import RedacLoginRequiredMixin, ChefRequiredMixin, SuperuserRequiredMixin


# ── Authentification ──────────────────────────────────────────────────────────

class RedacLoginView(auth_views.LoginView):
    template_name = 'redaction/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('redaction:dashboard')


class RedacLogoutView(auth_views.LogoutView):
    next_page = '/redac/login/'


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardView(RedacLoginRequiredMixin, TemplateView):
    template_name = 'redaction/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()

        # Site courant (contexte déjà calculé par le context processor, on le relit depuis la session)
        current_site = None
        if is_chef:
            site_id = self.request.session.get('redac_current_site_id')
            if site_id:
                try:
                    current_site = Site.objects.get(pk=site_id)
                except Site.DoesNotExist:
                    pass
        else:
            author_profile = getattr(user, 'author_profile', None)
            current_site = author_profile.site if author_profile else None

        # Queryset d'articles
        if is_chef and current_site:
            articles_qs = Article.objects.filter(site=current_site)
        elif is_chef:
            articles_qs = Article.objects.all()
        elif current_site:
            articles_qs = Article.objects.filter(site=current_site)
        else:
            articles_qs = Article.objects.none()

        ctx['nb_published'] = articles_qs.filter(status='publish').count()
        ctx['nb_draft'] = articles_qs.filter(status='draft').count()
        ctx['nb_pending'] = articles_qs.filter(status='pending').count()
        ctx['nb_total'] = articles_qs.count()
        ctx['recent_articles'] = articles_qs.select_related('author', 'site').order_by('-created_at')[:8]
        ctx['is_chef'] = is_chef

        if is_chef:
            ctx['nb_comments_pending'] = Comment.objects.filter(status='pending').count()
            ctx['recent_comments'] = Comment.objects.filter(
                status='pending'
            ).select_related('article').order_by('-created_at')[:5]
            if current_site:
                ctx['top_categories'] = (
                    Category.objects.filter(site=current_site)
                    .annotate(nb=Count('articles'))
                    .filter(nb__gt=0)
                    .order_by('-nb')[:5]
                )
            else:
                ctx['top_categories'] = (
                    Category.objects.annotate(nb=Count('articles'))
                    .filter(nb__gt=0)
                    .order_by('-nb')[:5]
                )
            ctx['stats_by_site'] = (
                Article.objects.filter(status='publish')
                .values('site__name')
                .annotate(total=Count('id'))
                .order_by('-total')[:6]
            ) if not current_site else None

        return ctx


# ── Upload image ──────────────────────────────────────────────────────────────

class ImageUploadView(RedacLoginRequiredMixin, View):
    """Endpoint pour Editor.js et l'image mise en avant."""

    def post(self, request):
        image = request.FILES.get('image')
        if not image:
            return JsonResponse({'success': 0, 'message': 'Aucun fichier reçu.'})

        allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml']
        if image.content_type not in allowed:
            return JsonResponse({'success': 0, 'message': 'Type de fichier non autorisé.'})

        media = Media.objects.create(
            title=image.name,
            file=image,
            mime_type=image.content_type,
        )

        return JsonResponse({
            'success': 1,
            'file': {
                'url': request.build_absolute_uri(media.file.url),
                'id': media.id,
            },
        })


class FileUploadView(RedacLoginRequiredMixin, View):
    """Endpoint pour l'upload de fichiers (PDF, doc…) depuis FileTool."""

    def post(self, request):
        f = request.FILES.get('file')
        if not f:
            return JsonResponse({'success': 0, 'message': 'Aucun fichier reçu.'})

        allowed = [
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.oasis.opendocument.text',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.oasis.opendocument.spreadsheet',
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/zip',
            'application/octet-stream',
        ]
        if f.content_type not in allowed:
            return JsonResponse({'success': 0, 'message': 'Type de fichier non autorisé.'})

        media = Media.objects.create(
            title=f.name,
            file=f,
            mime_type=f.content_type,
        )

        return JsonResponse({
            'success': 1,
            'file': {
                'url': request.build_absolute_uri(media.file.url),
                'name': f.name,
            },
        })


# ── Articles ──────────────────────────────────────────────────────────────────

class ArticleListView(RedacLoginRequiredMixin, ListView):
    model = Article
    template_name = 'redaction/article_list.html'
    context_object_name = 'articles'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()

        if is_chef:
            site_id = self.request.session.get('redac_current_site_id')
            if site_id:
                qs = Article.objects.filter(site_id=site_id).select_related('author', 'site').order_by('-created_at')
            else:
                qs = Article.objects.select_related('author', 'site').order_by('-created_at')
        else:
            author_profile = getattr(user, 'author_profile', None)
            user_site = author_profile.site if author_profile else None
            if user_site:
                qs = Article.objects.filter(site=user_site).select_related('author', 'site').order_by('-created_at')
            else:
                qs = Article.objects.none()

        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(title__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['is_chef'] = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        ctx['status_filter'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        ctx['status_choices'] = Article.STATUS_CHOICES
        return ctx


class ArticleCreateView(RedacLoginRequiredMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = 'redaction/article_form.html'
    success_url = reverse_lazy('redaction:article_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['current_site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        article = form.save(commit=False)
        user = self.request.user
        author = getattr(user, 'author_profile', None)
        if author:
            article.author = author
        if not article.slug:
            from django.utils.text import slugify
            article.slug = slugify(article.title)
        if article.status == 'publish' and not article.published_at:
            article.published_at = timezone.now()
        # Rédacteur : forcer le site de son profil
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef and author:
            article.site = author.site
        article.save()
        form.save_m2m()
        messages.success(self.request, 'Article créé avec succès.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        return ctx


class ArticleEditView(RedacLoginRequiredMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = 'redaction/article_form.html'
    success_url = reverse_lazy('redaction:article_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef:
            author_profile = getattr(user, 'author_profile', None)
            user_site = author_profile.site if author_profile else None
            if obj.site != user_site:
                raise PermissionDenied
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['current_site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        article = form.save(commit=False)
        user = self.request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef:
            # Rédacteur : s'assurer que le site n'est pas modifié
            author_profile = getattr(user, 'author_profile', None)
            if author_profile:
                article.site = author_profile.site
        if article.status == 'publish' and not article.published_at:
            article.published_at = timezone.now()
        article.save()
        form.save_m2m()
        messages.success(self.request, 'Article modifié avec succès.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        return ctx


class ArticleDeleteView(ChefRequiredMixin, DeleteView):
    model = Article
    template_name = 'redaction/article_confirm_delete.html'
    success_url = reverse_lazy('redaction:article_list')

    def form_valid(self, form):
        messages.success(self.request, 'Article supprimé.')
        return super().form_valid(form)


class ArticlePreviewView(RedacLoginRequiredMixin, View):
    """Aperçu de l'article — GET: version sauvegardée, POST: état actuel de l'éditeur."""

    def _check_permission(self, request, article):
        user = request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef:
            author_profile = getattr(user, 'author_profile', None)
            user_site = author_profile.site if author_profile else None
            if article.site != user_site:
                raise PermissionDenied

    def get(self, request, pk):
        article = get_object_or_404(Article, pk=pk)
        self._check_permission(request, article)
        return render(request, 'redaction/article_preview.html', {'article': article})

    def post(self, request, pk):
        article = get_object_or_404(Article, pk=pk)
        self._check_permission(request, article)
        # Créer un objet article temporaire avec les données du formulaire
        # sans toucher à la base de données
        article.title = request.POST.get('title', article.title)
        article.content = request.POST.get('content', article.content)
        article.status = request.POST.get('status', article.status)
        return render(request, 'redaction/article_preview.html', {'article': article, 'is_live_preview': True})


# ── Catégories ────────────────────────────────────────────────────────────────

class CategoryListView(ChefRequiredMixin, ListView):
    model = Category
    template_name = 'redaction/category_list.html'
    context_object_name = 'categories'

    def get_queryset(self):
        current_site = _get_current_site_for_view(self.request)
        if current_site:
            return Category.objects.filter(site=current_site).select_related('site', 'parent').order_by('name')
        return Category.objects.select_related('site', 'parent').order_by('site', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class CategoryCreateView(ChefRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'redaction/category_form.html'
    success_url = reverse_lazy('redaction:category_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        cat = form.save(commit=False)
        current_site = _get_current_site_for_view(self.request)
        if current_site and not cat.site:
            cat.site = current_site
        cat.save()
        messages.success(self.request, 'Catégorie créée.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class CategoryEditView(ChefRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'redaction/category_form.html'
    success_url = reverse_lazy('redaction:category_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Catégorie modifiée.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class CategoryDeleteView(ChefRequiredMixin, DeleteView):
    model = Category
    template_name = 'redaction/confirm_delete.html'
    success_url = reverse_lazy('redaction:category_list')

    def form_valid(self, form):
        messages.success(self.request, 'Catégorie supprimée.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['object_type'] = 'la catégorie'
        ctx['object_name'] = self.object.name
        ctx['cancel_url'] = self.success_url
        return ctx


# ── Tags ──────────────────────────────────────────────────────────────────────

class TagListView(ChefRequiredMixin, ListView):
    model = Tag
    template_name = 'redaction/tag_list.html'
    context_object_name = 'tags'

    def get_queryset(self):
        current_site = _get_current_site_for_view(self.request)
        if current_site:
            return Tag.objects.filter(site=current_site).select_related('site').order_by('name')
        return Tag.objects.select_related('site').order_by('site', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class TagCreateView(ChefRequiredMixin, CreateView):
    model = Tag
    form_class = TagForm
    template_name = 'redaction/tag_form.html'
    success_url = reverse_lazy('redaction:tag_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        tag = form.save(commit=False)
        current_site = _get_current_site_for_view(self.request)
        if current_site and not tag.site:
            tag.site = current_site
        tag.save()
        messages.success(self.request, 'Tag créé.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class TagEditView(ChefRequiredMixin, UpdateView):
    model = Tag
    form_class = TagForm
    template_name = 'redaction/tag_form.html'
    success_url = reverse_lazy('redaction:tag_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Tag modifié.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class TagDeleteView(ChefRequiredMixin, DeleteView):
    model = Tag
    template_name = 'redaction/confirm_delete.html'
    success_url = reverse_lazy('redaction:tag_list')

    def form_valid(self, form):
        messages.success(self.request, 'Tag supprimé.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['object_type'] = 'le tag'
        ctx['object_name'] = self.object.name
        ctx['cancel_url'] = self.success_url
        return ctx


# ── Commentaires ──────────────────────────────────────────────────────────────

class CommentListView(ChefRequiredMixin, ListView):
    model = Comment
    template_name = 'redaction/comment_list.html'
    context_object_name = 'comments'
    paginate_by = 30

    def get_queryset(self):
        qs = Comment.objects.select_related('article').order_by('-created_at')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(author_name__icontains=q) | qs.filter(content__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_filter'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        ctx['status_choices'] = Comment.STATUS_CHOICES
        ctx['nb_pending'] = Comment.objects.filter(status='pending').count()
        return ctx


class CommentModerationView(ChefRequiredMixin, View):
    """Change le statut d'un commentaire via POST."""

    def post(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        action = request.POST.get('action')
        if action == 'approve':
            comment.status = 'approved'
            messages.success(request, 'Commentaire approuvé.')
        elif action == 'spam':
            comment.status = 'spam'
            messages.success(request, 'Commentaire marqué comme spam.')
        elif action == 'delete':
            comment.status = 'trash'
            messages.success(request, 'Commentaire mis à la corbeille.')
        comment.save()
        return redirect(request.META.get('HTTP_REFERER', 'redaction:comment_list'))


# ── Utilisateurs ─────────────────────────────────────────────────────────────

def _send_invitation_email(request, user):
    """Envoie un e-mail d'invitation à un nouvel utilisateur pour qu'il définisse son mot de passe."""
    if not user.email:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    invitation_url = request.build_absolute_uri(
        reverse('redaction:invitation_confirm', args=[uid, token])
    )
    html = render_to_string('redaction/invitation_email.html', {
        'user': user,
        'invitation_url': invitation_url,
    }, request=request)
    text = f"Bonjour {user.get_full_name() or user.username},\n\nVous avez été invité(e) à rejoindre l'espace rédaction CNT-SO.\nDéfinissez votre mot de passe ici : {invitation_url}\n\nCe lien est valable 3 jours."
    try:
        msg = EmailMultiAlternatives(
            subject="Invitation — Espace rédaction CNT-SO",
            body=text,
            from_email=None,
            to=[user.email],
        )
        msg.attach_alternative(html, 'text/html')
        msg.send()
    except Exception:
        pass

class UserListView(ChefRequiredMixin, ListView):
    model = User
    template_name = 'redaction/user_list.html'
    context_object_name = 'users'

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.select_related('author_profile__site').prefetch_related('groups').order_by('username')
        if not user.is_superuser:
            chef_profile = getattr(user, 'author_profile', None)
            chef_site = chef_profile.site if chef_profile else None
            if chef_site:
                qs = qs.filter(author_profile__site=chef_site)
            else:
                qs = User.objects.none()
        return qs


class UserCreateView(ChefRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'redaction/user_form.html'
    success_url = reverse_lazy('redaction:user_list')

    def form_valid(self, form):
        user_obj = form.save()
        # Créer ou récupérer le profil Author et assigner le site
        author, _ = Author.objects.get_or_create(
            user=user_obj,
            defaults={
                'username': user_obj.username,
                'email': user_obj.email,
                'display_name': user_obj.get_full_name() or user_obj.username,
            }
        )
        request_user = self.request.user
        if request_user.is_superuser:
            author.site = form.cleaned_data.get('site')
        else:
            chef_profile = getattr(request_user, 'author_profile', None)
            author.site = chef_profile.site if chef_profile else None
        author.username = user_obj.username
        author.email = user_obj.email
        if not author.display_name:
            author.display_name = user_obj.get_full_name() or user_obj.username
        author.save()

        # Envoyer l'e-mail d'invitation
        _send_invitation_email(self.request, user_obj)
        messages.success(self.request, f'Utilisateur créé. Une invitation a été envoyée à {user_obj.email}.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        return ctx


class UserEditView(ChefRequiredMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = 'redaction/user_form.html'
    success_url = reverse_lazy('redaction:user_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser:
            chef_profile = getattr(user, 'author_profile', None)
            chef_site = chef_profile.site if chef_profile else None
            target_profile = getattr(obj, 'author_profile', None)
            target_site = target_profile.site if target_profile else None
            if chef_site is None or chef_site != target_site:
                raise PermissionDenied
        return obj

    def form_valid(self, form):
        user_obj = form.save()
        # Créer ou récupérer le profil Author et mettre à jour le site
        author, _ = Author.objects.get_or_create(
            user=user_obj,
            defaults={
                'username': user_obj.username,
                'email': user_obj.email,
                'display_name': user_obj.get_full_name() or user_obj.username,
            }
        )
        request_user = self.request.user
        if request_user.is_superuser:
            author.site = form.cleaned_data.get('site')
        else:
            chef_profile = getattr(request_user, 'author_profile', None)
            author.site = chef_profile.site if chef_profile else None
        author.save()
        messages.success(self.request, 'Utilisateur modifié.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        return ctx


# ── Sélecteur de site ─────────────────────────────────────────────────────────

class SiteSelectView(RedacLoginRequiredMixin, View):
    """POST : stocke site_id en session (chefs uniquement). site_id vide = effacer."""

    def post(self, request):
        user = request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef:
            raise PermissionDenied
        site_id = request.POST.get('site_id')
        if site_id:
            try:
                site = Site.objects.get(pk=site_id, is_active=True)
                request.session['redac_current_site_id'] = site.pk
            except Site.DoesNotExist:
                messages.error(request, 'Site introuvable.')
        else:
            request.session.pop('redac_current_site_id', None)
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'redaction:dashboard'
        return redirect(next_url)


class SiteClearView(RedacLoginRequiredMixin, View):
    """POST : supprime le site courant de la session."""

    def post(self, request):
        user = request.user
        is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
        if not is_chef:
            raise PermissionDenied
        request.session.pop('redac_current_site_id', None)
        messages.info(request, 'Sélection de site effacée.')
        return redirect('redaction:dashboard')


# ── Menus ─────────────────────────────────────────────────────────────────────

def _get_current_site_for_view(request):
    """Retourne le site courant selon le rôle et la session."""
    user = request.user
    is_chef = user.is_superuser or user.groups.filter(name='redacteur_en_chef').exists()
    if is_chef:
        site_id = request.session.get('redac_current_site_id')
        if site_id:
            try:
                return Site.objects.get(pk=site_id)
            except Site.DoesNotExist:
                pass
        return None
    else:
        author_profile = getattr(user, 'author_profile', None)
        return author_profile.site if author_profile else None


class MenuListView(RedacLoginRequiredMixin, TemplateView):
    template_name = 'redaction/menu_list.html'

    def get(self, request, *args, **kwargs):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site pour gérer ses menus.')
            return redirect('redaction:dashboard')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current_site = _get_current_site_for_view(self.request)
        items = MenuItem.objects.filter(site=current_site).select_related(
            'parent', 'category', 'article', 'page', 'target_site'
        ).order_by('menu', 'order')

        def _destination(item):
            if item.link_type == 'url':
                return item.url or '—'
            elif item.link_type == 'category':
                return str(item.category) if item.category else '—'
            elif item.link_type == 'site':
                return str(item.target_site) if item.target_site else '—'
            elif item.link_type == 'article':
                return str(item.article) if item.article else '—'
            elif item.link_type == 'page':
                return str(item.page) if item.page else '—'
            return '—'

        items_data = []
        for item in items:
            items_data.append({
                'id': item.pk,
                'menu': item.menu,
                'title': item.title,
                'link_type': item.link_type,
                'link_type_display': item.get_link_type_display(),
                'destination': _destination(item)[:60],
                'parent_id': item.parent_id,
                'order': item.order,
                'is_active': item.is_active,
                'opens_new_tab': item.opens_new_tab,
                'edit_url': reverse('redaction:menu_item_edit', args=[item.pk]),
                'delete_url': reverse('redaction:menu_item_delete', args=[item.pk]),
            })

        menus_meta = {k: v for k, v in MenuItem.MENU_CHOICES}

        ctx['items_json'] = json.dumps(items_data, ensure_ascii=False)
        ctx['menus_json'] = json.dumps(menus_meta, ensure_ascii=False)
        ctx['reorder_url'] = reverse('redaction:menu_reorder')
        ctx['current_site'] = current_site
        return ctx


class MenuItemCreateView(RedacLoginRequiredMixin, CreateView):
    model = MenuItem
    form_class = MenuItemForm
    template_name = 'redaction/menu_item_form.html'
    success_url = reverse_lazy('redaction:menu_list')

    def get(self, request, *args, **kwargs):
        if not _get_current_site_for_view(request):
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('redaction:dashboard')
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        item = form.save(commit=False)
        item.site = _get_current_site_for_view(self.request)
        item.save()
        messages.success(self.request, 'Élément de menu créé.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class MenuItemEditView(RedacLoginRequiredMixin, UpdateView):
    model = MenuItem
    form_class = MenuItemForm
    template_name = 'redaction/menu_item_form.html'
    success_url = reverse_lazy('redaction:menu_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        current_site = _get_current_site_for_view(self.request)
        if obj.site != current_site:
            raise PermissionDenied
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Élément de menu modifié.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class MenuItemDeleteView(ChefRequiredMixin, DeleteView):
    model = MenuItem
    template_name = 'redaction/menu_item_confirm_delete.html'
    success_url = reverse_lazy('redaction:menu_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        current_site = _get_current_site_for_view(self.request)
        if obj.site != current_site:
            raise PermissionDenied
        return obj

    def form_valid(self, form):
        messages.success(self.request, 'Élément de menu supprimé.')
        return super().form_valid(form)


class MenuReorderView(ChefRequiredMixin, View):
    """Endpoint AJAX — reçoit l'arbre JSON et met à jour order + parent."""

    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            return JsonResponse({'ok': False, 'error': 'Aucun site sélectionné.'}, status=400)
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'JSON invalide.'}, status=400)

        # Pré-charger tous les items du site pour éviter N+1
        all_items = {item.pk: item for item in MenuItem.objects.filter(site=current_site)}

        def process(nodes, parent_id):
            for idx, node in enumerate(nodes, start=1):
                item_id = node.get('id')
                item = all_items.get(item_id)
                if item is None:
                    continue
                item.parent_id = parent_id
                item.order = idx
                item.save(update_fields=['parent_id', 'order'])
                children = node.get('children', [])
                if children:
                    process(children, item_id)

        for menu_key, nodes in data.items():
            process(nodes, None)

        return JsonResponse({'ok': True})


# ── Gestion des sous-sites ─────────────────────────────────────────────────────

class SiteListView(SuperuserRequiredMixin, ListView):
    template_name = 'redaction/site_list.html'
    context_object_name = 'sites'

    def get_queryset(self):
        return Site.objects.exclude(slug='principal').order_by('site_type', 'name')


class SiteCreateView(SuperuserRequiredMixin, CreateView):
    template_name = 'redaction/site_form.html'
    form_class = SiteForm
    success_url = reverse_lazy('redaction:site_list')

    def form_valid(self, response):
        messages.success(self.request, 'Sous-site créé avec succès.')
        return super().form_valid(response)


class SiteEditView(SuperuserRequiredMixin, UpdateView):
    model = Site
    template_name = 'redaction/site_form.html'
    form_class = SiteForm
    success_url = reverse_lazy('redaction:site_list')

    def form_valid(self, response):
        messages.success(self.request, 'Sous-site modifié avec succès.')
        return super().form_valid(response)


class SiteToggleView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        site = get_object_or_404(Site, pk=pk)
        site.is_active = not site.is_active
        site.save(update_fields=['is_active'])
        status = 'activé' if site.is_active else 'masqué'
        messages.success(request, f'Sous-site « {site.name} » {status}.')
        return redirect('redaction:site_list')


# ── Footer (gestion par site) ──────────────────────────────────────────────────

class FooterListView(ChefRequiredMixin, TemplateView):
    template_name = 'redaction/footer_list.html'

    def get(self, request, *args, **kwargs):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site pour gérer son footer.')
            return redirect('redaction:dashboard')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current_site = _get_current_site_for_view(self.request)
        items = MenuItem.objects.filter(
            site=current_site, menu='footer'
        ).select_related('parent', 'category', 'article', 'page', 'target_site').order_by('order')

        def _destination(item):
            if item.link_type == 'url': return item.url or '—'
            if item.link_type == 'category': return str(item.category) if item.category else '—'
            if item.link_type == 'site': return str(item.target_site) if item.target_site else '—'
            if item.link_type == 'article': return str(item.article) if item.article else '—'
            if item.link_type == 'page': return str(item.page) if item.page else '—'
            return '—'

        items_data = []
        for item in items:
            items_data.append({
                'id': item.pk,
                'title': item.title,
                'link_type': item.link_type,
                'link_type_display': item.get_link_type_display(),
                'destination': _destination(item)[:60],
                'parent_id': item.parent_id,
                'order': item.order,
                'is_active': item.is_active,
                'opens_new_tab': item.opens_new_tab,
                'edit_url': reverse('redaction:footer_item_edit', args=[item.pk]),
                'delete_url': reverse('redaction:footer_item_delete', args=[item.pk]),
            })

        ctx['items_json'] = json.dumps(items_data, ensure_ascii=False)
        ctx['reorder_url'] = reverse('redaction:footer_reorder')
        ctx['current_site'] = current_site
        return ctx


class FooterItemCreateView(ChefRequiredMixin, CreateView):
    model = MenuItem
    form_class = MenuItemForm
    template_name = 'redaction/footer_item_form.html'
    success_url = reverse_lazy('redaction:footer_list')

    def get(self, request, *args, **kwargs):
        if not _get_current_site_for_view(request):
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('redaction:dashboard')
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        kwargs['menu_type'] = 'footer'
        return kwargs

    def get_initial(self):
        return {'menu': 'footer'}

    def form_valid(self, form):
        item = form.save(commit=False)
        item.site = _get_current_site_for_view(self.request)
        item.menu = 'footer'
        item.save()
        messages.success(self.request, 'Élément de footer créé.')
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Créer'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class FooterItemEditView(ChefRequiredMixin, UpdateView):
    model = MenuItem
    form_class = MenuItemForm
    template_name = 'redaction/footer_item_form.html'
    success_url = reverse_lazy('redaction:footer_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.site != _get_current_site_for_view(self.request):
            raise PermissionDenied
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['site'] = _get_current_site_for_view(self.request)
        kwargs['menu_type'] = 'footer'
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Élément de footer modifié.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Modifier'
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class FooterItemDeleteView(ChefRequiredMixin, DeleteView):
    model = MenuItem
    template_name = 'redaction/confirm_delete.html'
    success_url = reverse_lazy('redaction:footer_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.site != _get_current_site_for_view(self.request):
            raise PermissionDenied
        return obj

    def form_valid(self, form):
        messages.success(self.request, 'Élément de footer supprimé.')
        return super().form_valid(form)


class FooterReorderView(ChefRequiredMixin, View):
    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            return JsonResponse({'ok': False, 'error': 'Aucun site sélectionné.'}, status=400)
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'JSON invalide.'}, status=400)

        all_items = {item.pk: item for item in MenuItem.objects.filter(site=current_site, menu='footer')}

        def process(nodes, parent_id):
            for idx, node in enumerate(nodes, start=1):
                item = all_items.get(node.get('id'))
                if item is None:
                    continue
                item.parent_id = parent_id
                item.order = idx
                item.save(update_fields=['parent_id', 'order'])
                if node.get('children'):
                    process(node['children'], item.pk)

        process(data.get('footer', []), None)
        return JsonResponse({'ok': True})


# ── Newsletter ─────────────────────────────────────────────────────────────────

class NewsletterListView(ChefRequiredMixin, ListView):
    model = Newsletter
    template_name = 'redaction/newsletter_list.html'
    context_object_name = 'newsletters'

    def get_queryset(self):
        current_site = _get_current_site_for_view(self.request)
        if current_site:
            return Newsletter.objects.filter(site=current_site).select_related('sent_by')
        return Newsletter.objects.select_related('site', 'sent_by')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_site'] = _get_current_site_for_view(self.request)
        return ctx


class NewsletterCreateView(ChefRequiredMixin, View):
    template_name = 'redaction/newsletter_form.html'

    def _get_site(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site pour créer une newsletter.')
        return current_site

    def get(self, request):
        site = self._get_site(request)
        if not site:
            return redirect('redaction:newsletter_list')
        form = NewsletterForm(site=site)
        return render(request, self.template_name, {'form': form, 'action': 'Créer', 'current_site': site})

    def post(self, request):
        site = self._get_site(request)
        if not site:
            return redirect('redaction:newsletter_list')
        form = NewsletterForm(request.POST, site=site)
        if form.is_valid():
            newsletter = form.save(commit=False)
            newsletter.site = site
            newsletter.save()
            selected = form.cleaned_data['selected_articles']
            for idx, article in enumerate(selected, start=1):
                NewsletterArticle.objects.create(newsletter=newsletter, article=article, order=idx)
            messages.success(request, 'Newsletter créée.')
            return redirect('redaction:newsletter_edit', pk=newsletter.pk)
        return render(request, self.template_name, {'form': form, 'action': 'Créer', 'current_site': site})


class NewsletterEditView(ChefRequiredMixin, View):
    template_name = 'redaction/newsletter_form.html'

    def _get_newsletter(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = _get_current_site_for_view(request)
        if current_site and newsletter.site != current_site:
            raise PermissionDenied
        return newsletter

    def get(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.info(request, 'Cette newsletter a déjà été envoyée.')
            return redirect('redaction:newsletter_list')
        form = NewsletterForm(instance=newsletter, site=newsletter.site)
        return render(request, self.template_name, {
            'form': form, 'newsletter': newsletter,
            'action': 'Modifier', 'current_site': newsletter.site,
        })

    def post(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            raise PermissionDenied
        form = NewsletterForm(request.POST, instance=newsletter, site=newsletter.site)
        if form.is_valid():
            newsletter = form.save()
            # Remplacer les articles sélectionnés
            NewsletterArticle.objects.filter(newsletter=newsletter).delete()
            for idx, article in enumerate(form.cleaned_data['selected_articles'], start=1):
                NewsletterArticle.objects.create(newsletter=newsletter, article=article, order=idx)
            messages.success(request, 'Newsletter sauvegardée.')
            return redirect('redaction:newsletter_edit', pk=newsletter.pk)
        return render(request, self.template_name, {
            'form': form, 'newsletter': newsletter,
            'action': 'Modifier', 'current_site': newsletter.site,
        })


class NewsletterPreviewView(ChefRequiredMixin, View):
    """Aperçu HTML de l'e-mail tel qu'il sera reçu."""

    def get(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = _get_current_site_for_view(request)
        if current_site and newsletter.site != current_site:
            raise PermissionDenied
        articles = list(
            newsletter.newsletter_articles.select_related('article__featured_image').order_by('order')
        )
        site_url = request.build_absolute_uri('/')
        html = render_to_string('newsletter/email.html', {
            'newsletter': newsletter,
            'newsletter_articles': articles,
            'site_url': site_url,
            'unsubscribe_url': '#',
            'is_preview': True,
        }, request=request)
        return HttpResponse(html)


class NewsletterSendView(ChefRequiredMixin, View):
    """Confirmation puis envoi de la newsletter."""
    template_name = 'redaction/newsletter_send.html'

    def _get_newsletter(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = _get_current_site_for_view(request)
        if current_site and newsletter.site != current_site:
            raise PermissionDenied
        return newsletter

    def get(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.error(request, 'Newsletter déjà envoyée.')
            return redirect('redaction:newsletter_list')
        subscribers = Subscriber.objects.filter(site=newsletter.site, is_active=True)
        return render(request, self.template_name, {
            'newsletter': newsletter,
            'nb_subscribers': subscribers.count(),
        })

    def post(self, request, pk):
        newsletter = self._get_newsletter(request, pk)
        if newsletter.status == 'sent':
            messages.error(request, 'Newsletter déjà envoyée.')
            return redirect('redaction:newsletter_list')

        mode = request.POST.get('mode', 'send')
        articles = list(
            newsletter.newsletter_articles.select_related('article__featured_image').order_by('order')
        )
        site_url = request.build_absolute_uri('/')

        # ── Mode test : envoi à une seule adresse ──────────────────────────────
        if mode == 'test':
            test_email = request.POST.get('test_email', '').strip()
            if not test_email:
                messages.error(request, 'Adresse e-mail de test manquante.')
                return redirect('redaction:newsletter_send', pk=pk)
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:newsletter_unsubscribe', args=['00000000-0000-0000-0000-000000000000'])
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'newsletter_articles': articles,
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'is_preview': True,
            }, request=request)
            text_body = f"[TEST] {newsletter.title}\n\n{newsletter.intro}"
            try:
                msg = EmailMultiAlternatives(
                    subject=f"[TEST] {newsletter.title}",
                    body=text_body,
                    from_email=None,
                    to=[test_email],
                )
                msg.attach_alternative(html_body, 'text/html')
                msg.send()
                messages.success(request, f'E-mail de test envoyé à {test_email}.')
            except Exception as e:
                messages.error(request, f'Erreur lors de l\'envoi : {e}')
            return redirect('redaction:newsletter_send', pk=pk)

        # ── Mode réel : envoi à tous les abonnés ───────────────────────────────
        subscribers = list(Subscriber.objects.filter(site=newsletter.site, is_active=True))
        if not subscribers:
            messages.warning(request, 'Aucun abonné actif pour ce site.')
            return redirect('redaction:newsletter_list')

        sent = 0
        errors = 0
        for subscriber in subscribers:
            unsubscribe_url = request.build_absolute_uri(
                reverse('content:newsletter_unsubscribe', args=[subscriber.token])
            )
            html_body = render_to_string('newsletter/email.html', {
                'newsletter': newsletter,
                'newsletter_articles': articles,
                'site_url': site_url,
                'unsubscribe_url': unsubscribe_url,
                'subscriber': subscriber,
                'is_preview': False,
            }, request=request)
            text_body = f"{newsletter.title}\n\n{newsletter.intro}\n\n" + "\n".join(
                f"- {na.article.title}: {site_url.rstrip('/')}{na.article.get_absolute_url()}"
                for na in articles
            ) + f"\n\nSe désabonner : {unsubscribe_url}"

            try:
                msg = EmailMultiAlternatives(
                    subject=newsletter.title,
                    body=text_body,
                    from_email=None,
                    to=[subscriber.email],
                )
                msg.attach_alternative(html_body, 'text/html')
                msg.send()
                sent += 1
                from django.conf import settings as django_settings
                delay = getattr(django_settings, 'NEWSLETTER_SEND_DELAY', 0)
                if delay:
                    time.sleep(delay)
            except Exception:
                errors += 1

        newsletter.status = 'sent'
        newsletter.sent_at = timezone.now()
        newsletter.sent_by = request.user
        newsletter.sent_count = sent
        newsletter.save(update_fields=['status', 'sent_at', 'sent_by', 'sent_count'])

        if errors:
            messages.warning(request, f'Envoyée à {sent} abonné(s). {errors} erreur(s).')
        else:
            messages.success(request, f'Newsletter envoyée à {sent} abonné(s).')
        return redirect('redaction:newsletter_list')


class NewsletterDeleteView(ChefRequiredMixin, View):
    def post(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)
        current_site = _get_current_site_for_view(request)
        if current_site and newsletter.site != current_site:
            raise PermissionDenied
        newsletter.delete()
        messages.success(request, 'Newsletter supprimée.')
        return redirect('redaction:newsletter_list')


# ── Abonnés ────────────────────────────────────────────────────────────────────

class SubscriberListView(ChefRequiredMixin, ListView):
    model = Subscriber
    template_name = 'redaction/subscriber_list.html'
    context_object_name = 'subscribers'
    paginate_by = 50

    def get_queryset(self):
        current_site = _get_current_site_for_view(self.request)
        if current_site:
            qs = Subscriber.objects.filter(site=current_site)
        else:
            qs = Subscriber.objects.select_related('site')
        status = self.request.GET.get('status')
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'pending':
            qs = qs.filter(is_active=False)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(email__icontains=q)

        sort = self.request.GET.get('sort', '-subscribed_at')
        allowed = ['email', '-email', 'name', '-name', 'subscribed_at', '-subscribed_at', 'is_active', '-is_active']
        if sort not in allowed:
            sort = '-subscribed_at'
        return qs.order_by(sort)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current_site = _get_current_site_for_view(self.request)
        ctx['current_site'] = current_site
        ctx['status_filter'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        ctx['sort'] = self.request.GET.get('sort', '-subscribed_at')
        if current_site:
            ctx['nb_active'] = Subscriber.objects.filter(site=current_site, is_active=True).count()
            ctx['nb_total'] = Subscriber.objects.filter(site=current_site).count()
        ctx['import_form'] = SubscriberImportForm()
        return ctx


class SubscriberAddView(ChefRequiredMixin, View):
    """Ajout manuel d'un abonné depuis l'interface rédaction."""

    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('redaction:subscriber_list')

        email = request.POST.get('email', '').strip().lower()
        name = request.POST.get('name', '').strip()

        if not email or '@' not in email:
            messages.error(request, 'Adresse e-mail invalide.')
            return redirect('redaction:subscriber_list')

        _, created = Subscriber.objects.get_or_create(
            site=current_site,
            email=email,
            defaults={'name': name, 'is_active': True, 'confirmed_at': timezone.now()},
        )
        if created:
            messages.success(request, f'Abonné {email} ajouté.')
        else:
            messages.warning(request, f'{email} est déjà dans la liste.')
        return redirect('redaction:subscriber_list')


class SubscriberImportView(ChefRequiredMixin, View):
    """Import CSV d'abonnés pour le site courant."""

    def post(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('redaction:subscriber_list')
        form = SubscriberImportForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, form.errors['csv_file'][0])
            return redirect('redaction:subscriber_list')

        rows = form.cleaned_data['csv_file']
        created = updated = skipped = 0
        for row in rows:
            email = (row.get('email') or '').strip().lower()
            name = (row.get('nom') or row.get('name') or '').strip()
            if not email or '@' not in email:
                skipped += 1
                continue
            obj, is_new = Subscriber.objects.get_or_create(
                site=current_site, email=email,
                defaults={'name': name, 'is_active': True, 'confirmed_at': timezone.now()},
            )
            if is_new:
                created += 1
            else:
                if name and not obj.name:
                    obj.name = name
                    obj.save(update_fields=['name'])
                updated += 1

        messages.success(request, f'Import terminé : {created} ajouté(s), {updated} existant(s), {skipped} ignoré(s).')
        return redirect('redaction:subscriber_list')


class SubscriberDeleteView(ChefRequiredMixin, View):
    def post(self, request, pk):
        subscriber = get_object_or_404(Subscriber, pk=pk)
        current_site = _get_current_site_for_view(request)
        if current_site and subscriber.site != current_site:
            raise PermissionDenied
        subscriber.delete()
        messages.success(request, f'Abonné {subscriber.email} supprimé.')
        return redirect('redaction:subscriber_list')


class SubscriberExportView(ChefRequiredMixin, View):
    """Export CSV des abonnés actifs du site courant."""

    def get(self, request):
        current_site = _get_current_site_for_view(request)
        if not current_site:
            messages.warning(request, 'Veuillez sélectionner un site.')
            return redirect('redaction:subscriber_list')
        subscribers = Subscriber.objects.filter(site=current_site, is_active=True).order_by('email')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="abonnes-{current_site.slug}.csv"'
        response.write('\ufeff')  # BOM UTF-8 pour Excel
        writer = csv.writer(response)
        writer.writerow(['email', 'nom', 'date_inscription'])
        for s in subscribers:
            writer.writerow([s.email, s.name, s.subscribed_at.strftime('%d/%m/%Y')])
        return response
