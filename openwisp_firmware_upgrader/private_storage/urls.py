from urllib.parse import urljoin

from django.urls import path

from ..settings import IMAGE_URL_PATH
from . import views

urlpatterns = [
    path(
        # Use "path" URL kwarg to make it consistent with
        # django-private-storage. Otherwise, the S3 reverse
        # proxy feature of django-private-storage does
        # not work.
        urljoin(IMAGE_URL_PATH, '<path:path>'),
        views.firmware_image_download,
        name='serve_private_file',
    ),
]
