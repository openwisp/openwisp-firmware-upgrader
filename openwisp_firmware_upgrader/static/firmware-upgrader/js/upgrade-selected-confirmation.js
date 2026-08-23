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

  // Interpret the scheduled time in the browser timezone instead of the
  // server's: post a single UTC scheduled_at and relabel the picker note.
  const scheduleRow = $("#schedule-row");
  if (scheduleRow.length) {
    const form = scheduleRow.closest("form");
    const utcInput = $('<input type="hidden" name="scheduled_at">');
    form.append(utcInput);
    const dateInput = scheduleRow.find('input[name="scheduled_at_0"]');
    const timeInput = scheduleRow.find('input[name="scheduled_at_1"]');
    form.on("submit", function () {
      const scheduled = new Date(dateInput.val() + "T" + timeInput.val());
      utcInput.val(isNaN(scheduled.getTime()) ? "" : scheduled.toISOString());
    });
    labelScheduleTimezone(scheduleRow);
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
}
