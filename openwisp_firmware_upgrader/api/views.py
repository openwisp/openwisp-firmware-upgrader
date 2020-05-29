from wsgiref.util import FileWrapper

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.response import Response

from openwisp_users.api.authentication import BearerAuthentication

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


class ProtectedAPIMixin(object):
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [DjangoModelPermissions]
    throttle_scope = 'firmware_upgrader'


class OrgAPIMixin(ProtectedAPIMixin):
    def get_queryset(self):
        queryset = self.queryset.all()
        if not self.request.user.is_superuser:
            user_orgs = self.request.user.openwisp_users_organization.all()
            filter_key = f'{self.organization_field}__in'
            organization_filter = {filter_key: user_orgs}
            queryset = queryset.filter(**organization_filter)
        org = self.request.query_params.get('org', None)
        try:
            if org:
                organization_filter = {self.organization_field + '__name': org}
                queryset = queryset.filter(**organization_filter)
        except ValidationError:
            # when uuid is not valid
            queryset = []
        return queryset


class BuildListView(OrgAPIMixin, generics.ListCreateAPIView):
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    organization_field = 'category__organization'
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    filterset_fields = ['category']
    ordering_fields = ['version', 'created', 'modified']
    ordering = ['-created', '-version']


class BuildDetailView(OrgAPIMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    lookup_fields = ['pk']
    organization_field = 'category__organization'


class BuildMassUpgradeView(OrgAPIMixin, generics.GenericAPIView):
    model = Build
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    lookup_fields = ['pk']
    organization_field = 'category__organization'

    def post(self, request, pk):
        upgrade_all = request.POST.get('upgrade_all')
        instance = self.get_object()
        batch = instance.batch_upgrade(firmwareless=upgrade_all)
        return Response({"batch": str(batch.pk)}, status=201)


class CategoryListView(OrgAPIMixin, generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    organization_field = 'organization'
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['name', 'created', 'modified']
    ordering = ['-name', '-created']


class CategoryDetailView(OrgAPIMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_fields = ['pk']
    organization_field = 'organization'


class BatchUpgradeOperationListView(OrgAPIMixin, generics.ListAPIView):
    queryset = BatchUpgradeOperation.objects.all().select_related(
        'build', 'build__category'
    )
    serializer_class = BatchUpgradeOperationListSerializer
    organization_field = 'build__category__organization'
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    filterset_fields = ['build', 'status']
    ordering_fields = ['created', 'modified']
    ordering = ['-created']


class BatchUpgradeOperationDetailView(OrgAPIMixin, generics.RetrieveAPIView):
    queryset = (
        BatchUpgradeOperation.objects.all()
        .select_related('build', 'build__category')
        .prefetch_related('upgradeoperation_set')
    )
    serializer_class = BatchUpgradeOperationSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'


class FirmwareImageMixin(OrgAPIMixin):
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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        file_handle = instance.file.path
        document = open(file_handle, 'rb')
        response = HttpResponse(
            FileWrapper(document), content_type='application/octet-stream'
        )
        response['Content-Disposition'] = (
            'attachment; filename="%s"' % instance.file.name
        )
        return response


build_list = BuildListView.as_view()
build_detail = BuildDetailView.as_view()
build_mass_upgrade = BuildMassUpgradeView.as_view()
category_list = CategoryListView.as_view()
category_detail = CategoryDetailView.as_view()
batch_upgrade_operation_list = BatchUpgradeOperationListView.as_view()
batch_upgrade_operation_detail = BatchUpgradeOperationDetailView.as_view()
firmware_image_list = FirmwareImageListView.as_view()
firmware_image_detail = FirmwareImageDetailView.as_view()
firmware_image_download = FirmwareImageDownloadView.as_view()
