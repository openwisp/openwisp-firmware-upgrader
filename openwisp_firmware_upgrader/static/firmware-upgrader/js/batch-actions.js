"use strict";

django.jQuery(function ($) {
  function extractErrorMessage(xhr) {
    const body = xhr.responseJSON;
    if (body) {
      if (body.error) {
        return body.error;
      }
      // DRF serializer field errors are keyed by field name (e.g. an invalid
      // group/location pk or an unparseable datetime); surface the first one.
      for (const key of Object.keys(body)) {
        const value = body[key];
        if (Array.isArray(value) && value.length) {
          return value[0];
        }
        if (typeof value === "string" && value) {
          return value;
        }
      }
    }
    return gettext("The request could not be completed.");
  }

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
        alert(extractErrorMessage(xhr));
      },
    });
  }

  function showBatchCancelModal() {
    if ($("#ow-batch-cancel-modal").length === 0) {
      createBatchCancelModal();
    }
    $("#ow-batch-cancel-modal").removeClass("ow-hide");
    $("#ow-batch-cancel-modal .ow-batch-cancel-confirm").trigger("focus");
  }

  function createBatchCancelModal() {
    const modalHtml = `
      <div id="ow-batch-cancel-modal" class="ow-overlay ow-overlay-notification ow-overlay-inner ow-hide">
        <div class="ow-dialog-notification ow-cancel-confirmation-dialog">
          <span class="ow-dialog-close ow-dialog-close-x">&times;</span>
          <div class="ow-cancel-confirmation-header">
            <h2 class="ow-cancel-confirmation-title">${gettext("Cancel mass upgrade")}</h2>
          </div>
          <div class="ow-cancel-confirmation-content">
            <p>${gettext("Are you sure you want to cancel this mass upgrade?")}</p>
          </div>
          <div class="ow-dialog-buttons ow-cancel-confirmation-buttons">
            <button class="ow-batch-cancel-confirm button default danger-btn">
              ${gettext("Yes")}
            </button>
            <button class="ow-dialog-close button default">
              ${gettext("No")}
            </button>
          </div>
        </div>
      </div>
    `;
    $("body").append(modalHtml);
    $("#ow-batch-cancel-modal .ow-dialog-close").on("click", function () {
      $("#ow-batch-cancel-modal").addClass("ow-hide");
    });
    $("#ow-batch-cancel-modal .ow-batch-cancel-confirm").on("click", function () {
      $("#ow-batch-cancel-modal").addClass("ow-hide");
      post(owBatchCancelUrl, {});
    });
    $(document).on("keyup", function (e) {
      if (e.keyCode === 27 && $("#ow-batch-cancel-modal").is(":visible")) {
        $("#ow-batch-cancel-modal").addClass("ow-hide");
      }
    });
    $("#ow-batch-cancel-modal").on("click", function (e) {
      if (e.target === this) {
        $(this).addClass("ow-hide");
      }
    });
  }

  $("#batch-cancel-btn").on("click", function () {
    showBatchCancelModal();
  });

  const form = $("#batch-reschedule-form");
  if (!form.length) {
    return;
  }

  const toggle = $("#batch-reschedule-btn");
  const dateInput = form.find('input[name="scheduled_at_0"]');
  const timeInput = form.find('input[name="scheduled_at_1"]');

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  // Interpret the schedule in the browser timezone: show the stored UTC value
  // as local time and relabel the picker note.
  const scheduledUtc = form.data("scheduled-utc");
  if (scheduledUtc) {
    const local = new Date(scheduledUtc);
    if (!isNaN(local.getTime())) {
      dateInput.val(
        local.getFullYear() +
          "-" +
          pad(local.getMonth() + 1) +
          "-" +
          pad(local.getDate()),
      );
      timeInput.val(pad(local.getHours()) + ":" + pad(local.getMinutes()));
    }
  }
  let browserTz = "";
  try {
    browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (error) {
    browserTz = "";
  }
  const serverTz = form.data("server-tz") || "";
  let tzText = interpolate(gettext("Entered in your timezone (%s)."), [browserTz]);
  if (serverTz) {
    tzText += " " + interpolate(gettext("The server runs in %s."), [serverTz]);
  }
  form.find(".ow-schedule-tz-note").text(tzText);

  toggle.on("click", function () {
    const opening = form.hasClass("ow-hide");
    form.toggleClass("ow-hide", !opening);
    toggle.attr("aria-expanded", String(opening));
    if (opening) {
      dateInput.trigger("focus");
    }
  });

  $("#batch-reschedule-cancel").on("click", function () {
    form.addClass("ow-hide");
    toggle.attr("aria-expanded", "false").trigger("focus");
  });

  $("#batch-reschedule-save").on("click", function () {
    const scheduled = new Date(dateInput.val() + "T" + timeInput.val());
    post(owBatchRescheduleUrl, {
      scheduled_at: isNaN(scheduled.getTime()) ? null : scheduled.toISOString(),
      group: $("#batch-reschedule-group").val() || null,
      location: $("#batch-reschedule-location").val() || null,
      is_persistent: $("#batch-reschedule-persistent").is(":checked"),
      upgrade_all: $("#batch-reschedule-firmwareless").is(":checked"),
    });
  });
});
