"""
ViewSet utilisateurs de l'admin Wagtail, branché via CustomUsersAppConfig
(content/apps.py) : injecte les formulaires avec le champ « Syndicat ».
"""
from wagtail.users.views.users import UserViewSet as WagtailUserViewSet

from .admin_forms import SyndicatUserCreationForm, SyndicatUserEditForm


class UserViewSet(WagtailUserViewSet):
    def get_form_class(self, for_update=False):
        if for_update:
            return SyndicatUserEditForm
        return SyndicatUserCreationForm
