from django.utils.translation import gettext_lazy as _

from openwisp_users.multitenancy import (
    MultitenantOrgFilter,
    MultitenantRelatedOrgFilter,
)

from .swapper import load_model

Build = load_model('Build')
Category = load_model('Category')


class CategoryFilter(MultitenantRelatedOrgFilter):
    field_name = 'category'
    parameter_name = 'category_id'
    title = _('category')


class CategoryOrganizationFilter(MultitenantOrgFilter):
    parameter_name = 'category__organization'
    rel_model = Category


class BuildCategoryFilter(MultitenantRelatedOrgFilter):
    field_name = 'category'
    parameter_name = 'build__category'
    title = _('category')
    rel_model = Build


class BuildCategoryOrganizationFilter(MultitenantOrgFilter):
    parameter_name = 'build__category__organization'
    rel_model = Category
