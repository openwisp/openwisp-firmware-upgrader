'use strict';

django.jQuery(function ($) {
    function initSelect2() {
        $('select[id^="id_firmwareimage_set"][id$="type"]')
        .not('select[name*="__prefix__"]')
        .select2();
    }
    $('.add-row > a').click(initSelect2);
    initSelect2();
});
