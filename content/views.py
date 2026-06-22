from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View, CreateView, TemplateView
from django.http import Http404
from django.db.models import Q, Case, When, Value, IntegerField
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from .models import Page, Category, ContactMessage, FormulaireContact, Subscriber
from .forms import ContactForm, DynamicContactForm
from cms.models import ArticlePage, CmsCategory, SectionPage
from taggit.models import Tag as TaggitTag


def _sectoral_sidebar_context(site):
    """Contexte commun pour la sidebar des sous-sites sectoriel/régional."""
    from content.models import MenuItem
    rejoindre_menu = MenuItem.objects.filter(
        site=site, url__icontains='rejoindre', is_active=True,
    ).first()
    return {
        'rejoindre_url': (rejoindre_menu.url if rejoindre_menu else None) or site.framaform_url or '#',
        'manques_articles': (
            ArticlePage.objects.live()
            .filter(section_slug='principal')
            .order_by('-publication_date', '-first_published_at')
            .select_related('featured_image')
            .prefetch_related('cms_categories')[:5]
        ),
    }


class HomeView(ListView):
    """Page d'accueil - derniers articles du site principal"""
    model = ArticlePage
    template_name = 'content/home.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        return (ArticlePage.objects.live()
                .filter(section_slug='principal')
                .order_by('-publication_date', '-first_published_at')
                .select_related('featured_image')
                .prefetch_related('cms_categories'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        main_site = SectionPage.objects.filter(slug='principal').first()
        context['site'] = main_site
        context['sites'] = SectionPage.objects.filter(live=True).exclude(slug='principal')

        base_qs = (ArticlePage.objects.live()
                   .filter(section_slug='principal')
                   .order_by('-publication_date', '-first_published_at')
                   .select_related('featured_image')
                   .prefetch_related('cms_categories'))

        # Carousel : carousel_items du SectionPage principal, fallback articles récents avec image
        carousel = []
        if main_site:
            carousel = [
                ci.article for ci in
                main_site.carousel_items.select_related('article__featured_image').all()
                if ci.article and ci.article.live
            ]
        if not carousel:
            carousel = list(base_qs.exclude(featured_image=None)[:5])
        context['carousel_articles'] = carousel
        excl = [a.pk for a in carousel]

        # Manchette : 6 articles conf avec image
        manchette = list(base_qs.exclude(pk__in=excl).exclude(featured_image=None)[:6])
        context['manchette_articles'] = manchette
        excl += [a.pk for a in manchette]

        # 9 derniers articles de tout le réseau (conf + sous-sites)
        section_names = dict(SectionPage.objects.filter(live=True).values_list('slug', 'title'))
        all_latest = list(
            ArticlePage.objects.live()
            .order_by('-publication_date', '-first_published_at')
            .select_related('featured_image')
            .prefetch_related('cms_categories')
            .exclude(pk__in=excl)[:9]
        )
        for a in all_latest:
            a._site_name = section_names.get(a.section_slug, '')
        context['all_latest_articles'] = all_latest

        # Droits
        context['droits_articles'] = base_qs.filter(cms_categories__slug='droit')[:5]
        # Actions (remplace sans-papiers)
        context['actions_articles'] = base_qs.filter(cms_categories__slug='actions')[:5]

        context['campagnes_articles'] = base_qs.filter(
            cms_categories__slug__in=['international', 'solidarites', 'campagne']
        ).distinct()[:5]
        context['manques_articles'] = base_qs.exclude(pk__in=excl)[:5]

        return context


class SiteAgendaView(TemplateView):
    """Page agenda d'un sous-site : événements CMS ou iframe externe."""

    def get_template_names(self):
        if getattr(self, 'site_obj', None) and self.site_obj.agenda_url:
            return ['content/site_agenda.html']
        return ['content/site_agenda_events.html']

    def get(self, request, *args, **kwargs):
        self.site_obj = get_object_or_404(SectionPage, slug=kwargs['site_slug'])
        return TemplateView.get(self, request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.site_obj
        context.update(_sectoral_sidebar_context(self.site_obj))
        if self.site_obj.agenda_url:
            context['agenda_url'] = self.site_obj.agenda_url
        else:
            from cms.models import Event
            today = timezone.now().date()
            context['upcoming_events'] = (
                Event.objects.filter(section=self.site_obj, date__gte=today)
                .order_by('date', 'time')
            )
            context['past_events'] = (
                Event.objects.filter(section=self.site_obj, date__lt=today)
                .order_by('-date', '-time')[:10]
            )
            context['agenda_text'] = self.site_obj.agenda_text
        return context


class SiteHomeView(ListView):
    """Page d'accueil d'un sous-site"""
    model = ArticlePage
    context_object_name = 'articles'
    paginate_by = 10

    def get_template_names(self):
        if getattr(self, 'current_site', None) and self.current_site.section_type in ('sectoral', 'regional'):
            return ['content/sectoral_site_home.html']
        return ['content/site_home.html']

    def get(self, request, *args, **kwargs):
        self.current_site = get_object_or_404(SectionPage, slug=self.kwargs['site_slug'])
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
            self.current_site = get_object_or_404(SectionPage, slug=self.kwargs['site_slug'])
        return (ArticlePage.objects.live()
                .filter(section_slug=self.current_site.slug)
                .select_related('featured_image')
                .prefetch_related('cms_categories')
                .annotate(has_img=Case(
                    When(featured_image__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ))
                .order_by('-has_img', '-first_published_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['categories'] = Category.objects.filter(site=self.current_site).select_related('site')
        context['pages'] = Page.objects.filter(site=self.current_site, status='publish')
        if self.current_site.section_type in ('sectoral', 'regional'):
            carousel = [
                ci.article for ci in
                self.current_site.carousel_items.select_related('article').all()
            ]
            if not carousel:
                candidates = list(
                    ArticlePage.objects.live()
                    .filter(section_slug=self.current_site.slug)
                    .select_related('featured_image')
                    .order_by('-first_published_at')[:20]
                )
                carousel = [a for a in candidates if a.any_image_url][:5]
            context['carousel_articles'] = carousel
            from content.models import MenuItem
            rejoindre_menu = MenuItem.objects.filter(
                site=self.current_site,
                url__icontains='rejoindre',
                is_active=True,
            ).first()
            context['rejoindre_url'] = (
                (rejoindre_menu.url if rejoindre_menu else None)
                or self.current_site.framaform_url
                or '#'
            )
        return context


class ArticleDetailView(DetailView):
    """Détail d'un article"""
    model = ArticlePage
    template_name = 'content/article_detail.html'
    context_object_name = 'article'

    def get_object(self, queryset=None):
        slug = self.kwargs['slug']
        article = (ArticlePage.objects.live()
                   .filter(slug=slug, section_slug='principal')
                   .select_related('featured_image').first())
        if not article:
            article = get_object_or_404(
                ArticlePage.objects.live().select_related('featured_image'),
                slug=slug,
            )
        return article

    def get_queryset(self):
        return ArticlePage.objects.live().select_related('featured_image')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        section = self.object.section_slug or 'principal'
        context['site'] = SectionPage.objects.filter(slug=section).first()
        context['is_gallery'] = self.object.cms_categories.filter(slug='banque-dimage').exists()
        context['related_articles'] = (ArticlePage.objects.live()
            .filter(section_slug=section, cms_categories__in=self.object.cms_categories.all())
            .exclude(pk=self.object.pk).distinct()
            .select_related('featured_image').prefetch_related('cms_categories')[:5])
        first_cat = self.object.cms_categories.first()
        context['first_category'] = first_cat
        if first_cat:
            context['category_latest'] = (ArticlePage.objects.live()
                .filter(section_slug=section, cms_categories=first_cat)
                .exclude(pk=self.object.pk)
                .order_by('-publication_date', '-first_published_at')
                .select_related('featured_image')[:5])
        return context


class SiteArticleDetailView(ArticleDetailView):
    """Détail d'un article d'un sous-site"""

    def get_queryset(self):
        self.current_site = get_object_or_404(SectionPage, slug=self.kwargs['site_slug'])
        return (ArticlePage.objects.live()
                .filter(section_slug=self.current_site.slug)
                .select_related('featured_image'))

    def get_object(self, queryset=None):
        self.current_site = get_object_or_404(SectionPage, slug=self.kwargs['site_slug'])
        return get_object_or_404(
            ArticlePage.objects.live().select_related('featured_image'),
            slug=self.kwargs['slug'],
            section_slug=self.current_site.slug,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site = context.get('site') or self.current_site
        if site and site.section_type in ('sectoral', 'regional'):
            from content.models import MenuItem
            rejoindre_menu = MenuItem.objects.filter(
                site=site, url__icontains='rejoindre', is_active=True,
            ).first()
            context['rejoindre_url'] = (
                (rejoindre_menu.url if rejoindre_menu else None)
                or site.framaform_url or '#'
            )
            context['manques_articles'] = (
                ArticlePage.objects.live()
                .filter(section_slug='principal')
                .order_by('-publication_date', '-first_published_at')
                .select_related('featured_image')
                .prefetch_related('cms_categories')[:5]
            )
        return context


class PageDetailView(View):
    """Redirige les anciennes URLs /page/<slug>/ vers cms.ContentPage si migré, sinon legacy."""

    def get(self, request, slug, **kwargs):
        from cms.models import ContentPage
        from django.http import HttpResponsePermanentRedirect
        cp = ContentPage.objects.live().filter(slug=slug).first()
        if cp:
            return HttpResponsePermanentRedirect(cp.get_absolute_url())
        # Fallback : servir la page legacy
        page = get_object_or_404(Page, slug=slug, status='publish')
        return render(request, 'content/page_detail.html', {
            'page': page,
            'site': page.site,
        })


class SitePageDetailView(View):
    """Redirige les anciennes URLs /<site>/page/<slug>/ vers ContentPage si migré."""

    def get(self, request, site_slug, slug, **kwargs):
        from cms.models import ContentPage
        from django.http import HttpResponsePermanentRedirect
        cp = ContentPage.objects.live().filter(slug=slug, section_slug=site_slug).first()
        if cp:
            return HttpResponsePermanentRedirect(cp.get_absolute_url())
        current_site = get_object_or_404(SectionPage, slug=site_slug)
        page = get_object_or_404(Page, slug=slug, site=current_site, status='publish')
        return render(request, 'content/page_detail.html', {
            'page': page,
            'site': current_site,
        })


class CategoryDetailView(ListView):
    """Articles d'une catégorie (site principal)"""
    model = ArticlePage
    template_name = 'content/category_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        slug = self.kwargs['slug']
        self.category = CmsCategory.objects.filter(slug=slug, section_slug='principal').first()
        if not self.category:
            self.category = CmsCategory.objects.filter(slug=slug).first()
            if not self.category:
                raise Http404
        return (ArticlePage.objects.live()
                .filter(cms_categories=self.category)
                .select_related('featured_image')
                .prefetch_related('cms_categories'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['site'] = SectionPage.objects.filter(slug=self.category.section_slug or 'principal').first()
        return context


class SiteCategoryDetailView(ListView):
    """Articles d'une catégorie d'un sous-site"""
    model = ArticlePage
    template_name = 'content/category_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        self.current_site = get_object_or_404(SectionPage, slug=kwargs['site_slug'])
        self.category = get_object_or_404(CmsCategory, slug=kwargs['slug'], section_slug=self.current_site.slug)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return (ArticlePage.objects.live()
                .filter(cms_categories=self.category)
                .select_related('featured_image')
                .prefetch_related('cms_categories'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['site'] = self.current_site
        return context


class EspacePresse(ListView):
    """Page Espace Presse conf — articles communiqué de presse du site principal"""
    model = ArticlePage
    template_name = 'content/espace_presse.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.current_site = get_object_or_404(SectionPage, slug='principal')
        self.category = CmsCategory.objects.filter(
            slug='communique-de-presse', section_slug='principal'
        ).first()
        if not self.category:
            return ArticlePage.objects.none()
        return (ArticlePage.objects.live()
                .filter(cms_categories=self.category)
                .select_related('featured_image')
                .prefetch_related('cms_categories')
                .order_by('-publication_date', '-first_published_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['category'] = self.category
        return context


class SiteEspacePresse(ListView):
    """Page Espace Presse d'un sous-site"""
    model = ArticlePage
    template_name = 'content/espace_presse.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.current_site = get_object_or_404(SectionPage, slug=self.kwargs['site_slug'])
        self.category = CmsCategory.objects.filter(
            slug='communique-de-presse', section_slug=self.current_site.slug
        ).first()
        if not self.category:
            return ArticlePage.objects.none()
        return (ArticlePage.objects.live()
                .filter(cms_categories=self.category)
                .select_related('featured_image')
                .prefetch_related('cms_categories')
                .order_by('-publication_date', '-first_published_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.current_site
        context['category'] = self.category
        return context


class TagDetailView(ListView):
    """Articles d'un tag"""
    model = ArticlePage
    template_name = 'content/tag_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.tag = get_object_or_404(TaggitTag, slug=self.kwargs['slug'])
        return (ArticlePage.objects.live()
                .filter(cms_tags__slug=self.kwargs['slug'])
                .select_related('featured_image')
                .prefetch_related('cms_categories'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tag'] = self.tag
        context['site'] = SectionPage.objects.filter(slug='principal').first()
        return context


class SearchView(ListView):
    """Recherche d'articles"""
    model = ArticlePage
    template_name = 'content/search.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        from wagtail.search.backends import get_search_backend
        query = self.request.GET.get('q', '').strip()
        if not query:
            return ArticlePage.objects.none()
        backend = get_search_backend()
        results = backend.search(
            query,
            ArticlePage.objects.live().select_related('featured_image').prefetch_related('cms_categories'),
            order_by_relevance=True,
        )
        return results

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        context['site'] = SectionPage.objects.filter(slug='principal').first()
        return context


class WordPressRedirectView(View):
    """Redirection des anciennes URLs WordPress vers les nouvelles"""

    def get(self, request, *args, **kwargs):
        slug = kwargs.get('slug', '')
        site_path = kwargs.get('site_path', '')

        # Chercher l'article par slug
        if site_path:
            # Sous-site: /13/2024/01/slug/ -> chercher dans le site correspondant
            site = SectionPage.objects.filter(wp_path__icontains=site_path).first()
            if site:
                article = ArticlePage.objects.live().filter(section_slug=site.slug, slug=slug).first()
                if article:
                    return redirect(article.get_absolute_url(), permanent=True)
                page = Page.objects.filter(site=site, slug=slug, status='publish').first()
                if page:
                    return redirect(page.get_absolute_url(), permanent=True)

        # Site principal ou fallback
        article = ArticlePage.objects.live().filter(slug=slug).first()
        if article:
            return redirect(article.get_absolute_url(), permanent=True)

        page = Page.objects.filter(slug=slug, status='publish').first()
        if page:
            return redirect(page.get_absolute_url(), permanent=True)

        raise Http404("Contenu non trouvé")


def _send_contact_email(site, message_obj):
    """Envoie le message de contact à l'adresse configurée sur le site ou le formulaire."""
    from django.conf import settings
    formulaire = getattr(message_obj, 'formulaire', None)
    if formulaire:
        recipient = formulaire.get_email_destination()
        prefix = formulaire.email_subject_prefix
    else:
        recipient = site.contact_email if site else ''
        prefix = ''
    if not recipient:
        recipient = getattr(settings, 'DEFAULT_CONTACT_EMAIL', settings.DEFAULT_FROM_EMAIL)
    if not recipient:
        return

    site_name = site.name if site else 'CNT-SO'
    subject = f'{prefix or f"[Contact {site_name}]"}'
    objet = message_obj.subject or ''
    if objet:
        subject += f' — {objet}'

    lines = [
        f'Nom : {message_obj.name}',
        f'Email : {message_obj.email}',
    ]
    if message_obj.phone:
        lines.append(f'Téléphone : {message_obj.phone}')
    if message_obj.city:
        lines.append(f'Ville : {message_obj.city}')
    if message_obj.sector:
        lines.append(f'Secteur : {message_obj.sector}')
    if objet:
        lines.append(f'Objet : {objet}')
    if message_obj.custom_data:
        for k, v in message_obj.custom_data.items():
            lines.append(f'{k} : {v}')
    lines += ['', message_obj.message]

    safe_name = message_obj.name.replace('\n', ' ').replace('\r', ' ')
    email = EmailMultiAlternatives(
        subject=subject,
        body='\n'.join(lines),
        from_email=f'{safe_name} via {site_name} <{settings.DEFAULT_FROM_EMAIL}>',
        to=[recipient],
        reply_to=[message_obj.email],
    )
    try:
        email.send(fail_silently=True)
    except Exception:
        pass


class _BaseContactView(View):
    """Mixin partagé pour les vues de contact (principal et sous-sites)."""
    template_name = 'content/contact.html'

    def _get_formulaire(self, site):
        try:
            return site.formulaire_contact if site else None
        except FormulaireContact.DoesNotExist:
            return None

    def _build_form(self, formulaire, data=None):
        if formulaire:
            return DynamicContactForm(data, formulaire=formulaire)
        return ContactForm(data)

    def _save_submission(self, form, site, formulaire):
        cd = form.cleaned_data
        if formulaire:
            msg = ContactMessage(
                site=site,
                formulaire=formulaire,
                email=cd['email'],
                name=cd.get('nom', ''),
                phone=cd.get('telephone', ''),
                city=cd.get('ville', ''),
                sector=cd.get('secteur', ''),
                subject=cd.get('objet', ''),
                message=cd.get('message', ''),
                custom_data=form.get_custom_data(formulaire),
            )
        else:
            msg = ContactMessage(
                site=site,
                name=cd.get('name', ''),
                email=cd['email'],
                phone=cd.get('phone', ''),
                city=cd.get('city', ''),
                sector=cd.get('sector', ''),
                subject=cd.get('subject', ''),
                message=cd.get('message', ''),
            )
        msg.save()
        return msg

    def get(self, request, site, success_url):
        formulaire = self._get_formulaire(site)
        form = self._build_form(formulaire)
        return render(request, self.template_name, {
            'form': form, 'site': site, 'formulaire': formulaire,
        })

    def post(self, request, site, success_url):
        formulaire = self._get_formulaire(site)
        form = self._build_form(formulaire, request.POST)
        if form.is_valid():
            msg = self._save_submission(form, site, formulaire)
            _send_contact_email(site, msg)
            messages.success(request, 'Votre message a été envoyé avec succès !')
            return redirect(success_url)
        return render(request, self.template_name, {
            'form': form, 'site': site, 'formulaire': formulaire,
        })


class ContactView(_BaseContactView):
    def get(self, request, *args, **kwargs):
        site = SectionPage.objects.filter(slug='principal').first()
        return super().get(request, site, reverse_lazy('content:contact_success'))

    def post(self, request, *args, **kwargs):
        site = SectionPage.objects.filter(slug='principal').first()
        return super().post(request, site, reverse_lazy('content:contact_success'))


def contact_success(request):
    return render(request, 'content/contact_success.html')


class SiteContactView(_BaseContactView):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        slug = kwargs['site_slug']
        self.site_obj = SectionPage.objects.filter(Q(slug=slug) | Q(legacy_site_slug=slug)).first()
        if self.site_obj is None:
            raise Http404

    def get(self, request, *args, **kwargs):
        url = reverse_lazy('content:site_contact_success', kwargs={'site_slug': self.site_obj.legacy_site_slug or self.site_obj.slug})
        return super().get(request, self.site_obj, url)

    def post(self, request, *args, **kwargs):
        url = reverse_lazy('content:site_contact_success', kwargs={'site_slug': self.site_obj.legacy_site_slug or self.site_obj.slug})
        return super().post(request, self.site_obj, url)


def site_contact_success(request, site_slug):
    site_obj = SectionPage.objects.filter(Q(slug=site_slug) | Q(legacy_site_slug=site_slug)).first()
    if site_obj is None:
        raise Http404
    return render(request, 'content/contact_success.html', {'site': site_obj})


class PlanDuSiteView(TemplateView):
    """Plan du site HTML — site principal ou sous-site"""
    template_name = 'content/plan_du_site.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        site_slug = self.kwargs.get('site_slug', 'principal')
        current = get_object_or_404(SectionPage, slug=site_slug)
        ctx['plan_site'] = current
        ctx['site'] = current

        # Grouper les catégories de même nom (ex: 9x "Actualité & luttes" par secteur)
        from collections import defaultdict
        from os.path import commonprefix

        from django.db.models import Prefetch
        children_qs = Category.objects.select_related('site')
        raw_cats = list(
            Category.objects.filter(site=current, parent=None)
            .select_related('site')
            .prefetch_related(Prefetch('children', queryset=children_qs))
            .order_by('name')
        )
        grouped = defaultdict(list)
        for cat in raw_cats:
            grouped[cat.name].append(cat)

        cat_groups = []
        for name, cats in sorted(grouped.items()):
            if len(cats) == 1:
                cat_groups.append({
                    'name': name,
                    'url': cats[0].get_absolute_url(),
                    'children': [{'name': c.name, 'url': c.get_absolute_url()} for c in cats[0].children.all()],
                })
            else:
                # Trouver le préfixe commun des slugs pour extraire le secteur
                prefix = commonprefix([c.slug for c in cats])
                children = []
                for c in sorted(cats, key=lambda x: x.slug):
                    sector = c.slug[len(prefix):].strip('-').replace('-', ' ')
                    label = sector.capitalize() if sector else c.slug
                    children.append({'name': label, 'url': c.get_absolute_url()})
                cat_groups.append({'name': name, 'url': None, 'children': children})
        ctx['cat_groups'] = cat_groups

        ctx['pages'] = Page.objects.filter(
            site=current, status='publish'
        ).select_related('site').order_by('title')
        if site_slug == 'principal':
            ctx['unions_regionales'] = SectionPage.objects.filter(
                live=True, section_type='regional'
            ).order_by('title')
            ctx['syndicats_sectoriels'] = SectionPage.objects.filter(
                live=True, section_type='sectoral'
            ).order_by('title')
        return ctx


# ── Newsletter publique ────────────────────────────────────────────────────────

class NewsletterSubscribeView(View):
    """Formulaire d'inscription à la newsletter d'un site."""

    def _get_site(self, site_slug=None):
        if site_slug:
            return get_object_or_404(SectionPage, slug=site_slug, live=True)
        return get_object_or_404(SectionPage, slug='principal')

    def post(self, request, site_slug=None):
        site = self._get_site(site_slug)
        email = request.POST.get('email', '').strip().lower()
        name = request.POST.get('name', '').strip()

        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        try:
            validate_email(email)
        except ValidationError:
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
        ctx['site'] = SectionPage.objects.filter(slug='principal').first()

        # Contenu de la page depuis la DB (si elle existe)
        ctx['page'] = Page.objects.filter(
            slug='qui-sommes-nous', site__slug='principal', status='publish'
        ).first()

        base_qs = (
            ArticlePage.objects.live()
            .filter(section_slug='principal')
            .select_related('featured_image')
            .prefetch_related('cms_categories')
        )
        ctx['campagnes_articles'] = base_qs.filter(
            cms_categories__slug__in=['international', 'solidarites', 'campagne']
        ).distinct()[:5]
        ctx['manques_articles'] = base_qs[:6]
        return ctx


# ── Vues STUCS ────────────────────────────────────────────────────────────────

class SiteRejoindreView(View):
    """Page 'Nous rejoindre' générique pour tout sous-site."""

    def _ctx(self, site_slug):
        site = get_object_or_404(SectionPage, slug=site_slug)
        ctx = {'site': site, 'categories': CmsCategory.objects.filter(section_slug=site_slug)}
        ctx.update(_sectoral_sidebar_context(site))
        return ctx

    def get(self, request, site_slug):
        ctx = self._ctx(site_slug)
        ctx['form'] = ContactForm()
        return render(request, 'content/site_rejoindre.html', ctx)

    def post(self, request, site_slug):
        ctx = self._ctx(site_slug)
        form = ContactForm(request.POST)
        ctx['form'] = form
        if form.is_valid():
            site = ctx['site']
            msg = ContactMessage(
                site=site,
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                message=form.cleaned_data['message'],
            )
            msg.save()
            _send_contact_email(site, msg)
            ctx['success'] = True
        return render(request, 'content/site_rejoindre.html', ctx)


class SiteRessourcesView(View):
    """Page 'Ressources' générique pour tout sous-site."""

    def get(self, request, site_slug):
        site = get_object_or_404(SectionPage, slug=site_slug)
        categories = CmsCategory.objects.filter(section_slug=site_slug)
        slug = request.GET.get('cat', '')
        active_cat = CmsCategory.objects.filter(section_slug=site_slug, slug=slug).first() if slug else None
        qs = ArticlePage.objects.live().filter(section_slug=site_slug)
        if active_cat:
            qs = qs.filter(cms_categories=active_cat)
        articles = qs.select_related('featured_image').order_by('-publication_date', '-first_published_at')
        ctx = {
            'site': site,
            'categories': categories,
            'active_cat': active_cat,
            'articles': articles,
        }
        ctx.update(_sectoral_sidebar_context(site))
        return render(request, 'content/site_ressources.html', ctx)
