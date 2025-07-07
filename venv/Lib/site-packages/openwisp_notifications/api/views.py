from django.contrib.contenttypes.models import ContentType
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import (
    GenericAPIView,
    RetrieveDestroyAPIView,
    RetrieveUpdateAPIView,
    get_object_or_404,
)
from rest_framework.mixins import CreateModelMixin, ListModelMixin, UpdateModelMixin
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from openwisp_notifications.api.serializers import (
    IgnoreObjectNotificationSerializer,
    NotificationListSerializer,
    NotificationSerializer,
    NotificationSettingSerializer,
)
from openwisp_notifications.swapper import load_model
from openwisp_users.api.authentication import BearerAuthentication

from .filters import NotificationSettingFilter

UNAUTHORIZED_STATUS_CODES = (
    status.HTTP_401_UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN,
)

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
IgnoreObjectNotification = load_model('IgnoreObjectNotification')


class NotificationPaginator(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class BaseNotificationView(GenericAPIView):
    model = Notification
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.all()
    # NOTE: Required for Browsable API view. Don't remove.
    serializer_class = serializers.Serializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset.none()  # pragma: no cover
        return self.queryset.filter(recipient=self.request.user)


class NotificationListView(BaseNotificationView, ListModelMixin):
    serializer_class = NotificationListSerializer
    pagination_class = NotificationPaginator
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['unread']

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class NotificationDetailView(BaseNotificationView, RetrieveDestroyAPIView):
    serializer_class = NotificationSerializer
    lookup_field = 'pk'

    def patch(self, request, *args, **kwargs):
        return self._mark_notification_read()

    def _mark_notification_read(self):
        notification = self.get_object()
        notification.mark_as_read()
        return Response(
            status=status.HTTP_200_OK,
        )


class NotificationReadRedirect(BaseNotificationView):
    lookup_field = 'pk'

    def get(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.mark_as_read()
        return HttpResponseRedirect(notification.target_url)

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if response.status_code not in UNAUTHORIZED_STATUS_CODES:
            return response

        redirect_url = '{admin_login}?next={path}'.format(
            admin_login=reverse('admin:login'), path=self.request.path
        )
        return HttpResponseRedirect(redirect_url)


class NotificationReadAllView(BaseNotificationView):
    def post(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        queryset.filter(unread=True).update(unread=False)
        # update() does not create post_save signal, therefore
        # manual invalidation of cache is required
        Notification.invalidate_unread_cache(request.user)
        return Response(status=status.HTTP_200_OK)


class BaseNotificationSettingView(GenericAPIView):
    model = NotificationSetting
    serializer_class = NotificationSettingSerializer
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return NotificationSetting.objects.none()  # pragma: no cover
        return NotificationSetting.objects.filter(user=self.request.user)


class NotificationSettingListView(BaseNotificationSettingView, ListModelMixin):
    pagination_class = NotificationPaginator
    filter_backends = [DjangoFilterBackend]
    filterset_class = NotificationSettingFilter

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class NotificationSettingView(BaseNotificationSettingView, RetrieveUpdateAPIView):
    lookup_field = 'pk'


class BaseIgnoreObjectNotificationView(GenericAPIView):
    model = IgnoreObjectNotification
    serializer_class = IgnoreObjectNotificationSerializer
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return IgnoreObjectNotification.objects.filter(user=self.request.user)


class IgnoreObjectNotificationListView(
    BaseIgnoreObjectNotificationView, ListModelMixin
):
    pagination_class = NotificationPaginator

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class IgnoreObjectNotificationView(
    BaseIgnoreObjectNotificationView,
    RetrieveDestroyAPIView,
    CreateModelMixin,
    UpdateModelMixin,
):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, *kwargs)
        self.kwargs['obj_content_type_id'] = self.obj_content_type_id

    def put(self, request, *args, **kwargs):
        return self.create_or_update(request, *args, **kwargs)

    @property
    def obj_content_type_id(self):
        return ContentType.objects.get_by_natural_key(
            self.kwargs['app_label'], self.kwargs['model_name']
        ).pk

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        filter_kwargs = {
            'object_content_type_id': self.kwargs['obj_content_type_id'],
            'object_id': self.kwargs['object_id'],
        }
        obj = get_object_or_404(queryset, **filter_kwargs)
        # May raise a permission denied
        self.check_object_permissions(self.request, obj)
        return obj

    def create_or_update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except Http404:
            return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(
            user=self.request.user,
            object_content_type_id=self.kwargs['obj_content_type_id'],
            object_id=self.kwargs['object_id'],
        )


notifications_list = NotificationListView.as_view()
notification_detail = NotificationDetailView.as_view()
notifications_read_all = NotificationReadAllView.as_view()
notification_read_redirect = NotificationReadRedirect.as_view()
notification_setting_list = NotificationSettingListView.as_view()
notification_setting = NotificationSettingView.as_view()
ignore_object_notification_list = IgnoreObjectNotificationListView.as_view()
ignore_object_notification = IgnoreObjectNotificationView.as_view()
