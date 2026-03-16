from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View, CreateView, TemplateView
from django.http import Http404
from django.db.models import Q
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from .models import Site, Article, Page, Category, Tag, ContactMessage, Subscriber
from .forms import ContactForm


class HomeView(ListView):
    """Page d'accueil - derniers articles du site principal"""
    model = Article
    template_name = 'content/home.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        return Article.objects.filter(
            site__slug='principal',
            status='publish'
        ).select_related('author', 'site', 'featured_image').prefetch_related('categories')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = Site.objects.get(slug='principal')
        context['sites'] = Site.objects.filter(is_active=True).exclude(slug='principal')

        base_qs = Article.objects.filter(
            site__slug='principal',
            status='publish'
        ).select_related('featured_image').prefetch_related('categories')

        # Articles "À la une" (sticky) — le 1er devient le héro, les suivants les mini-cartes
        sticky_qs = list(base_qs.filter(is_sticky=True)[:4])
        featured = sticky_qs[0] if sticky_qs else base_qs.first()
        context['featured_article'] = featured
        excl = [featured.pk] if featured else []

        # 3 mini cartes : articles sticky suivants, complétés par les plus récents si besoin
        sticky_mini = [a for a in sticky_qs[1:4]]
        if len(sticky_mini) < 3:
            recent = list(base_qs.exclude(pk__in=excl + [a.pk for a in sticky_mini])[:3 - len(sticky_mini)])
            mini = sticky_mini + recent
        else:
            mini = sticky_mini
        context['hero_mini_cards'] = mini
        excl += [a.pk for a in mini]

        # Sidebar: 1 article mini-carte
        context['sidebar_article'] = base_qs.exclude(pk__in=excl).first()

        # Notre flux d'actu: 3 cartes avec images
        flux = list(base_qs.exclude(pk__in=excl)[:3])
        context['flux_grid'] = flux
        excl += [a.pk for a in flux]

        # Les luttes actuelles: 1 grand article
        luttes_qs = base_qs.filter(categories__slug='actualites-luttes')
        luttes_featured = luttes_qs.first()
        context['luttes_featured'] = luttes_featured
        luttes_excl = [luttes_featured.pk] if luttes_featured else []

        # Les luttes: 3 cartes texte en dessous
        context['luttes_text_cards'] = luttes_qs.exclude(pk__in=luttes_excl)[:3]

        # Droits
        context['droits_articles'] = base_qs.filter(categories__slug='droit')[:5]

        # Sans-papiers
        context['sanspapiers_articles'] = base_qs.filter(
            categories__slug='travailleurs-euses-sans-papiers'
        )[:5]

        # Sidebar: Les dernières campagnes
        context['campagnes_articles'] = base_qs.filter(
            categories__slug__in=['international', 'solidarites', 'campagne']
        ).distinct()[:5]

        # Sidebar: Ce que vous avez loupé
        context['manques_articles'] = base_qs.exclude(pk__in=excl)[6:11]

        return context


class SiteAgendaView(TemplateView):
    """Page agenda d'un sous-site (iframe vers agenda externe)"""
    template_name = 'content/site_agenda.html'

    def get(self, request, *args, **kwargs):
        self.site_obj = get_object_or_404(Site, slug=kwargs['site_slug'])
        if not self.site_obj.agenda_url:
            raise Http404
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.site_obj
        context['agenda_url'] = self.site_obj.agenda_url
        return context


class SiteHomeView(ListView):
    """Page d'accueil d'un sous-site"""
    model = Article
    template_name = 'content/site_home.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        if self.current_site.external_url:
            return redirect(self.current_site.external_url)
        self.home_page = Page.objects.filter(
            site=self.current_site, slug='home', status='publish'
        ).first()
        if self.home_page:
            return render(request, 'content/site_home_page.html', {
                'site': self.current_site,
                'page': self.home_page,
            })
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if not hasattr(self, 'current_site'):
            self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        return Article.objects.filter(
            site=self.current_site,
            status='publish'
        ).select_related('author', 'site', 'featured_image').prefetch_related('categories')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['categories'] = Category.objects.filter(site=self.current_site)
        context['pages'] = Page.objects.filter(site=self.current_site, status='publish')
        return context


