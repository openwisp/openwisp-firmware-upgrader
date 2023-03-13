'use strict';

django.jQuery(function ($) {
    django._loadUi(
        $('textarea[name="upgrade_options"]').get(0),
        false,
        firmwareUpgraderSchema,
        true
    );
});
