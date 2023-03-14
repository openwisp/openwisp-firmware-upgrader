'use strict';

django.jQuery(function ($) {
    django._loadJsonSchemaUi(
        $('textarea[name="upgrade_options"]').get(0),
        false,
        firmwareUpgraderSchema,
        true
    );
});
