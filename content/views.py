from datetime import datetime, timezone as dt_timezone
from itertools import chain

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View, CreateView, TemplateView
from django.http import Http404
from django.db.models import Q, Case, When, Value, IntegerField
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from .models import (Page, ContactMessage, FormulaireContact, Subscriber,
                     ExternalArticle)
from .courriel import destinataire_de_reponse
from .forms import (ContactForm, DynamicContactForm, NewsletterCaptchaForm,
                    NewsletterSubscribeForm, NewsletterUnsubscribeForm)
from cms.models import ArticlePage, CmsCategory, SectionPage, _cle_de_nom
from taggit.models import Tag as TaggitTag


def get_section_or_404(slug, inclure_depublies=False, **extra):
    """Résout une SectionPage PUBLIÉE par son slug Wagtail *ou* son slug hérité.

    Sur un domaine autonome, `SectionDomainMiddleware` préfixe le chemin avec
    `legacy_site_slug` quand celui-ci diffère du slug (cas Numérique : slug
    « numerique », legacy « stnum »). Chercher sur le seul `slug` renvoyait
    alors un 404 sur toutes les pages du sous-site sauf le contact et la home.

    Le filtre sur `live` est le point important : dépublier un syndicat le
    retirait des menus et des listes, mais ses URL continuaient de servir —
    ses pages comme ses articles. Un site « désactivé » restait donc ouvert à
    quiconque avait l'adresse, un signet ou un résultat de moteur de recherche
    (constaté sur Rhône-Alpes, 16/08/2026). Dépublier ferme désormais le site.

    `inclure_depublies` n'est là que pour les rares appels qui doivent voir un
    syndicat dépublié — jamais depuis une vue publique.
    """
    if not inclure_depublies:
        extra.setdefault('live', True)
    section = SectionPage.objects.filter(
        Q(slug=slug) | Q(legacy_site_slug=slug), **extra
    ).first()
    if section is None:
        raise Http404(f"Syndicat introuvable ou dépublié : {slug}")
    return section


def _sidebar_context(section_slug):
    """Contexte campagnes/incontournables pour la sidebar, filtré par section."""
    base_qs = (
        ArticlePage.objects.live()
        .filter(section_slug=section_slug)
        .order_by('-publication_date', '-first_published_at')
        .select_related('featured_image')
        .prefetch_related('cms_categories')
    )
    return {
        'campagnes_articles': base_qs.filter(cms_categories__slug='campagne').distinct()[:5],
        # « Ce que vous avez loupé », ce sont les articles récents — pas ceux
        # d'une catégorie « incontournables » qui n'existe dans AUCUNE section :
        # le cartouche était vide depuis toujours, sur la conf comme sur les
        # sous-sites (constaté en production, 17/08/2026).
        'manques_articles': base_qs.distinct()[:5],
    }


def _sectoral_sidebar_context(site):
    """Contexte commun pour la sidebar des sous-sites sectoriel/régional."""
    ctx = _sidebar_context(site.slug)
    ctx['rejoindre_url'] = site.get_rejoindre_url()
    # Le cartouche « Nouvelles de la confédération » recevait les articles du
    # sous-site lui-même : il annonçait la conf et montrait autre chose — rien,
    # en l'occurrence. Il montre désormais ce que son titre promet.
    ctx['manques_articles'] = (
        ArticlePage.objects.live()
        .filter(section_slug='principal')
        .order_by('-publication_date', '-first_published_at')
        .select_related('featured_image')
        .prefetch_related('cms_categories')
        .distinct()[:5]
    )
    return ctx


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
        # Compléter jusqu'à 5, plutôt que de tout couper au premier choisi.
        # Avant le 16/08/2026, un seul article épinglé faisait disparaître les
        # quatre autres : mettre un article en avant en retirait quatre.
        carousel = _completer_carrousel(carousel, base_qs.exclude(featured_image=None))
        context['carousel_articles'] = carousel
        excl = [a.pk for a in carousel]

        # Manchette : 6 articles conf avec image
        manchette = list(base_qs.exclude(pk__in=excl).exclude(featured_image=None)[:6])
        context['manchette_articles'] = manchette
        excl += [a.pk for a in manchette]

        # 9 articles du réseau, c'est-à-dire des syndicats et fédérations
        # UNIQUEMENT : la confédération occupe déjà tout le haut de la page
        # (carrousel, sélection, colonnes). L'y remettre ici noyait les
        # sous-sites, seul endroit de l'accueil où ils s'expriment.
        section_names = dict(SectionPage.objects.filter(live=True).values_list('slug', 'title'))
        context['all_latest_articles'] = _reseau_tour_de_table(
            _candidats_reseau(excl), section_names, nb=9)

        # Droits
        context['droits_articles'] = base_qs.filter(cms_categories__slug='droit')[:5]
        # Actions (remplace sans-papiers)
        context['actions_articles'] = base_qs.filter(cms_categories__slug='actions')[:5]

        context.update(_sidebar_context('principal'))

        return context


