"""
ViewSet utilisateurs de l'admin Wagtail, branché via CustomUsersAppConfig
(content/apps.py) : injecte les formulaires avec le champ « Syndicat » et
borne ce que peut faire un gestionnaire de comptes non-superuser
(redacteur_en_chef) — pas d'édition des comptes superuser, pas d'accès à la
case « Administrateur ».
"""
from django.core.exceptions import PermissionDenied
from wagtail.users.views.users import (
    CreateView as WagtailUserCreateView,
    EditView as WagtailUserEditView,
    UserViewSet as WagtailUserViewSet,
)

from .admin_forms import SyndicatUserCreationForm, SyndicatUserEditForm


class UserCreateView(WagtailUserCreateView):
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        return kwargs


class UserEditView(WagtailUserEditView):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        # Un non-superuser ne touche pas aux comptes superuser : il pourrait
        # sinon en changer le mot de passe (escalade de privilèges).
        if self.object.is_superuser and not request.user.is_superuser:
            raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        return kwargs


class UserViewSet(WagtailUserViewSet):
    add_view_class = UserCreateView
    edit_view_class = UserEditView

    def get_form_class(self, for_update=False):
        if for_update:
            return SyndicatUserEditForm
        return SyndicatUserCreationForm
