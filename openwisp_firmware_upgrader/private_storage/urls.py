from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^(?P<path>.*)$', views.firmware_image_download, name='serve_private_file'),
]
