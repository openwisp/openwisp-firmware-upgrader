"use strict";

django.jQuery(function ($) {
  const upgradeOptions = $('textarea[name="upgrade_options"]');
  if (firmwareUpgraderSchema === null || !upgradeOptions.length) {
    $(".form-row").hide();
  } else {
    django._loadJsonSchemaUi(
      $('textarea[name="upgrade_options"]').get(0),
      false,
      firmwareUpgraderSchema,
      true,
    );
  }
  $("#ow-loading").hide();
});
