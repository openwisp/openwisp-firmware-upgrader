"use strict";

django.jQuery(function ($) {
  const upgradeOptions = $('textarea[name="upgrade_options"]');
  if (firmwareUpgraderSchema === null || !upgradeOptions.length) {
    $(".form-row").not("#persistence-row, #schedule-row").hide();
  } else {
    django._loadJsonSchemaUi(
      $('textarea[name="upgrade_options"]').get(0),
      false,
      firmwareUpgraderSchema,
      true,
    );
  }
  $("#ow-loading").hide();

  const scheduleRow = $("#schedule-row");
  if (scheduleRow.length) {
    // Date/time inputs carry no offset. Send the browser's zone separately so
    // the server interprets the maintenance window as the user's wall clock.
    const form = scheduleRow.closest("form");
    const browserTz = getBrowserTimezone();
    labelScheduleTimezone(scheduleRow, browserTz);
    const tzInput = $('<input type="hidden" name="scheduled_at_tz">');
    tzInput.val(browserTz);
    form.append(tzInput);
  }
});
