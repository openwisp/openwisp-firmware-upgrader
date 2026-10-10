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
    document.body.removeAttribute("data-admin-utc-offset");
    const form = scheduleRow.closest("form");
    const browserTz = labelScheduleTimezone(scheduleRow);
    const tzInput = $('<input type="hidden" name="scheduled_at_tz">');
    tzInput.val(browserTz);
    form.append(tzInput);
  }
});

function labelScheduleTimezone(container) {
  let browserTz = "";
  try {
    browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (error) {
    browserTz = "";
  }
  const serverTz = container.data("server-tz") || "";
  let text = interpolate(gettext("Entered in your timezone (%s)."), [browserTz]);
  if (serverTz) {
    text += " " + interpolate(gettext("The server runs in %s."), [serverTz]);
  }
  container.find(".ow-schedule-tz-note").text(text);
  return browserTz;
}
