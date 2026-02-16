"use strict";

django.jQuery(function ($) {
  $(".select2-input").each(function () {
    var $element = $(this);
    var placeholder = $element.data("placeholder") || gettext("Select an option");

    $element.select2({
      theme: "default",
      dropdownCssClass:
        $element.data("dropdown-css-class") || "ow2-autocomplete-dropdown",
      placeholder: placeholder,
      allowClear: $element.data("allow-clear") === "true",
      width: "resolve",
      minimumInputLength: 0,
      language: {
        noResults: function () {
          return gettext("No results found.");
        },
      },
    });
  });
});
