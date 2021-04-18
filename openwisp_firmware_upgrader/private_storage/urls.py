from urllib.parse import urljoin

from django.urls import path

from ..settings import IMAGE_URL_PATH
from . import views

urlpatterns = [
    path(
        urljoin(IMAGE_URL_PATH, '<path:imagefile>'),
        views.firmware_image_download,
        name='serve_private_file',
    ),
]