class ArticleDetailView(DetailView):
    """Détail d'un article"""
    model = Article
    template_name = 'content/article_detail.html'
    context_object_name = 'article'

    def get_object(self, queryset=None):
        slug = self.kwargs['slug']
        # Chercher d'abord sur le site principal
        article = Article.objects.filter(
            slug=slug, site__slug='principal', status='publish'
        ).select_related('author', 'site', 'featured_image').first()
        if not article:
            article = get_object_or_404(
                Article.objects.select_related('author', 'site', 'featured_image'),
                slug=slug, status='publish'
            )
        return article

    def get_queryset(self):
        return Article.objects.filter(status='publish').select_related('author', 'site', 'featured_image')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.object.site
        context['is_gallery'] = self.object.categories.filter(slug='banque-dimage').exists()
        # Articles similaires (même catégorie)
        context['related_articles'] = Article.objects.filter(
            site=self.object.site,
            status='publish',
            categories__in=self.object.categories.all()
        ).exclude(pk=self.object.pk).distinct()[:5]
        # Derniers articles de la catégorie principale (sidebar)
        first_cat = self.object.categories.first()
        context['first_category'] = first_cat
        if first_cat:
            context['category_latest'] = Article.objects.filter(
                site=self.object.site,
                status='publish',
                categories=first_cat,
            ).exclude(pk=self.object.pk).order_by('-published_at')[:5]
        return context


class SiteArticleDetailView(ArticleDetailView):
    """Détail d'un article d'un sous-site"""

    def get_queryset(self):
        self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        return Article.objects.filter(
            site=self.current_site,
            status='publish'
        ).select_related('author', 'site', 'featured_image')

    def get_object(self, queryset=None):
        self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        return get_object_or_404(
            Article.objects.select_related('author', 'site', 'featured_image'),
            slug=self.kwargs['slug'],
            site=self.current_site,
            status='publish',
        )


class PageDetailView(DetailView):
    """Détail d'une page"""
    model = Page
    template_name = 'content/page_detail.html'
    context_object_name = 'page'

    def get_object(self, queryset=None):
        slug = self.kwargs['slug']
        # Chercher d'abord sur le site principal
        page = Page.objects.filter(
            slug=slug, site__slug='principal', status='publish'
        ).select_related('author', 'site').first()
        if not page:
            page = get_object_or_404(Page, slug=slug, status='publish')
        return page

    def get_queryset(self):
        return Page.objects.filter(status='publish').select_related('author', 'site')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.object.site
        return context


class SitePageDetailView(PageDetailView):
    """Détail d'une page d'un sous-site"""

    def get_queryset(self):
        self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        return Page.objects.filter(
            site=self.current_site,
            status='publish'
        ).select_related('author', 'site')


class CategoryDetailView(ListView):
    """Articles d'une catégorie (site principal)"""
    model = Article
    template_name = 'content/category_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        slug = self.kwargs['slug']
        # Chercher d'abord sur le site principal, sinon prendre la première
        self.category = Category.objects.filter(
            slug=slug, site__slug='principal'
        ).first()
        if not self.category:
            self.category = Category.objects.filter(slug=slug).first()
            if not self.category:
                raise Http404

        return Article.objects.filter(
            categories=self.category,
            status='publish'
        ).select_related('author', 'site', 'featured_image')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['site'] = self.category.site
        return context


class SiteCategoryDetailView(ListView):
    """Articles d'une catégorie d'un sous-site"""
    model = Article
    template_name = 'content/category_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        self.current_site = get_object_or_404(Site, slug=kwargs['site_slug'])
        self.category = get_object_or_404(Category, slug=kwargs['slug'], site=self.current_site)
        if self.category.redirect_page:
            return redirect(self.category.redirect_page.get_absolute_url())
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return Article.objects.filter(
            categories=self.category,
            status='publish'
        ).select_related('author', 'site', 'featured_image')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['site'] = self.current_site
        return context


