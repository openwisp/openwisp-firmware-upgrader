from django.contrib.auth import get_permission_codename
from private_storage.views import PrivateStorageDetailView

from ..swapper import load_model


class FirmwareImageDownloadView(PrivateStorageDetailView):
    model = load_model("FirmwareImage")
    model_file_field = "file"

    slug_field = "file"
    slug_url_kwarg = "path"

    def can_access_file(self, private_file):
        user = private_file.request.user
        
        # Check if user is superuser or manager of the organization
        is_authorized = user.is_superuser or (
            user.is_staff and user.is_manager(self.object.build.category.organization)
        )
        
        # If user is not authorized by role, deny access
        if not is_authorized:
            return False
        
        # For authorized users, check view permission
        # Only if they're not superusers (superusers have all permissions)
        if not user.is_superuser:
            perm_codename = get_permission_codename('view', self.model._meta)
            view_perm = f'{self.model._meta.app_label}.{perm_codename}'
            has_view_perm = user.has_perm(view_perm, self.object)
            if not has_view_perm:
                return False
        
        return True


firmware_image_download = FirmwareImageDownloadView.as_view()
