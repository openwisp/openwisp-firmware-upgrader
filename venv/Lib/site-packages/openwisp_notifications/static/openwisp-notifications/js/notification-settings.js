'use strict';
(function ($) {
    $(document).ready(function () {
        let emailCheckboxSelector = '.dynamic-notificationsetting_set .field-email > input[type="checkbox"]',
            webCheckboxSelector = '.dynamic-notificationsetting_set .field-web > input[type="checkbox"]';
        // If email notification is checked, web should also be checked.
        $(document).on('change', emailCheckboxSelector, function(){
            let emailCheckBoxId = $(this).attr('id'),
            webCheckboxId = emailCheckBoxId.replace('-email', '-web');
            if($(this).prop('checked') == true){
                $(`#${webCheckboxId}`).prop('checked', $(this).prop('checked'));
            }
        });
        // If web notification is unchecked, email should also be unchecked.
        $(document).on('change', webCheckboxSelector, function(){
            let webCheckboxId = $(this).attr('id'),
            emailCheckBoxId = webCheckboxId.replace('-web', '-email');
            if($(this).prop('checked') == false){
                $(`#${emailCheckBoxId}`).prop('checked', $(this).prop('checked'));
            }
        });
    });
})(django.jQuery);
