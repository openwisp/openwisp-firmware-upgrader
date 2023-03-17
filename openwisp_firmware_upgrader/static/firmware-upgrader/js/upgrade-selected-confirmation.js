'use strict';

django.jQuery(function ($) {
    if(firmwareUpgraderSchema === null) {
        $('.form-row').hide();
        return;
    }
    django._loadJsonSchemaUi(
        $('textarea[name="upgrade_options"]').get(0),
        false,
        firmwareUpgraderSchema,
        true
    );
});