class SiteAgendaView(TemplateView):
    """Page agenda d'un sous-site : événements CMS ou iframe externe."""

    def get_template_names(self):
        if getattr(self, 'site_obj', None) and self.site_obj.agenda_url:
            return ['content/site_agenda.html']
        return ['content/site_agenda_events.html']

    def get(self, request, *args, **kwargs):
        self.site_obj = get_section_or_404(kwargs['site_slug'])
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


#: Date de repli pour un article sans aucune date : il passe en dernier plutôt
#: que de faire échouer le tri de tout le cartouche.
_DATE_ZERO = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


def _date_reseau(article):
    """Date commune à nos articles et à ceux moissonnés ailleurs."""
    return (getattr(article, 'published_at', None)
            or getattr(article, 'publication_date', None)
            or getattr(article, 'first_published_at', None)
            or _DATE_ZERO)


def _candidats_reseau(exclus, nb=60):
    """Les articles récents des syndicats : les nôtres ET ceux d'ailleurs.

    Un syndicat hébergé sur son propre site (le STAA, le TAS) n'a aucune
    `ArticlePage` chez nous : à ne regarder que notre base, il était absent du
    cartouche « réseau », c'est-à-dire du seul endroit de l'accueil où les
    sous-sites s'expriment. On y ajoute donc les articles moissonnés dans leurs
    flux par la commande `sync_flux_reseau` — jamais lus en direct ici : un
    serveur voisin en panne ferait tomber l'accueil de la confédération.

    La confédération est exclue des deux côtés : elle occupe déjà tout le haut
    de la page.
    """
    locaux = (
        ArticlePage.objects.live()
        .exclude(section_slug='principal')
        .order_by('-publication_date', '-first_published_at')
        .select_related('featured_image')
        .prefetch_related('cms_categories')
        .exclude(pk__in=exclus)[:nb]
    )
    externes = (
        ExternalArticle.objects
        .filter(section__live=True)
        .exclude(section__slug='principal')
        .select_related('section')
        .order_by('-published_at')[:nb]
    )
    return sorted(chain(locaux, externes), key=_date_reseau, reverse=True)


def _reseau_tour_de_table(candidats, noms_de_sites, nb=9):
    """Répartit les places du « réseau » entre les sites, par tour de table.

    À prendre simplement les N plus récents, le site le plus bavard raflait
    tout : dans la base de développement, les 9 places revenaient au même
    syndicat, et les autres n'apparaissaient nulle part sur l'accueil. On sert
    donc d'abord le dernier article de chaque site, puis l'avant-dernier de
    chacun, et ainsi de suite jusqu'à remplir les places.

    L'ordre des sites reste celui de leur article le plus récent : le réseau
    montre bien l'actualité en premier, mais une place par site avant d'en
    accorder une deuxième à quiconque. Un site seul remplit tout, comme avant.

    `candidats` doit déjà être trié du plus récent au plus ancien.
    """
    par_site = {}
    for article in candidats:
        par_site.setdefault(article.section_slug, []).append(article)

    resultat = []
    while len(resultat) < nb and any(par_site.values()):
        for articles in par_site.values():
            if not articles:
                continue
            resultat.append(articles.pop(0))
            if len(resultat) >= nb:
                break

    for article in resultat:
        article.source_site = noms_de_sites.get(article.section_slug, '')
    return resultat


