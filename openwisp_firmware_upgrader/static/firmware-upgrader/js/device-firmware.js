'use strict';

django.jQuery(function ($) {
    if(firmwareUpgraderSchema === null) {
        return;
    }
    var firmwareImageChanged = false;
    // Do not render JSONSchema form if the image field is not changed.
    // The "change" event is also emitted when the form is rendered.
    // The "firmwareImageChanged" variable is used as flag to prevent this
    // behavior.
    $('#devicefirmware-group').on('change', '#id_devicefirmware-0-image', function () {
        if (firmwareImageChanged) {
            django._loadJsonSchemaUi(
                $('#id_devicefirmware-0-upgrade_options').get(0),
                false,
                firmwareUpgraderSchema,
                true
            );
        } else {
            firmwareImageChanged = true;
        }
    });
    $('#devicefirmware-group .add-row a').click(function() {
        firmwareImageChanged = true;
    });
});
