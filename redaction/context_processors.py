from content.models import Site


def redac_context(request):
    is_chef = False
    user_site = None
    current_site = None

    if request.user.is_authenticated:
        is_chef = request.user.is_superuser or request.user.groups.filter(
            name='redacteur_en_chef'
        ).exists()
        try:
            user_site = request.user.author_profile.site
        except Exception:
            pass

        if is_chef:
            site_id = request.session.get('redac_current_site_id')
            if site_id:
                try:
                    current_site = Site.objects.get(pk=site_id)
                except Site.DoesNotExist:
                    request.session.pop('redac_current_site_id', None)
        else:
            current_site = user_site

    all_sites = []
    if is_chef and request.user.is_authenticated:
        all_sites = list(Site.objects.filter(is_active=True).order_by('name'))

    return {
        'is_chef': is_chef,
        'user_site': user_site,
        'current_site': current_site,
        'all_sites': all_sites,
    }