def _completer_carrousel(choisis, candidats, maximum=5):
    """Les articles épinglés d'abord, puis les récents illustrés jusqu'à 5.

    Le carrousel fonctionnait en tout ou rien : tant qu'aucun article n'était
    coché, l'accueil affichait les 5 récents illustrés ; dès qu'un seul était
    coché, l'automatique s'arrêtait et le carrousel n'affichait plus que celui-
    là. Mettre un article en avant en retirait donc quatre — l'inverse de ce
    qu'attend un rédacteur (relevé par Arnaud, 15/08/2026).

    L'ordre voulu par le syndicat est conservé : les choisis restent en tête,
    dans leur ordre, et le complément ne fait que remplir les places libres.
    """
    resultat = list(choisis)[:maximum]
    deja = {a.pk for a in resultat}
    for article in candidats:
        if len(resultat) >= maximum:
            break
        if article.pk not in deja:
            resultat.append(article)
            deja.add(article.pk)
    return resultat


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
        self.current_site = get_section_or_404(self.kwargs['site_slug'])
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
            self.current_site = get_section_or_404(self.kwargs['site_slug'])
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
        context['pages'] = Page.objects.filter(site=self.current_site, status='publish')
        if self.current_site.section_type in ('sectoral', 'regional'):
            carousel = [
                ci.article for ci in
                self.current_site.carousel_items.select_related('article').all()
            ]
            candidats = [
                a for a in ArticlePage.objects.live()
                .filter(section_slug=self.current_site.slug)
                .select_related('featured_image')
                .order_by('-publication_date', '-first_published_at')[:20]
                if a.any_image_url
            ]
            carousel = _completer_carrousel(carousel, candidats)
            context['carousel_articles'] = carousel
            context.update(_sectoral_sidebar_context(self.current_site))
        else:
            context.update(_sidebar_context(self.current_site.slug))
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
        context.update(_sidebar_context(section))
        return context


