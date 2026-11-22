"use strict";

django.jQuery(function ($) {
  const browserTimezone = getBrowserTimezone();
  let actionPending = false;

  /** Prefer server validation messages; network failures may have no JSON body. */
  function extractErrorMessage(xhr) {
    const body = xhr.responseJSON;
    if (body) {
      if (body.error) {
        return body.error;
      }
      // Field errors are keyed by field name; show the first actionable message.
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

  /** Reload after a successful mutation so actions reflect the latest batch state. */
  function submitBatchAction(url, data) {
    // Cancellation and rescheduling mutate the same batch. Do not allow either
    // action to race with a request that is already in flight.
    if (actionPending) {
      return;
    }
    actionPending = true;
    const buttons = $(
      "#batch-cancel-btn, #batch-reschedule-save, .ow-batch-cancel-confirm",
    );
    buttons.prop("disabled", true);
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
        actionPending = false;
        buttons.prop("disabled", false);
        $("#ow-loading").hide();
        alert(extractErrorMessage(xhr));
      },
    });
  }

  /** Keep keyboard focus inside the confirmation dialog and return it on dismissal. */
  function initializeCancelDialog() {
    const modal = $("#ow-batch-cancel-modal");
    if (!modal.length) {
      return;
    }
    const confirmButton = modal.find(".ow-batch-cancel-confirm");
    let lastFocused = null;

    function hideModal() {
      modal.addClass("ow-hide");
      if (lastFocused) {
        $(lastFocused).trigger("focus");
        lastFocused = null;
      }
    }

    $("#batch-cancel-btn").on("click", function () {
      lastFocused = document.activeElement;
      modal.removeClass("ow-hide");
      confirmButton.trigger("focus");
    });

    modal.find(".ow-dialog-close").on("click", hideModal);
    confirmButton.on("click", function () {
      hideModal();
      submitBatchAction(owBatchCancelUrl, {});
    });
    modal.on("click", function (event) {
      if (event.target === this) {
        hideModal();
      }
    });
    modal.on("keydown", function (event) {
      // Escape dismisses the dialog without confirming the cancellation.
      if (event.key === "Escape") {
        event.preventDefault();
        hideModal();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      // Tab must stay inside the open dialog, not reach the page behind it.
      const focusable = modal
        .find(
          "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
        )
        .filter(":visible:not(:disabled)");
      if (!focusable.length) {
        return;
      }
      const first = focusable.first()[0];
      const last = focusable.last()[0];
      // Wrap backward from the first control and forward from the last one.
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  function initializeScheduledTimeDisplay() {
    const scheduledAt = $(".ow-scheduled-at");
    // Without a browser timezone, keep the server-rendered value and its label.
    if (!scheduledAt.length || !browserTimezone) {
      return;
    }
    const scheduledDate = new Date(scheduledAt.data("scheduled-utc"));
    if (isNaN(scheduledDate.getTime())) {
      return;
    }
    const text = scheduledDate.toLocaleString(window.djangoLocale || undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    scheduledAt.text(text + " (" + browserTimezone + ")");
  }

  /** Initialize editable values once; Discard restores this saved-page snapshot. */
  function initializeReschedulePanel() {
    const panel = $("#batch-reschedule-form");
    if (!panel.length) {
      return;
    }
    const toggle = $("#batch-reschedule-btn");
    const dateInput = panel.find('input[name="scheduled_at_0"]');
    const timeInput = panel.find('input[name="scheduled_at_1"]');
    labelScheduleTimezone(panel, browserTimezone);

    const scheduledDate = new Date(panel.data("scheduled-utc"));
    if (browserTimezone && !isNaN(scheduledDate.getTime())) {
      // Use the same localized format as Django's calendar widget and parser.
      // The input is a wall-clock time; scheduled_at_tz tells the server its zone.
      dateInput.val(scheduledDate.strftime(get_format("DATE_INPUT_FORMATS")[0]));
      timeInput.val(scheduledDate.strftime("%H:%M"));
    }
    // This panel is a div, not a form. Snapshot its controls without resetting
    // Django's surrounding admin form or relying on server-time default values.
    const initialValues = panel
      .find("input, select")
      .get()
      .map(function (element) {
        return { element: element, value: $(element).val(), checked: element.checked };
      });

    function setPanelOpen(opening) {
      panel.toggleClass("ow-hide", !opening);
      toggle.attr("aria-expanded", String(opening));
      (opening ? dateInput : toggle).trigger("focus");
    }

    toggle.on("click", function () {
      setPanelOpen(panel.hasClass("ow-hide"));
    });
    panel.find("#batch-reschedule-cancel").on("click", function () {
      initialValues.forEach(function (initial) {
        const input = $(initial.element);
        if (initial.element.type === "checkbox") {
          input.prop("checked", initial.checked);
        } else {
          input.val(initial.value);
        }
        // Select2 maintains its own display, so restoring the select is not enough.
        if (initial.element.tagName === "SELECT") {
          input.trigger("change");
        }
      });
      setPanelOpen(false);
    });
    panel.find("#batch-reschedule-save").on("click", function () {
      submitBatchAction(owBatchRescheduleUrl, {
        scheduled_at_0: dateInput.val() || null,
        scheduled_at_1: timeInput.val() || null,
        scheduled_at_tz: browserTimezone,
        group: panel.find("#batch-reschedule-group").val() || null,
        location: panel.find("#batch-reschedule-location").val() || null,
        is_persistent: panel.find("#batch-reschedule-persistent").is(":checked"),
        // The action endpoint calls the firmwareless option "upgrade_all".
        upgrade_all: panel.find("#batch-reschedule-firmwareless").is(":checked"),
      });
    });
  }

  initializeCancelDialog();
  initializeScheduledTimeDisplay();
  initializeReschedulePanel();
});
