from django.contrib.auth import get_permission_codename
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import HttpResponse
from private_storage.views import PrivateStorageDetailView

from ..swapper import load_model


class FirmwareImageDownloadView(PermissionRequiredMixin, PrivateStorageDetailView):
    model = load_model("FirmwareImage")
    model_file_field = "file"
    raise_exception = True

    slug_field = "file"
    slug_url_kwarg = "path"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponse(status=401)
        return super().dispatch(request, *args, **kwargs)

    def get_permission_required(self):
        """
        Return the list of permissions that the user should have.
        """
        return [
            f'{self.model._meta.app_label}.{get_permission_codename("view", self.model._meta)}'
        ]

    def can_access_file(self, private_file):
        user = private_file.request.user
        return user.is_superuser or (
            user.is_staff and user.is_manager(self.object.build.category.organization)
        )


firmware_image_download = FirmwareImageDownloadView.as_view()