class SiteArticleDetailView(ArticleDetailView):
    """Détail d'un article d'un sous-site"""

    def get_queryset(self):
        self.current_site = get_section_or_404(self.kwargs['site_slug'])
        return (ArticlePage.objects.live()
                .filter(section_slug=self.current_site.slug)
                .select_related('featured_image'))

    def get_object(self, queryset=None):
        self.current_site = get_section_or_404(self.kwargs['site_slug'])
        return get_object_or_404(
            ArticlePage.objects.live().select_related('featured_image'),
            slug=self.kwargs['slug'],
            section_slug=self.current_site.slug,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site = context.get('site') or self.current_site
        if site and site.section_type in ('sectoral', 'regional'):
            context.update(_sectoral_sidebar_context(site))
        return context


class ArticleTractView(View):
    """La version affichable d'une fiche pratique : une page A4, prête à imprimer.

    Demandé par Arnaud le 18/08/2026 : « il faut fabriquer un format d'article
    de fiche pratique que les gens peuvent aussi télécharger en format tract
    pour afficher dans leur boîte ».

    Aucune bibliothèque PDF n'est installée, et en ajouter une ferait entrer
    des dépendances système (cairo, pango) sur le serveur pour un seul usage.
    On sert donc une page calibrée A4, dont le navigateur fait un vrai PDF par
    « Enregistrer au format PDF » — la fonction est native partout, et le
    fichier obtenu est un PDF comme un autre.
    """

    #: Sections retirées du tract. Sur un panneau syndical, personne ne lit
    #: quinze références de jurisprudence : elles font la crédibilité de
    #: l'article en ligne, pas celle de l'affiche. Elles restent sur la page web.
    TITRES_EXCLUS = ('sources', 'sourcesjuridiques', 'references', 'referencesjuridiques',
                     'mentionslegales', 'bibliographie')

    def get(self, request, slug, site_slug=None):
        site = get_section_or_404(site_slug) if site_slug else \
            SectionPage.objects.filter(slug='principal').first()
        section_slug = site.slug if site else 'principal'
        article = get_object_or_404(
            ArticlePage.objects.live().select_related('featured_image'),
            slug=slug, section_slug=section_slug,
        )
        if not article.fiche_pratique:
            # Le tract n'existe que pour les articles marqués comme fiches
            # pratiques : sinon chaque brève aurait une adresse fantôme.
            raise Http404("Cet article n'est pas une fiche pratique.")
        return render(request, 'content/article_tract.html', {
            'article': article,
            'site': site,
            'blocs': self._blocs_du_tract(article),
            'contact_email': self._contact(site),
        })

    @classmethod
    def _blocs_du_tract(cls, article):
        """Le corps de l'article, allégé des sections de références."""
        return [bloc for bloc in article.body if not cls._est_une_section_exclue(bloc)]

    @classmethod
    def _est_une_section_exclue(cls, bloc):
        """Vrai si le bloc s'ouvre sur un titre du genre « Sources »."""
        from bs4 import BeautifulSoup
        if bloc.block_type != 'rich_text':
            return False
        soupe = BeautifulSoup(str(bloc.value), 'html.parser')
        titre = soupe.find(['h2', 'h3', 'h4'])
        if titre is None:
            return False
        cle = ''.join(c for c in _cle_de_nom(titre.get_text()) if c.isalnum())
        return cle in cls.TITRES_EXCLUS

    @staticmethod
    def _contact(site):
        """L'adresse à donner sur le tract : celle du syndicat, sinon la conf.

        Un tract sans contact ne sert à rien : c'est par là qu'on rejoint.
        """
        from django.conf import settings
        return (getattr(site, 'contact_email', '') or '').strip() \
            or getattr(settings, 'DEFAULT_CONTACT_EMAIL', 'contact@cnt-so.org')


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
        current_site = get_section_or_404(site_slug)
        cp = ContentPage.objects.live().filter(
            slug=slug, section_slug=current_site.slug).first()
        if cp:
            return HttpResponsePermanentRedirect(cp.get_absolute_url())
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
                .prefetch_related('cms_categories')
                .annotate(has_img=Case(
                    When(featured_image__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ))
                .order_by('-has_img', '-publication_date', '-first_published_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        section_slug = self.category.section_slug or 'principal'
        context['site'] = SectionPage.objects.filter(slug=section_slug).first()
        context.update(_sidebar_context(section_slug))
        return context


class SiteCategoryDetailView(ListView):
    """Articles d'une catégorie d'un sous-site"""
    model = ArticlePage
    template_name = 'content/category_detail.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        self.current_site = get_section_or_404(kwargs['site_slug'])
        self.category = get_object_or_404(CmsCategory, slug=kwargs['slug'], section_slug=self.current_site.slug)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return (ArticlePage.objects.live()
                .filter(cms_categories=self.category)
                .select_related('featured_image')
                .prefetch_related('cms_categories')
                .annotate(has_img=Case(
                    When(featured_image__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ))
                .order_by('-has_img', '-publication_date', '-first_published_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['site'] = self.current_site
        context.update(_sidebar_context(self.current_site.slug))
        return context


def _page_editoriale(section_slug, slug):
    """Page statique servant de chapô à une vue codée en dur.

    Certaines pages (espace presse…) sont rendues par une vue, pas par l'arbre
    Wagtail : leur texte vivait donc dans le gabarit, hors de portée des
    rédacteurs. On va chercher ici la page statique de même slug pour qu'ils
    puissent en reprendre la main depuis /cms/.
    """
    from cms.models import ContentPage
    return ContentPage.objects.filter(
        slug=slug, section_slug=section_slug
    ).first()


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
        context['intro_page'] = _page_editoriale('principal', 'espace-presse')
        context.update(_sidebar_context('principal'))
        return context


class SiteEspacePresse(ListView):
    """Page Espace Presse d'un sous-site"""
    model = ArticlePage
    template_name = 'content/espace_presse.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.current_site = get_section_or_404(self.kwargs['site_slug'])
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
        context['intro_page'] = _page_editoriale(self.current_site.slug, 'espace-presse')
        context.update(_sidebar_context(self.current_site.slug))
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
        context.update(_sidebar_context('principal'))
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

    nom_complet = ' '.join(filter(None, [message_obj.first_name, message_obj.name]))
    lines = [
        f'Nom : {nom_complet}',
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

    safe_name = nom_complet.replace('\n', ' ').replace('\r', ' ')
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


class ContactFormMixin:
    """Logique partagée pour construire/traiter un formulaire de contact
    (dynamique par section si un FormulaireContact existe, sinon générique)."""

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
                first_name=cd.get('prenom', ''),
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


class _BaseContactView(ContactFormMixin, View):
    """Vue de contact partagée (principal et sous-sites)."""
    template_name = 'content/contact.html'

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
        # Passe par get_section_or_404 : cette vue faisait sa propre résolution,
        # sans filtrer sur `live` — le formulaire de contact restait donc
        # ouvert sur un syndicat dépublié.
        self.site_obj = get_section_or_404(slug)
        if self.site_obj is None:
            raise Http404

    def get(self, request, *args, **kwargs):
        url = reverse_lazy('content:site_contact_success', kwargs={'site_slug': self.site_obj.legacy_site_slug or self.site_obj.slug})
        return super().get(request, self.site_obj, url)

    def post(self, request, *args, **kwargs):
        url = reverse_lazy('content:site_contact_success', kwargs={'site_slug': self.site_obj.legacy_site_slug or self.site_obj.slug})
        return super().post(request, self.site_obj, url)


def site_contact_success(request, site_slug):
    site_obj = get_section_or_404(site_slug)
    if site_obj is None:
        raise Http404
    return render(request, 'content/contact_success.html', {'site': site_obj})


class PlanDuSiteView(TemplateView):
    """Plan du site HTML — site principal ou sous-site"""
    template_name = 'content/plan_du_site.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        site_slug = self.kwargs.get('site_slug', 'principal')
        current = get_section_or_404(site_slug)
        ctx['plan_site'] = current
        ctx['site'] = current

        # Grouper les catégories de même nom (ex: 9x "Actualité & luttes" par secteur)
        from collections import defaultdict
        from os.path import commonprefix

        from django.db.models import Prefetch
        children_qs = CmsCategory.objects.all()
        raw_cats = list(
            CmsCategory.objects.filter(section_slug=current.slug, parent=None)
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

#: Une même adresse IP ne peut pas demander plus de N inscriptions par heure.
#: Le botnet du 24/07 au 17/08/2026 en postait une centaine par jour depuis 25
#: IP : trois par heure et par IP laisse passer un couple qui s'inscrit depuis
#: le même local syndical, et coupe court à l'abus.
NEWSLETTER_MAX_PAR_IP = 3
NEWSLETTER_FENETRE = 3600

#: Le désabonnement, lui, doit rester large : il ne coûte rien à personne, et
#: chaque lecteur empêché de sortir se venge sur le bouton « indésirable ».
#: La limite ne vise qu'un script qui viderait une liste adresse par adresse.
NEWSLETTER_MAX_DESABO_PAR_IP = 20


def _ip_du_visiteur(request):
    """L'IP réelle derrière le reverse proxy nginx."""
    transmis = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if transmis:
        return transmis.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _trop_de_demandes(request):
    """Vrai si cette IP a déjà épuisé son quota d'inscriptions de l'heure."""
    from django.core.cache import caches
    # Cache PARTAGÉ entre les workers gunicorn : dans le cache local du
    # processus, la limite aurait valu trois fois plus (cf. settings.CACHES).
    cache = caches['limites']
    cle = f'newsletter-inscription:{_ip_du_visiteur(request)}'
    essais = cache.get(cle, 0)
    if essais >= NEWSLETTER_MAX_PAR_IP:
        return True
    cache.set(cle, essais + 1, NEWSLETTER_FENETRE)
    return False


def _trop_de_desabonnements(request):
    """Vrai si cette IP a épuisé son quota de désabonnements de l'heure."""
    from django.core.cache import caches
    cache = caches['limites']
    cle = f'newsletter-desabonnement:{_ip_du_visiteur(request)}'
    essais = cache.get(cle, 0)
    if essais >= NEWSLETTER_MAX_DESABO_PAR_IP:
        return True
    cache.set(cle, essais + 1, NEWSLETTER_FENETRE)
    return False


def _site_de_la_newsletter(site):
    """Le syndicat dont la liste recevra cette inscription.

    Seule la confédération diffuse une newsletter : les autres listes OVH sont
    des listes de travail internes, réservées aux adhérent·es et non
    destinées à la diffusion publique (arbitrage d'Arnaud, 17/08/2026).

    La règle suit les données plutôt qu'un nom écrit en dur : un syndicat qui
    a une liste garde ses inscrits, les autres envoient vers la conf. Rendre
    sa liste à un syndicat suffirait donc à lui rendre sa newsletter, sans
    toucher au code. Et surtout, personne n'atterrit plus dans une base que
    nul n'utilise.
    """
    from .ovh_sync import lists_for_site
    if lists_for_site(site):
        return site
    return SectionPage.objects.filter(slug='principal').first() or site


class NewsletterSubscribeView(View):
    """Première étape de l'inscription : recueillir l'adresse.

    Cette vue n'inscrit personne et n'envoie aucun courriel. Elle se contente
    de mener à la page de validation, qui porte le hCaptcha. Avant le
    17/08/2026 elle créait l'abonné et envoyait la confirmation sur simple
    POST, sans la moindre vérification : un botnet en a fait un relais pour
    bombarder des adresses tierces depuis nos serveurs.
    """

    def _get_site(self, site_slug=None):
        if site_slug:
            return get_section_or_404(site_slug, live=True)
        return get_object_or_404(SectionPage, slug='principal')

    def post(self, request, site_slug=None):
        site = self._get_site(site_slug)
        form = NewsletterSubscribeForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Adresse e-mail invalide.')
            return redirect(request.META.get('HTTP_REFERER', '/'))

        return render(request, 'content/newsletter_subscribe_verify.html', {
            'site': _site_de_la_newsletter(site),
            'form': NewsletterCaptchaForm(initial={
                'email': form.cleaned_data['email'],
                'name': form.cleaned_data.get('name', ''),
            }),
        })


class NewsletterSubscribeVerifyView(View):
    """Deuxième étape : le hCaptcha franchi, on inscrit et on envoie le courriel.

    Seule cette vue crée un `Subscriber`. C'est aussi la seule à faire partir
    un courriel vers une adresse que le visiteur a saisie : le captcha et la
    limite par IP protègent donc autant notre base que les boîtes d'autrui.
    """

    def _get_site(self, site_slug=None):
        if site_slug:
            return get_section_or_404(site_slug, live=True)
        return get_object_or_404(SectionPage, slug='principal')

    def post(self, request, site_slug=None):
        site = _site_de_la_newsletter(self._get_site(site_slug))
        form = NewsletterCaptchaForm(request.POST)
        if not form.is_valid():
            return render(request, 'content/newsletter_subscribe_verify.html', {
                'site': site, 'form': form,
            }, status=400)

        if _trop_de_demandes(request):
            return render(request, 'content/newsletter_subscribe_verify.html', {
                'site': site, 'form': form,
                'trop_de_demandes': True,
            }, status=429)

        email = form.cleaned_data['email'].strip().lower()
        subscriber, created = Subscriber.objects.get_or_create(
            site=site, email=email,
            defaults={'name': form.cleaned_data.get('name', '')},
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
                    reply_to=destinataire_de_reponse(),
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
            # (le signal post_save de cms/apps.py répercute l'ajout sur la liste OVH)
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
        # (le signal post_save de cms/apps.py répercute le retrait des listes OVH)
        return render(request, 'content/newsletter_unsubscribe_done.html', {
            'site': subscriber.site,
        })


class NewsletterDesabonnementView(View):
    """Désabonnement sans jeton, à partir de la seule adresse.

    La newsletter part en un message unique vers les listes OVH : il n'y a donc
    pas de jeton par destinataire à glisser dans le lien. Le pied de page
    pointait faute de mieux vers `/newsletter/inscription/`, une vue en POST
    seul — le lien « Se désabonner » renvoyait un 405 (constaté le 17/08/2026).
    Sans porte de sortie, le seul geste qui restait au lecteur était « signaler
    comme indésirable », le pire signal qui soit pour la délivrabilité.

    Le retrait s'opère sur les listes OVH, où vivent les adresses, et sur la
    ligne locale quand elle existe.
    """

    def _site(self, site_slug=None):
        if site_slug:
            return get_section_or_404(site_slug, live=True)
        return get_object_or_404(SectionPage, slug='principal')

    def get(self, request, site_slug=None):
        site = self._site(site_slug)
        return render(request, 'content/newsletter_desabonnement.html', {
            'site': site,
            'form': NewsletterUnsubscribeForm(initial={'email': request.GET.get('email', '')}),
        })

    def post(self, request, site_slug=None):
        site = self._site(site_slug)
        form = NewsletterUnsubscribeForm(request.POST)
        if not form.is_valid():
            return render(request, 'content/newsletter_desabonnement.html', {
                'site': site, 'form': form,
            })

        email = form.cleaned_data['email'].strip().lower()

        # Garde-fou contre un script qui viderait une liste entière. Le quota
        # est large : mieux vaut un désabonnement de trop qu'un lecteur coincé.
        # Et s'il est atteint, on le dit — annoncer un retrait qui n'a pas eu
        # lieu renverrait la personne vers le bouton « indésirable ».
        if _trop_de_desabonnements(request):
            form.add_error(None, (
                "Trop de demandes depuis cette connexion. Réessayez dans une "
                "heure, ou écrivez à contact@cnt-so.org : nous vous retirerons "
                "de la liste à la main."))
            return render(request, 'content/newsletter_desabonnement.html', {
                'site': site, 'form': form,
            })

        from .ovh_sync import ovh_unsubscribe
        ovh_unsubscribe(_site_de_la_newsletter(site), email)
        Subscriber.objects.filter(site=site, email=email).update(is_active=False)

        return render(request, 'content/newsletter_desabonnement_done.html', {
            'site': site, 'email': email,
        })


class SOrganiserView(TemplateView):
    """Page S'organiser avec la CNT-SO"""
    template_name = 'content/s_organiser.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = SectionPage.objects.filter(slug='principal').first()
        return ctx


def _libelle_document(titre):
    """Rend lisible un titre de document qui n'est qu'un nom de fichier.

    « cntso_souscription_flyers.pdf » → « Souscription flyers ». Un titre déjà
    rédigé (avec des espaces) est laissé intact : on ne réécrit que ce qui
    ressemble à un fichier.
    """
    if ' ' in titre.strip():
        return titre
    radical = titre.rsplit('.', 1)[0]
    mots = [m for m in radical.replace('-', '_').split('_') if m and m != 'cntso']
    return ' '.join(mots).capitalize() if mots else titre


class PermanencesJuridiquesView(TemplateView):
    """Page des permanences syndicales et juridiques.

    Le contenu venait d'un bloc HTML écrit à la main : les fiches sont
    désormais des `Permanence` éditables dans /cms/, et le chapô reste le
    corps de la page statique.
    """
    template_name = 'content/permanences_juridiques.html'

    def get_context_data(self, **kwargs):
        from .models import Permanence
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = SectionPage.objects.filter(slug='principal').first()
        ctx['intro_page'] = _page_editoriale('principal', 'permanences-juridiques')
        ctx['permanences'] = (Permanence.objects.filter(is_active=True)
                              .select_related('site')
                              .order_by('order', 'ville'))
        ctx.update(_sidebar_context('principal'))
        return ctx


class SyndicatsView(TemplateView):
    """Page « Nos syndicats et structures ».

    Ses treize cartes tenaient dans un bloc HTML de 9 800 caractères, feuille
    de style comprise : elles sont désormais des `FicheSyndicat` à remplir
    dans /cms/, et le chapô reste le corps de la page statique.
    """
    template_name = 'content/syndicats.html'

    def get_context_data(self, **kwargs):
        from .models import FicheSyndicat
        ctx = super().get_context_data(**kwargs)
        principal = SectionPage.objects.filter(slug='principal').first()
        ctx['site'] = principal
        ctx['intro_page'] = _page_editoriale('principal', 'syndicats')
        ctx['fiches'] = (
            FicheSyndicat.objects.filter(is_active=True, site=principal)
            .select_related('image', 'categorie', 'site_cible')
            .order_by('order', 'titre')
        )
        ctx.update(_sidebar_context('principal'))
        return ctx


class SouscriptionView(TemplateView):
    """Page d'appel à la souscription permanente.

    Elle remplace l'article du même nom, dont l'appel au don tenait dans un
    « cliquez ici » en petits caractères, répété deux fois au fil du texte —
    sur une page dont c'est pourtant la seule raison d'être.
    """
    template_name = 'content/souscription.html'

    # Cagnotte externe. En dur, comme le reste de cette page : SectionPage ne
    # porte pas de champ « don », et en inventer un pour une unique valeur
    # coûterait une migration sans rien rendre de plus modifiable en pratique.
    URL_DON = ('https://www.we-solidaire.com/fr/collecte/'
               'souscription-dappui-aux-luttes-et-a-la-defense-ouvriere')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = SectionPage.objects.filter(slug='principal').first()
        ctx['url_don'] = self.URL_DON

        # L'affiche reste portée par l'article : le jour où un rédacteur la
        # remplace dans /cms/, la page suit. On ne filtre pas sur `live` —
        # l'article est dépublié au profit de cette page, mais il demeure la
        # source de l'image.
        article = ArticlePage.objects.filter(
            slug='souscription', section_slug='principal'
        ).first()
        ctx['affiche'] = article.featured_image if article else None

        from wagtail.documents import get_document_model
        # Les documents importés portent leur nom de fichier
        # (« cntso_souscription_flyers.pdf »), qui fait négligé en bouton de
        # téléchargement. On l'habille sans le remplacer : un titre saisi à la
        # main dans /cms/ ressort tel quel.
        ctx['documents'] = [
            {'url': d.url, 'libelle': _libelle_document(d.title)}
            for d in get_document_model().objects.filter(
                title__icontains='souscription').order_by('title')
        ]

        ctx.update(_sidebar_context('principal'))
        return ctx


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
        ctx.update(_sidebar_context('principal'))
        return ctx


# ── Vues STUCS ────────────────────────────────────────────────────────────────

class SiteRejoindreView(View):
    """Page 'Nous rejoindre' générique pour tout sous-site.

    La page portait jusqu'au 17/08/2026 un second formulaire de contact, copie
    exacte de celui de `/<slug>/contact/` : même formulaire dynamique, même
    captcha, même destinataire. Elle renvoie désormais vers lui, ce qui laisse
    un seul chemin à maintenir et un seul endroit où un champ personnalisé peut
    manquer. La vue redevient donc une simple lecture.
    """

    def get(self, request, site_slug):
        site = get_section_or_404(site_slug)
        ctx = {
            'site': site,
            'categories': CmsCategory.objects.filter(section_slug=site.slug),
            'on_rejoindre_page': True,
        }
        ctx.update(_sectoral_sidebar_context(site))
        return render(request, 'content/site_rejoindre.html', ctx)


class SiteRessourcesView(View):
    """Page 'Ressources' générique pour tout sous-site."""

    def get(self, request, site_slug):
        site = get_section_or_404(site_slug)
        # Uniquement les catégories contenant au moins un article publié
        # (l'import WordPress a laissé beaucoup de catégories vides ou en doublon)
        categories = CmsCategory.objects.filter(
            section_slug=site.slug,
            articles__live=True,
            articles__section_slug=site.slug,
        ).distinct().order_by('name')
        slug = request.GET.get('cat', '')
        active_cat = CmsCategory.objects.filter(section_slug=site.slug, slug=slug).first() if slug else None
        qs = ArticlePage.objects.live().filter(section_slug=site.slug)
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
