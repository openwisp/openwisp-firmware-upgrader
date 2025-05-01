from django.contrib.auth import get_permission_codename
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import HttpResponse
from private_storage.views import PrivateStorageDetailView

from ..swapper import load_model


class FirmwareImageDownloadView(PermissionRequiredMixin, PrivateStorageDetailView):
    model = load_model('FirmwareImage')
    model_file_field = 'file'
    raise_exception = True

    slug_field = "file"
    slug_url_kwarg = "path"

    def get_permission_required(self):
        """
        Return the list of permissions that the user should have.
        """
        return [
            f'{self.model._meta.app_label}.{get_permission_codename("view", self.model._meta)}'
        ]

    def can_access_file(self, private_file):
        user = private_file.request.user
        # Get object first since it's needed for permission checks
        self.object = self.get_object()

        # Superusers can always access
        if user.is_superuser:
            return True

        # For non-superusers, check both organization access and view permission
        perm = self.get_permission_required()[0]
        is_org_manager = user.is_staff and user.is_manager(
            self.object.build.category.organization
        )
        has_view_perm = user.has_perm(perm, self.object)

        return is_org_manager and has_view_perm

    def handle_no_permission(self):
        """
        Return empty response for unauthorized API requests
        """
        if 'api' in self.request.path:
            return HttpResponse(status=403)
        return super().handle_no_permission()


firmware_image_download = FirmwareImageDownloadView.as_view()
