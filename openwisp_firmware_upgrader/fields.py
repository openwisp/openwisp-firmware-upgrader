import datetime

from django import forms
from django.core.exceptions import ValidationError


class NaiveSplitDateTimeField(forms.SplitDateTimeField):
    """Combine date/time inputs without assigning the server's timezone."""

    def compress(self, data_list):
        if data_list:
            if data_list[0] in self.empty_values:
                raise ValidationError(
                    self.error_messages["invalid_date"], code="invalid_date"
                )
            if data_list[1] in self.empty_values:
                raise ValidationError(
                    self.error_messages["invalid_time"], code="invalid_time"
                )
            return datetime.datetime.combine(*data_list)
        return None
