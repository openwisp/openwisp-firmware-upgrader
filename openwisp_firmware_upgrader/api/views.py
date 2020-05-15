from wsgiref.util import FileWrapper

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from rest_framework import filters, generics
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import DjangoModelPermissions
from swapper import load_model

from openwisp_users.api.authentication import BearerAuthentication

from .serializers import (
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    FirmwareImageSerializer,
)

BatchUpgradeOperation = load_model('firmware_upgrader', 'BatchUpgradeOperation')
Build = load_model('firmware_upgrader', 'Build')
Category = load_model('firmware_upgrader', 'Category')
FirmwareImage = load_model('firmware_upgrader', 'FirmwareImage')


class ProtectedAPIMixin(object):
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [DjangoModelPermissions]


class OrgAPIMixin(ProtectedAPIMixin):
    def get_queryset(self):
        queryset = self.queryset.all().order_by('-pk')
        if not self.request.user.is_superuser:
            user_org = self.request.user.openwisp_users_organization.get()
            organization_filter = {self.organization_field: user_org}
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
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['version', 'created', 'modified']
    ordering = ['-created', '-version']


class BuildDetailView(OrgAPIMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Build.objects.all().select_related('category')
    serializer_class = BuildSerializer
    lookup_fields = ['pk']
    organization_field = 'category__organization'


class CategoryListView(OrgAPIMixin, generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    organization_field = 'organization'
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['name', 'created', 'modified']
    ordering = ['name', '-created']


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
    filter_backends = [filters.OrderingFilter]
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


class FirmwareImageListView(OrgAPIMixin, generics.ListCreateAPIView):
    serializer_class = FirmwareImageSerializer
    organization_field = 'build__category__organization'
    ordering_fields = ['type', 'created', 'modified']
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['type', 'created', 'modified']
    ordering = ['-created']

    def get_queryset(self):
        build_pk = self.request.parser_context['kwargs']['pk']
        self.queryset = FirmwareImage.objects.filter(build=build_pk)
        queryset = super().get_queryset()
        return queryset

    def create(self, request, *args, **kwargs):
        request.data['build'] = kwargs['pk']
        return super().create(request, *args, **kwargs)


class FirmwareImageDetailView(OrgAPIMixin, generics.RetrieveDestroyAPIView):
    queryset = FirmwareImage.objects.all()
    serializer_class = FirmwareImageSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'

    def get_queryset(self):
        build_pk = self.request.parser_context['kwargs']['build_pk']
        self.queryset = FirmwareImage.objects.filter(build=build_pk)
        queryset = super().get_queryset()
        return queryset


class FirmwareImageDownloadView(OrgAPIMixin, generics.RetrieveAPIView):
    serializer_class = FirmwareImageSerializer
    lookup_fields = ['pk']
    organization_field = 'build__category__organization'

    def get_queryset(self):
        build_pk = self.request.parser_context['kwargs']['build_pk']
        self.queryset = FirmwareImage.objects.filter(build=build_pk)
        queryset = super().get_queryset()
        return queryset

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
category_list = CategoryListView.as_view()
category_detail = CategoryDetailView.as_view()
batch_upgrade_operation_list = BatchUpgradeOperationListView.as_view()
batch_upgrade_operation_detail = BatchUpgradeOperationDetailView.as_view()
firmware_image_list = FirmwareImageListView.as_view()
firmware_image_detail = FirmwareImageDetailView.as_view()
firmware_image_download = FirmwareImageDownloadView.as_view()
