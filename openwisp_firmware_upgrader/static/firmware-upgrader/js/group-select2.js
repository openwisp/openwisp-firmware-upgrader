(function ($) {
  "use strict";

  $(document).ready(function () {
    $(".select2-input").each(function () {
      var $element = $(this);
      var placeholder = $element.data("placeholder") || "Select an option";
      var fieldType = placeholder.toLowerCase().includes("group")
        ? "group"
        : placeholder.toLowerCase().includes("location")
          ? "location"
          : "item";

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
            return "No " + fieldType + "s found";
          },
        },
      });
    });

    $(".select2-input").next(".select2").find(".select2-selection").css({
      width: "222px",
      "min-width": "222px",
    });
  });
})(django.jQuery);
