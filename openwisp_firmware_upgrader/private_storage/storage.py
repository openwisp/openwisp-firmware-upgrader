from urllib.parse import urljoin

from private_storage.storage.files import PrivateFileSystemStorage

from ..settings import FIRMWARE_API_BASEURL, IMAGE_URL_PATH

file_system_private_storage = PrivateFileSystemStorage(
    base_url=urljoin(FIRMWARE_API_BASEURL, IMAGE_URL_PATH)
)
