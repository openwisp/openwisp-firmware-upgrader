"use strict";

django.jQuery(function ($) {
  const input = $('input[name="scheduled_at"]');
  if (!input.length) {
    return;
  }
  const row = $("#schedule-row");
  const minDelay = parseInt(row.data("min-delay"), 10);
  const maxHorizon = parseInt(row.data("max-horizon"), 10);
  const feedback = $("#schedule-feedback");
  const submits = $('input[name="upgrade_all"], input[name="upgrade_related"]');
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  $("#schedule-timezone").text(interpolate(gettext("Your timezone: %s"), [timezone]));

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function toUtcString(date) {
    return (
      date.getUTCFullYear() +
      "-" +
      pad(date.getUTCMonth() + 1) +
      "-" +
      pad(date.getUTCDate()) +
      "T" +
      pad(date.getUTCHours()) +
      ":" +
      pad(date.getUTCMinutes()) +
      ":" +
      pad(date.getUTCSeconds()) +
      "+00:00"
    );
  }

  function validate() {
    feedback.text("").addClass("ow-hide");
    submits.prop("disabled", false);
    if (!input.val()) {
      return true;
    }
    const seconds = (new Date(input.val()).getTime() - Date.now()) / 1000;
    let message = "";
    if (seconds < minDelay) {
      const minutes = Math.floor(minDelay / 60);
      message = interpolate(
        ngettext(
          "The scheduled time must be at least %s minute in the future.",
          "The scheduled time must be at least %s minutes in the future.",
          minutes,
        ),
        [minutes],
      );
    } else if (seconds > maxHorizon) {
      message = interpolate(
        gettext("The scheduled time cannot be more than %s days in the future."),
        [Math.floor(maxHorizon / 86400)],
      );
    }
    if (message) {
      feedback.text(message).removeClass("ow-hide");
      submits.prop("disabled", true);
      return false;
    }
    return true;
  }

  input.on("input change", validate);

  input.closest("form").on("submit", function (event) {
    if (!input.val()) {
      return;
    }
    if (!validate()) {
      event.preventDefault();
      return;
    }
    const utc = toUtcString(new Date(input.val()));
    input.removeAttr("name");
    $("<input>", { type: "hidden", name: "scheduled_at", value: utc }).appendTo(
      input.closest("form"),
    );
  });
});
