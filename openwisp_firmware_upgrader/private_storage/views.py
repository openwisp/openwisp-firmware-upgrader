from private_storage.views import PrivateStorageDetailView

from ..swapper import load_model


class FirmwareImageDownloadView(PrivateStorageDetailView):
    model = load_model('FirmwareImage')
    model_file_field = 'file'

    slug_field = 'file'
    slug_url_kwarg = 'path'

    def can_access_file(self, private_file):
        user = private_file.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        org = self.object.build.category.organization
        return user.is_staff and user.is_member(org)


firmware_image_download = FirmwareImageDownloadView.as_view()
