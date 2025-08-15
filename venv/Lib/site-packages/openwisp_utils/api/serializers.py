from django.core.exceptions import ImproperlyConfigured

try:
    from rest_framework import serializers
except ImportError:  # pragma: nocover
    raise ImproperlyConfigured(
        'Django REST Framework is required to use '
        'this feature but it is not installed'
    )


class ValidatedModelSerializer(serializers.ModelSerializer):
    def validate(self, data):
        instance = self.instance or self.Meta.model(**data)
        instance.full_clean()
        return data
