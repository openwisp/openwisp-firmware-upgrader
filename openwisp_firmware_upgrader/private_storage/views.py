from private_storage.views import PrivateStorageDetailView

from ..swapper import load_model


class FirmwareImageDownloadView(PrivateStorageDetailView):
    model = load_model('FirmwareImage')
    model_file_field = 'file'

    slug_field = 'file'
    slug_url_kwarg = 'path'

    def can_access_file(self, private_file):
        user = private_file.request.user
        return user.is_superuser or (
            user.is_staff and user.is_manager(self.object.build.category.organization)
        )


firmware_image_download = FirmwareImageDownloadView.as_view()
