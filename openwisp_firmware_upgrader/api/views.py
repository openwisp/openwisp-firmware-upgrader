import swapper
from django.core.exceptions import ValidationError
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, pagination, serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import clone_request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict

from openwisp_firmware_upgrader import private_storage
from openwisp_users.api.mixins import FilterByOrganizationManaged
from openwisp_users.api.mixins import ProtectedAPIMixin as BaseProtectedAPIMixin

from ..hardware import REVERSE_FIRMWARE_IMAGE_MAP
from ..swapper import load_model
from .filters import DeviceUpgradeOperationFilter, UpgradeOperationFilter
from .serializers import (
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    DeviceFirmwareSerializer,
    DeviceUpgradeOperationSerializer,
    FirmwareImageSerializer,
    UpgradeOperationSerializer,
)

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
UpgradeOperation = load_model('UpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
FirmwareImage = load_model('FirmwareImage')
DeviceFirmware = load_model('DeviceFirmware')
Device = swapper.load_model('config', 'Device')


class ListViewPagination(pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProtectedAPIMixin(BaseProtectedAPIMixin, FilterByOrganizationManaged):
    throttle_scope = 'firmware_upgrader'
    pagination_class = ListViewPagination

    def get_queryset(self):
        qs = super().get_queryset()
        org_filtered = self.request.query_params.get('organization', None)
        try:
            if org_filtered:
                organization_filter = {self.organization_field + '__slug': org_filtered}
                qs = qs.filter(**organization_filter)
        except ValidationError:
            # when uuid is not valid
            qs = []
        return qs


class BuildListView(ProtectedAPIMixin, generics.ListCreateAPIView):
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    organization_field = 'category__organization'
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    filterset_fields = ['category', 'version', 'os']
    ordering_fields = ['version', 'created', 'modified']
    ordering = ['-created', '-version']


class BuildDetailView(ProtectedAPIMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    lookup_fields = ['pk']
    organization_field = 'category__organization'


class BuildBatchUpgradeView(ProtectedAPIMixin, generics.GenericAPIView):
    model = Build
    queryset = Build.objects.all().select_related('category')
    serializer_class = serializers.Serializer
    lookup_fields = ['pk']
    organization_field = 'category__organization'

    def post(self, request, pk):
        """
        Upgrades all the devices related to the specified build ID.
        """
        upgrade_all = request.POST.get('upgrade_all') is not None
        instance = self.get_object()
        batch = instance.batch_upgrade(firmwareless=upgrade_all)
        return Response({"batch": str(batch.pk)}, status=201)

    def get(self, request, pk):
        """
        Returns a list of objects (DeviceFirmware and Device)
        which would be upgraded if POST is used.
        """
        self.instance = self.get_object()
        data = BatchUpgradeOperation.dry_run(build=self.instance)
        data['device_firmwares'] = [
            str(device_fw.pk) for device_fw in data['device_firmwares']
        ]
        data['devices'] = [str(device.pk) for device in data['devices']]
        return Response(data)


class CategoryListView(ProtectedAPIMixin, generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    organization_field = 'organization'
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['name', 'created', 'modified']
    ordering = ['-name', '-created']


class CategoryDetailView(ProtectedAPIMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_fields = ['pk']
    organization_field = 'organization'


class BatchUpgradeOperationListView(ProtectedAPIMixin, generics.ListAPIView):
    queryset = BatchUpgradeOperation.objects.all().select_related(
        'build', 'build__category'
    )
    serializer_class = BatchUpgradeOperationListSerializer
    organization_field = 'build__category__organization'
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    filterset_fields = ['build', 'status']
    ordering_fields = ['created', 'modified']
    ordering = ['-created']


class BatchUpgradeOperationDetailView(ProtectedAPIMixin, generics.RetrieveAPIView):
    queryset = (
        BatchUpgradeOperation.objects.all()
        .select_related('build', 'build__category')
        .prefetch_related('upgradeoperation_set')
    )
    serializer_class = BatchUpgradeOperationSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'


class FirmwareImageMixin(ProtectedAPIMixin):
    queryset = FirmwareImage.objects.all()
    parent = None

    def get_parent_queryset(self):
        return Build.objects.filter(pk=self.kwargs['build_pk'])

    def assert_parent_exists(self):
        try:
            assert self.get_parent_queryset().exists()
        except (AssertionError, ValidationError):
            raise NotFound(detail='build not found')

    def get_queryset(self):
        return super().get_queryset().filter(build=self.kwargs['build_pk'])

    def initial(self, *args, **kwargs):
        self.assert_parent_exists()
        super().initial(*args, **kwargs)


class FirmwareImageListView(FirmwareImageMixin, generics.ListCreateAPIView):
    serializer_class = FirmwareImageSerializer
    organization_field = 'build__category__organization'
    ordering_fields = ['type', 'created', 'modified']
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    filterset_fields = ['type']
    ordering_fields = ['type', 'created', 'modified']
    ordering = ['-created']


class FirmwareImageDetailView(FirmwareImageMixin, generics.RetrieveDestroyAPIView):
    queryset = FirmwareImage.objects.all()
    serializer_class = FirmwareImageSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'


class FirmwareImageDownloadView(FirmwareImageMixin, generics.RetrieveAPIView):
    serializer_class = FirmwareImageSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'
    queryset = FirmwareImage.objects.none()

    def retrieve(self, request, *args, **kwargs):
        return private_storage.views.firmware_image_download(
            request, build_pk=kwargs['build_pk'], pk=kwargs['pk']
        )


class DeviceUpgradeOperationMixin(ProtectedAPIMixin):
    queryset = UpgradeOperation.objects.all()
    parent = None

    def get_parent_queryset(self):
        return Device.objects.filter(pk=self.kwargs['pk'])

    def assert_parent_exists(self):
        try:
            assert self.get_parent_queryset().exists()
        except (AssertionError, ValidationError):
            raise NotFound(detail='device not found')

    def get_queryset(self):
        return super().get_queryset().filter(device=self.kwargs['pk'])

    def initial(self, *args, **kwargs):
        self.assert_parent_exists()
        super().initial(*args, **kwargs)


class UpgradeOperationListView(ProtectedAPIMixin, generics.ListAPIView):
    queryset = UpgradeOperation.objects.select_related('device', 'image')
    serializer_class = UpgradeOperationSerializer
    organization_field = 'device__organization'
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    ordering_fields = ['device_id', 'created', 'modified']
    ordering = ['-created']
    filterset_class = UpgradeOperationFilter


class UpgradeOperationDetailView(ProtectedAPIMixin, generics.RetrieveAPIView):
    queryset = UpgradeOperation.objects.select_related('device', 'image').order_by(
        '-created'
    )
    serializer_class = UpgradeOperationSerializer
    lookup_fields = ['pk']
    organization_field = 'device__organization'


class DeviceUpgradeOperationListView(DeviceUpgradeOperationMixin, generics.ListAPIView):
    queryset = UpgradeOperation.objects.select_related('device', 'image').order_by(
        '-created'
    )
    serializer_class = DeviceUpgradeOperationSerializer
    organization_field = 'device__organization'
    filter_backends = [DjangoFilterBackend]
    filterset_class = DeviceUpgradeOperationFilter

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(device__pk=self.kwargs['pk'])


class DeviceFirmwareDetailView(
    ProtectedAPIMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = DeviceFirmwareSerializer
    queryset = DeviceFirmware.objects.select_related('device', 'image')
    lookup_field = 'device'
    lookup_url_kwarg = 'pk'
    organization_field = 'device__organization'

    def get_object(self):
        obj = super().get_object()
        if self.request.method not in ('GET', 'HEAD') and obj.device.is_deactivated():
            raise PermissionDenied
        return obj

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({'device_id': self.kwargs['pk']})
        return context

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        if kwargs.get('instance'):
            image_qs = self._get_image_queryset(
                kwargs.get('instance'), kwargs.get('instance').device
            )
            serializer.fields['image'].queryset = image_qs
        else:
            device = self._get_device_object(serializer.context.get('device_id'))
            image_qs = self._get_image_queryset(device=device)
            serializer.fields['image'].queryset = image_qs
        return serializer

    def _get_device_object(self, device_id):
        try:
            device = Device.objects.get(id=device_id)
            return device
        except Device.DoesNotExist:
            return None

    def _get_image_queryset(self, device_firmware=None, device=None):
        if not device_firmware and not device:
            return
        image_qs = (
            FirmwareImage.objects.filter(
                build__category__organization_id=device.organization_id
            )
            .order_by('-created')
            .select_related('build', 'build__category')
        )
        if device.model and device.model in REVERSE_FIRMWARE_IMAGE_MAP:
            image_qs = image_qs.filter(type=REVERSE_FIRMWARE_IMAGE_MAP[device.model])
        if device_firmware:
            image_qs = image_qs.filter(
                build__category_id=device_firmware.image.build.category_id
            )
        return image_qs

    def _get_response_data(self, serializer, upgrade_operation=None):
        data = {**serializer.data}
        if upgrade_operation:
            data.update({'upgrade_operation': {'id': upgrade_operation.id}})
        return ReturnDict(data, serializer=serializer)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object_or_none()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        if instance is None:
            self.perform_create(serializer)
            instance = self.get_object_or_none()
            uo = instance.device.upgradeoperation_set.latest('created')
            data = self._get_response_data(serializer, uo)
            image_qs = self._get_image_queryset(uo, instance.device)
            serializer.fields['image'].queryset = image_qs
            return Response(data, status=status.HTTP_201_CREATED)

        self.perform_update(serializer)
        uo = instance.device.upgradeoperation_set.latest('created')
        data = self._get_response_data(serializer, uo)
        image_qs = self._get_image_queryset(uo, instance.device)
        serializer.fields['image'].queryset = image_qs
        return Response(data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def get_object_or_none(self):
        try:
            return self.get_object()
        except Http404:
            if self.request.method == 'PUT':
                # For PUT-as-create operation, we need to ensure that we have
                # relevant permissions, as if this was a POST request. This
                # will either raise a PermissionDenied exception, or simply
                # return None.
                self.check_permissions(clone_request(self.request, 'POST'))
            else:
                # PATCH requests where the object does not exist should still
                # return a 404 response.
                raise


build_list = BuildListView.as_view()
build_detail = BuildDetailView.as_view()
api_batch_upgrade = BuildBatchUpgradeView.as_view()
category_list = CategoryListView.as_view()
category_detail = CategoryDetailView.as_view()
batch_upgrade_operation_list = BatchUpgradeOperationListView.as_view()
batch_upgrade_operation_detail = BatchUpgradeOperationDetailView.as_view()
firmware_image_list = FirmwareImageListView.as_view()
firmware_image_detail = FirmwareImageDetailView.as_view()
firmware_image_download = FirmwareImageDownloadView.as_view()
upgrade_operation_list = UpgradeOperationListView.as_view()
upgrade_operation_detail = UpgradeOperationDetailView.as_view()
device_upgrade_operation_list = DeviceUpgradeOperationListView.as_view()
device_firmware_detail = DeviceFirmwareDetailView.as_view()