class EspacePresse(ListView):
    """Page Espace Presse conf — articles communiqué de presse du site principal"""
    model = Article
    template_name = 'content/espace_presse.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.current_site = get_object_or_404(Site, slug='principal')
        self.category = Category.objects.filter(
            slug='communique-de-presse', site=self.current_site
        ).first()
        if not self.category:
            return Article.objects.none()
        return Article.objects.filter(
            categories=self.category,
            status='publish'
        ).select_related('author', 'site', 'featured_image').order_by('-published_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['category'] = self.category
        return context


class SiteEspacePresse(ListView):
    """Page Espace Presse d'un sous-site"""
    model = Article
    template_name = 'content/espace_presse.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.current_site = get_object_or_404(Site, slug=self.kwargs['site_slug'])
        self.category = Category.objects.filter(
            slug='communique-de-presse', site=self.current_site
        ).first()
        if not self.category:
            return Article.objects.none()
        return Article.objects.filter(
            categories=self.category,
            status='publish'
        ).select_related('author', 'site', 'featured_image').order_by('-published_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['category'] = self.category
        return context


class TagDetailView(ListView):
    """Articles d'un tag"""
    model = Article
    template_name = 'content/tag_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.tag = get_object_or_404(Tag, slug=self.kwargs['slug'])
        return Article.objects.filter(
            tags=self.tag,
            status='publish'
        ).select_related('author', 'site', 'featured_image')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tag'] = self.tag
        context['site'] = self.tag.site
        return context


class SearchView(ListView):
    """Recherche d'articles"""
    model = Article
    template_name = 'content/search.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        query = self.request.GET.get('q', '')
        if query:
            return Article.objects.filter(
                Q(title__icontains=query) | Q(content__icontains=query),
                status='publish'
            ).select_related('author', 'site', 'featured_image')
        return Article.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        context['site'] = Site.objects.filter(slug='principal').first()
        return context


class WordPressRedirectView(View):
    """Redirection des anciennes URLs WordPress vers les nouvelles"""

    def get(self, request, *args, **kwargs):
        slug = kwargs.get('slug', '')
        site_path = kwargs.get('site_path', '')

        # Chercher l'article par slug
        if site_path:
            # Sous-site: /13/2024/01/slug/ -> chercher dans le site correspondant
            site = Site.objects.filter(path__icontains=site_path).first()
            if site:
                article = Article.objects.filter(site=site, slug=slug, status='publish').first()
                if article:
                    return redirect(article.get_absolute_url(), permanent=True)
                page = Page.objects.filter(site=site, slug=slug, status='publish').first()
                if page:
                    return redirect(page.get_absolute_url(), permanent=True)

        # Site principal ou fallback
        article = Article.objects.filter(slug=slug, status='publish').first()
        if article:
            return redirect(article.get_absolute_url(), permanent=True)

        page = Page.objects.filter(slug=slug, status='publish').first()
        if page:
            return redirect(page.get_absolute_url(), permanent=True)

        raise Http404("Contenu non trouvé")


class ContactView(CreateView):
    """Formulaire de contact"""
    model = ContactMessage
    form_class = ContactForm
    template_name = 'content/contact.html'
    success_url = reverse_lazy('content:contact_success')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = Site.objects.filter(slug='principal').first()
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Votre message a été envoyé avec succès !')
        return super().form_valid(form)


def contact_success(request):
    """Page de confirmation après envoi du formulaire"""
    return render(request, 'content/contact_success.html')


class SiteContactView(CreateView):
    """Formulaire de contact dédié à un site régional"""
    model = ContactMessage
    form_class = ContactForm
    template_name = 'content/contact.html'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.site_obj = get_object_or_404(Site, slug=kwargs['site_slug'])

    def get_success_url(self):
        return reverse_lazy('content:site_contact_success', kwargs={'site_slug': self.site_obj.slug})

    def form_valid(self, form):
        form.instance.site = self.site_obj
        messages.success(self.request, 'Votre message a été envoyé avec succès !')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = self.site_obj
        return ctx


def site_contact_success(request, site_slug):
    site_obj = get_object_or_404(Site, slug=site_slug)
    return render(request, 'content/contact_success.html', {'site': site_obj})


class PlanDuSiteView(TemplateView):
    """Plan du site HTML — site principal ou sous-site"""
    template_name = 'content/plan_du_site.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        site_slug = self.kwargs.get('site_slug', 'principal')
        current = get_object_or_404(Site, slug=site_slug)
        ctx['plan_site'] = current
        ctx['site'] = current
        ctx['categories'] = Category.objects.filter(
            site=current, parent=None
        ).prefetch_related('children').order_by('name')
        ctx['pages'] = Page.objects.filter(
            site=current, status='publish'
        ).order_by('title')
        if site_slug == 'principal':
            ctx['unions_regionales'] = Site.objects.filter(
                is_active=True, site_type='regional'
            ).order_by('name')
            ctx['syndicats_sectoriels'] = Site.objects.filter(
                is_active=True, site_type='sectoral'
            ).order_by('name')
        return ctx


# ── Newsletter publique ────────────────────────────────────────────────────────

class NewsletterSubscribeView(View):
    """Formulaire d'inscription à la newsletter d'un site."""

    def _get_site(self, site_slug=None):
        if site_slug:
            return get_object_or_404(Site, slug=site_slug, is_active=True)
        return get_object_or_404(Site, slug='principal')

    def post(self, request, site_slug=None):
        site = self._get_site(site_slug)
        email = request.POST.get('email', '').strip().lower()
        name = request.POST.get('name', '').strip()

        if not email or '@' not in email:
            messages.error(request, 'Adresse e-mail invalide.')
            return redirect(request.META.get('HTTP_REFERER', '/'))

        subscriber, created = Subscriber.objects.get_or_create(
            site=site, email=email,
            defaults={'name': name},
        )

        if not subscriber.is_active:
            # Envoyer (ou renvoyer) l'e-mail de confirmation
            confirm_url = request.build_absolute_uri(
                reverse_lazy('content:newsletter_confirm', args=[subscriber.token])
            )
            html = render_to_string('newsletter/confirm_email.html', {
                'site': site, 'confirm_url': confirm_url, 'subscriber': subscriber,
            }, request=request)
            text = f"Confirmez votre inscription à la newsletter {site.name} :\n{confirm_url}"
            try:
                msg = EmailMultiAlternatives(
                    subject=f"Confirmez votre inscription — {site.name}",
                    body=text,
                    from_email=None,
                    to=[email],
                )
                msg.attach_alternative(html, 'text/html')
                msg.send()
            except Exception:
                pass  # Ne pas bloquer l'utilisateur si l'e-mail échoue

        return render(request, 'content/newsletter_subscribe_done.html', {
            'site': site, 'email': email, 'already_active': subscriber.is_active,
        })


class NewsletterConfirmView(View):
    """Confirmation d'inscription via le lien envoyé par e-mail."""

    def get(self, request, token):
        subscriber = get_object_or_404(Subscriber, token=token)
        if not subscriber.is_active:
            subscriber.is_active = True
            subscriber.confirmed_at = timezone.now()
            subscriber.save(update_fields=['is_active', 'confirmed_at'])
        return render(request, 'content/newsletter_confirm.html', {
            'subscriber': subscriber, 'site': subscriber.site,
        })


class NewsletterUnsubscribeView(View):
    """Désinscription via le lien dans le pied de l'e-mail."""

    def get(self, request, token):
        subscriber = get_object_or_404(Subscriber, token=token)
        return render(request, 'content/newsletter_unsubscribe.html', {
            'subscriber': subscriber, 'site': subscriber.site,
        })

    def post(self, request, token):
        subscriber = get_object_or_404(Subscriber, token=token)
        subscriber.is_active = False
        subscriber.save(update_fields=['is_active'])
        return render(request, 'content/newsletter_unsubscribe_done.html', {
            'site': subscriber.site,
        })


class QuiSommesNousView(TemplateView):
    """Page Qui sommes-nous ?"""
    template_name = 'content/qui_sommes_nous.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = Site.objects.filter(slug='principal').first()

        # Contenu de la page depuis la DB (si elle existe)
        ctx['page'] = Page.objects.filter(
            slug='qui-sommes-nous', site__slug='principal', status='publish'
        ).first()

        base_qs = (
            Article.objects
            .filter(site__slug='principal', status='publish')
            .select_related('featured_image')
            .prefetch_related('categories')
        )
        ctx['campagnes_articles'] = base_qs.filter(
            categories__slug__in=['international', 'solidarites', 'campagne']
        ).distinct()[:5]
        ctx['manques_articles'] = base_qs[:6]
        return ctx
