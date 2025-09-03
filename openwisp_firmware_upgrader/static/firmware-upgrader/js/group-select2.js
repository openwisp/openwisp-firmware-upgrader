(function ($) {
  "use strict";

  $(document).ready(function () {
    $(".select2-input").select2({
      theme: "default",
      dropdownCssClass: "ow2-autocomplete-dropdown",
      placeholder: "Select a group",
      allowClear: true,
      width: "40px !important",
      minimumInputLength: 0,
      language: {
        noResults: function () {
          return "No groups found";
        },
      },
    });
  });
})(django.jQuery);
