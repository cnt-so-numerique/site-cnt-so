"""
Provisionnement d'un syndicat : tout ce qu'il faut pour qu'une SectionPage
fraîchement créée soit gérable en autonomie — groupe redacteur_<slug>,
permissions d'arbre (add/change/publish sur son sous-arbre), permissions
modèle (copiées du groupe socle « redacteur »), collection de médias et
lecture de la collection « Commun ».

Appelé à la création d'une SectionPage (signal post_save, cf. cms/apps.py)
et par setup_cms_permissions pour la passe globale. Idempotent.
"""

# Permissions accordées au groupe du syndicat sur SA collection ; sur
# « Commun », seulement les deux choose_* (lecture pour le chooser).
COLLECTION_PERMS = [
    ('wagtailimages', 'add_image'), ('wagtailimages', 'change_image'),
    ('wagtailimages', 'choose_image'),
    ('wagtaildocs', 'add_document'), ('wagtaildocs', 'change_document'),
    ('wagtaildocs', 'choose_document'),
]
CHOOSE_PERMS = [
    ('wagtailimages', 'choose_image'), ('wagtaildocs', 'choose_document'),
]


def get_perms(pairs):
    """Résout des couples (app_label, codename) en Permission, en ignorant
    silencieusement celles qui n'existent pas encore (migrations partielles)."""
    from django.contrib.auth.models import Permission
    perms = []
    for app_label, codename in pairs:
        try:
            perms.append(Permission.objects.get(
                codename=codename, content_type__app_label=app_label))
        except Permission.DoesNotExist:
            pass
    return perms


def grant_collection_perms(group, collection, pairs):
    from wagtail.models import GroupCollectionPermission
    for perm in get_perms(pairs):
        GroupCollectionPermission.objects.get_or_create(
            group=group, collection=collection, permission=perm)


def root_child_collection(name):
    """Retourne (ou crée) la collection enfant de Root portant ce nom.
    Root est rechargé à chaque appel : add_child invalide les champs d'arbre."""
    from wagtail.models import Collection
    root = Collection.get_first_root_node()
    existing = root.get_children().filter(name=name).first()
    return existing or root.add_child(name=name)


def commun_collection():
    return root_child_collection('Commun')


def section_collection(group, section):
    """Collection de médias du syndicat : réutilise celle déjà liée au groupe
    (robuste à un renommage du syndicat), sinon la crée du nom de la section."""
    from wagtail.models import Collection
    root = Collection.get_first_root_node()
    linked = Collection.objects.filter(
        group_permissions__group=group,
    ).exclude(pk__in=[root.pk, commun_collection().pk]).first()
    return linked or root_child_collection(section.title)


def provision_section(section):
    """Crée/complète le groupe et les permissions d'un syndicat. Retourne le
    groupe, ou None si la section n'a pas encore de slug."""
    from django.contrib.auth.models import Group
    from wagtail.models import GroupPagePermission

    slug = section.legacy_site_slug or section.slug
    if not slug:
        return None

    group, _ = Group.objects.get_or_create(name=f'redacteur_{slug}')

    # Permissions d'arbre : add/change/publish sur le sous-arbre du syndicat
    for perm in get_perms([('wagtailcore', 'add_page'),
                           ('wagtailcore', 'change_page'),
                           ('wagtailcore', 'publish_page')]):
        GroupPagePermission.objects.get_or_create(
            group=group, page=section, permission=perm)

    # Permissions modèle : mêmes que le groupe socle « redacteur »
    # (synchronisé par create_editorial_groups à chaque migrate)
    socle = Group.objects.filter(name='redacteur').first()
    if socle is not None:
        group.permissions.add(*socle.permissions.all())
    else:
        group.permissions.add(*get_perms([('wagtailadmin', 'access_admin')]))

    # Médias : collection du syndicat + lecture de « Commun »
    collection = section_collection(group, section)
    grant_collection_perms(group, collection, COLLECTION_PERMS)
    grant_collection_perms(group, commun_collection(), CHOOSE_PERMS)
    return group
