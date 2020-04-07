from private_storage.views import PrivateStorageDetailView
from swapper import load_model


class FirmwareImageDownloadView(PrivateStorageDetailView):
    model = load_model('firmware_upgrader', 'FirmwareImage')
    model_file_field = 'file'

    slug_field = 'file'
    slug_url_kwarg = 'path'

    def can_access_file(self, private_file):
        user = private_file.request.user
        if not user.is_authenticated:
            return False
        org = self.object.build.category.organization
        user_organizations = user.openwisp_users_organization.all()
        return user.is_superuser or (user.is_staff and org in user_organizations)


firmware_image_download = FirmwareImageDownloadView.as_view()
