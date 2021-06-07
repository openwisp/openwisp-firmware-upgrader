from django.core.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, pagination, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from openwisp_firmware_upgrader import private_storage
from openwisp_users.api.authentication import BearerAuthentication
from openwisp_users.api.mixins import FilterByOrganizationManaged
from openwisp_users.api.permissions import DjangoModelPermissions, IsOrganizationManager

from ..swapper import load_model
from .serializers import (
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    FirmwareImageSerializer,
)

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
FirmwareImage = load_model('FirmwareImage')


class ListViewPagination(pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProtectedAPIMixin(FilterByOrganizationManaged):
    authentication_classes = (
        BearerAuthentication,
        SessionAuthentication,
    )
    permission_classes = (
        IsOrganizationManager,
        DjangoModelPermissions,
    )
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
