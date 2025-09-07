(function ($) {
  "use strict";

  $(document).ready(function () {
    $(".select2-input").select2({
      theme: "default",
      dropdownCssClass: "ow2-autocomplete-dropdown",
      placeholder: "Select a group",
      allowClear: true,
      width: "resolve", // Let it calculate the width
      minimumInputLength: 0,
      language: {
        noResults: function () {
          return "No groups found";
        },
      },
    });

    $(".select2-input").next('.select2').find('.select2-selection').css({
      'width': '222px',
      'min-width': '222px'
    });
    
  });
})(django.jQuery);
