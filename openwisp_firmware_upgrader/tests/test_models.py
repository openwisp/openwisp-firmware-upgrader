# from django.core.exceptions import ValidationError
from django.test import TestCase

from openwisp_users.tests.utils import TestOrganizationMixin

from ..models import Build, Category


class TestModels(TestOrganizationMixin, TestCase):
    def _create_category(self, **kwargs):
        opts = dict(name='Test Category')
        opts.update(kwargs)
        if 'organization' not in opts:
            opts['organization'] = self._create_org()
        c = Category(**opts)
        c.full_clean()
        c.save()
        return c

    def test_category_str(self):
        c = Category(name='WiFi Hotspot')
        self.assertEqual(str(c), c.name)

    def test_build_str(self):
        c = self._create_category()
        b = Build(category=c, version='0.1')
        self.assertIn(c.name, str(b))
        self.assertIn(b.version, str(b))

    def test_build_str_no_category(self):
        b = Build()
        self.assertIsNotNone(str(b))
