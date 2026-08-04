"use strict";

django.jQuery(function ($) {
  function post(url, data) {
    $("#ow-loading").show();
    $.ajax({
      url: url,
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify(data),
      headers: { "X-CSRFToken": $('input[name="csrfmiddlewaretoken"]').val() },
      success: function () {
        window.location.reload();
      },
      error: function (xhr) {
        $("#ow-loading").hide();
        const detail =
          xhr.responseJSON && xhr.responseJSON.error
            ? xhr.responseJSON.error
            : gettext("The request could not be completed.");
        alert(detail);
      },
    });
  }

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

  function toLocalInputValue(date) {
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate()) +
      "T" +
      pad(date.getHours()) +
      ":" +
      pad(date.getMinutes())
    );
  }

  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  $("#batch-cancel-btn").on("click", function () {
    if (window.confirm(gettext("Cancel this mass upgrade?"))) {
      post(owBatchCancelUrl, {});
    }
  });

  const form = $("#batch-reschedule-form");
  if (!form.length) {
    return;
  }

  const toggle = $("#batch-reschedule-btn");
  const input = $("#batch-reschedule-input");
  const save = $("#batch-reschedule-save");
  const feedback = $("#batch-reschedule-feedback");
  const minDelay = parseInt(form.data("min-delay"), 10);
  const maxHorizon = parseInt(form.data("max-horizon"), 10);

  $("#batch-reschedule-timezone").text(
    interpolate(gettext("Your timezone: %s"), [timezone]),
  );

  const scheduledAt = form.data("scheduled-at");
  if (scheduledAt) {
    const current = new Date(scheduledAt);
    if (!isNaN(current.getTime())) {
      input.val(toLocalInputValue(current));
    }
  }
  if (!isNaN(minDelay)) {
    input.attr("min", toLocalInputValue(new Date(Date.now() + minDelay * 1000)));
  }
  if (!isNaN(maxHorizon)) {
    input.attr("max", toLocalInputValue(new Date(Date.now() + maxHorizon * 1000)));
  }

  function showFeedback(message) {
    feedback.text(message).removeClass("ow-hide");
  }

  function clearFeedback() {
    feedback.text("").addClass("ow-hide");
  }

  function validate() {
    clearFeedback();
    save.prop("disabled", false);
    const value = input.val();
    if (!value) {
      showFeedback(gettext("Select a scheduled time."));
      save.prop("disabled", true);
      return false;
    }
    const seconds = (new Date(value).getTime() - Date.now()) / 1000;
    let message = "";
    if (!isNaN(minDelay) && seconds < minDelay) {
      const minutes = Math.floor(minDelay / 60);
      message = interpolate(
        ngettext(
          "The scheduled time must be at least %s minute in the future.",
          "The scheduled time must be at least %s minutes in the future.",
          minutes,
        ),
        [minutes],
      );
    } else if (!isNaN(maxHorizon) && seconds > maxHorizon) {
      message = interpolate(
        gettext("The scheduled time cannot be more than %s days in the future."),
        [Math.floor(maxHorizon / 86400)],
      );
    }
    if (message) {
      showFeedback(message);
      save.prop("disabled", true);
      return false;
    }
    return true;
  }

  input.on("input change", validate);

  toggle.on("click", function () {
    const opening = form.hasClass("ow-hide");
    form.toggleClass("ow-hide", !opening);
    toggle.attr("aria-expanded", String(opening));
    if (opening) {
      validate();
    }
  });

  $("#batch-reschedule-cancel").on("click", function () {
    form.addClass("ow-hide");
    toggle.attr("aria-expanded", "false").trigger("focus");
  });

  save.on("click", function () {
    if (!validate()) {
      input.trigger("focus");
      return;
    }
    post(owBatchRescheduleUrl, {
      scheduled_at: toUtcString(new Date(input.val())),
      group: $("#batch-reschedule-group").val() || null,
      location: $("#batch-reschedule-location").val() || null,
      is_persistent: $("#batch-reschedule-persistent").is(":checked"),
      upgrade_all: $("#batch-reschedule-firmwareless").is(":checked"),
    });
  });
});
