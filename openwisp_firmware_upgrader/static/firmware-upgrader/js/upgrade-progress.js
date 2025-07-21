"use strict";

django.jQuery(function ($) {
  const firmwareDeviceId = getObjectIdFromUrl();

  setTimeout(function () {
    if (!firmwareDeviceId) {
      return;
    }

    let upgradeSection = $("#upgradeoperation_set-group");

    // Initialize existing upgrade operations with progress bars
    initializeExistingUpgradeOperations($);

    // Determine the host to use for WebSocket connection
    let wsHost = null;
    if (
      typeof owControllerApiHost !== "undefined" &&
      owControllerApiHost.host
    ) {
      wsHost = owControllerApiHost.host;
    } else {
      wsHost = window.location.host;
    }

    if (wsHost && firmwareDeviceId) {
      const wsUrl = `${getWebSocketProtocol()}${wsHost}/ws/firmware-upgrader/device/${firmwareDeviceId}/`;

      const upgradeProgressWebSocket = new ReconnectingWebSocket(wsUrl, null, {
        automaticOpen: false,
        timeoutInterval: 7000,
        maxRetries: 5,
        retryInterval: 3000,
      });

      // Initialize websocket connection
      initUpgradeProgressWebSockets($, upgradeProgressWebSocket);
    }
  }, 100);
});

let upgradeOperationsInitialized = false;

// Store accumulated log content to preserve across WebSocket reconnections
let accumulatedLogContent = new Map();

function formatLogForDisplay(logContent) {
  return logContent ? logContent.replace(/\n/g, "<br>") : "";
}

function requestCurrentOperationState(websocket) {
  // Request current state of any in-progress operations to get full log content
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      const requestMessage = {
        type: "request_current_state",
        device_id: getObjectIdFromUrl(),
      };
      websocket.send(JSON.stringify(requestMessage));
    } catch (error) {
      console.error("Error requesting current state:", error);
    }
  }
}

function initializeExistingUpgradeOperations($, isRetry = false) {
  if (upgradeOperationsInitialized && isRetry) {
    return;
  }

  let statusFields = $("#upgradeoperation_set-group .field-status .readonly");

  let processedCount = 0;
  statusFields.each(function (index) {
    let statusField = $(this);
    let statusText = statusField.text().trim();

    if (statusField.find(".upgrade-status-container").length > 0) {
      return;
    }

    if (
      statusText &&
      (statusText.includes("progress") ||
        statusText === "success" ||
        statusText === "failed" ||
        statusText === "aborted")
    ) {
      let operationFieldset = statusField.closest("fieldset");
      let logElement = operationFieldset.find(".field-log .readonly");

      // Get operation ID for restoring accumulated content
      let operationIdInput = operationFieldset.find("input[name*='id'][value]");
      let operationId =
        operationIdInput.length > 0 ? operationIdInput.val() : "unknown";

      // Use accumulated log content if available
      let logContent;
      if (accumulatedLogContent.has(operationId)) {
        logContent = accumulatedLogContent.get(operationId);

        if (logElement.length > 0) {
          logElement.html(formatLogForDisplay(logContent));
        }
      } else {
        logContent = logElement.length > 0 ? logElement.text().trim() : "";

        // Store this initial content for future use
        if (logContent && operationId !== "unknown") {
          accumulatedLogContent.set(operationId, logContent);
        }
      }

      // Create operation object for updateStatusWithProgressBar
      let operation = {
        status: statusText,
        log: logContent,
        id: operationId,
        progress: null,
      };

      updateStatusWithProgressBar(statusField, operation);
      processedCount++;
    }
  });

  // Mark as initialized if found and processed some operations, or if this is already a retry
  if (processedCount > 0 || isRetry) {
    upgradeOperationsInitialized = true;
  } else if (!isRetry) {
    setTimeout(function () {
      initializeExistingUpgradeOperations($, true);
    }, 1000);
  }
}

function initUpgradeProgressWebSockets($, upgradeProgressWebSocket) {
  upgradeProgressWebSocket.addEventListener("open", function (e) {
    upgradeOperationsInitialized = false;

    setTimeout(function () {
      requestCurrentOperationState(upgradeProgressWebSocket);

      setTimeout(function () {
        initializeExistingUpgradeOperations($, false);
      }, 100);
    }, 50);
  });

  upgradeProgressWebSocket.addEventListener("close", function (e) {
    upgradeOperationsInitialized = false;

    if (e.code === 1006) {
      console.error("WebSocket closed");
    }
  });

  upgradeProgressWebSocket.addEventListener("error", function (e) {
    console.error("WebSocket error occurred", e);
  });

  upgradeProgressWebSocket.addEventListener("message", function (e) {
    try {
      let data = JSON.parse(e.data);

      if (data.model !== "UpgradeOperation") {
        return;
      }

      data = data.data;

      if (data.type === "operation_update") {
        updateUpgradeOperationDisplay(data.operation);
      } else if (data.type === "log") {
        updateUpgradeOperationLog(data);
      } else if (data.type === "status") {
        updateUpgradeOperationStatus(data);
      }
    } catch (error) {
      console.error("Error parsing WebSocket message:", error);
    }
  });
  upgradeProgressWebSocket.open();
}

function updateUpgradeOperationDisplay(operation) {
  let $ = django.jQuery;
  let operationIdInputField = $(`input[value="${operation.id}"]`);
  if (operationIdInputField.length === 0) {
    if (isUpgradeOperationsAbsent()) {
      location.reload();
    }
    return;
  }

  let operationFieldset = operationIdInputField.parent().children("fieldset");
  let statusField = operationFieldset.find(".field-status .readonly");

  if (operation.log && operation.id) {
    accumulatedLogContent.set(operation.id, operation.log);
  }

  // Update status with progress bar
  updateStatusWithProgressBar(statusField, operation);

  let logElement = operationFieldset.find(".field-log .readonly");
  let shouldScroll = isScrolledToBottom(logElement);

  logElement.html(formatLogForDisplay(operation.log));
  if (
    operation.status === "success" ||
    operation.status === "failed" ||
    operation.status === "aborted"
  ) {
    accumulatedLogContent.delete(operation.id);
  }

  // Auto-scroll to bottom if user was already at bottom
  if (shouldScroll) {
    scrollToBottom(logElement);
  }

  // Update modified timestamp
  if (operation.modified) {
    operationFieldset
      .find(".field-modified .readonly")
      .html(getFormattedDateTimeString(operation.modified));
  }

  let colorCode = getStatusColor(operation.status);
  operationFieldset.css("background-color", colorCode);
  setTimeout(function () {
    operationFieldset.addClass("object-updated");
    operationFieldset.css("background-color", "inherit");
  }, 100);
}

function updateStatusWithProgressBar(statusField, operation) {
  let $ = django.jQuery;

  let status = operation.status;
  let logContent = operation.log || "";
  let progressPercentage = getProgressPercentage(status, operation.progress);
  let progressClass = status.replace(/\s+/g, "-");

  if (!statusField.find(".upgrade-status-container").length) {
    statusField.empty();
    statusField.append('<div class="upgrade-status-container"></div>');
  }

  let statusContainer = statusField.find(".upgrade-status-container");

  let statusHtml = `
    <span class="upgrade-status-${progressClass}">${status}</span>
  `;

  // Add progress bar for all statuses
  if (status === "in-progress" || status === "in progress") {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill in-progress" style="width: ${progressPercentage}%"></div>
      </div>
      <span class="upgrade-progress-text">${progressPercentage}%</span>
    `;

    const canCancel = progressPercentage < 60;
    const cancelButtonClass = canCancel
      ? "upgrade-cancel-btn"
      : "upgrade-cancel-btn disabled";
    const cancelButtonTitle = canCancel
      ? "Cancel upgrade"
      : "Cannot cancel - firmware flashing in progress";

    statusHtml += `
      <button class="${cancelButtonClass}" 
              data-operation-id="${operation.id}" 
              title="${cancelButtonTitle}"
              ${!canCancel ? "disabled" : ""}>
        Cancel
      </button>
    `;
  } else if (status === "success") {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill success" style="width: 100%"></div>
      </div>
      <span class="upgrade-progress-text">100%</span>
    `;
  } else if (status === "failed" || status === "aborted") {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${status}" style="width: ${progressPercentage}%"></div>
      </div>
      <span class="upgrade-progress-text">${progressPercentage}%</span>
    `;
  } else {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill" style="width: ${progressPercentage}%"></div>
      </div>
      <span class="upgrade-progress-text">${progressPercentage}%</span>
    `;
  }

  statusContainer.html(statusHtml);

  statusContainer
    .find(".upgrade-cancel-btn:not(.disabled)")
    .off("click")
    .on("click", function (e) {
      e.preventDefault();
      const operationId = $(this).data("operation-id");
      showCancelConfirmationModal(operationId);
    });
}

function getProgressPercentage(status, operationProgress = null) {
  if (operationProgress !== null && operationProgress !== undefined) {
    return Math.min(100, Math.max(0, operationProgress));
  }
  if (status === "success") {
    return 100;
  }
  return 0;
}

function calculateProgressFromLogLength(logContent = "") {
  if (!logContent) return 0;

  const logLines = logContent
    .split("\n")
    .filter((line) => line.trim().length > 0);
  const estimatedTotalSteps = 20;
  const currentProgress = Math.min(
    95,
    (logLines.length / estimatedTotalSteps) * 100,
  );

  return Math.max(5, currentProgress);
}

function updateUpgradeOperationLog(logData) {
  let $ = django.jQuery;

  // Find all in-progress operations and recently completed operations to update their logs
  $("#upgradeoperation_set-group .field-status .readonly").each(function () {
    let statusField = $(this);
    let currentStatusText =
      statusField.find(".upgrade-status-container span").text() ||
      statusField.text().trim();

    // Update logs for in-progress operations and recently completed operations
    if (
      currentStatusText === "in progress" ||
      currentStatusText === "in-progress" ||
      currentStatusText === "success" ||
      currentStatusText === "failed" ||
      currentStatusText === "aborted"
    ) {
      let operationFieldset = $(this).closest("fieldset");
      let logElement = operationFieldset.find(".field-log .readonly");
      let shouldScroll = isScrolledToBottom(logElement);

      // Get operation ID for storing accumulated content
      let operationIdInput = operationFieldset.find("input[name*='id'][value]");
      let operationId =
        operationIdInput.length > 0 ? operationIdInput.val() : "unknown";

      let currentLog;
      if (accumulatedLogContent.has(operationId)) {
        currentLog = accumulatedLogContent.get(operationId);
      } else {
        currentLog = logElement.text().replace(/\s*$/, "");
      }

      let newLog = currentLog
        ? currentLog + "\n" + logData.content
        : logData.content;

      // Store accumulated content in memory
      accumulatedLogContent.set(operationId, newLog);

      // Update log content without spinner
      logElement.html(formatLogForDisplay(newLog));

      // Update progress bar with new log content
      let operation = {
        status: currentStatusText,
        log: newLog,
        id: operationId,
        progress: null,
      };

      updateStatusWithProgressBar(statusField, operation);

      if (shouldScroll) {
        scrollToBottom(logElement);
      }
    }
  });
}

function updateUpgradeOperationStatus(statusData) {
  let $ = django.jQuery;

  // Update status for in-progress operations
  $("#upgradeoperation_set-group .field-status .readonly").each(function () {
    let statusField = $(this);
    let currentStatusText =
      statusField.find(".upgrade-status-container span").text() ||
      statusField.text().trim();

    if (
      currentStatusText === "in progress" ||
      currentStatusText === "in-progress"
    ) {
      // Get current log content for progress calculation
      let operationFieldset = statusField.closest("fieldset");
      let logElement = operationFieldset.find(".field-log .readonly");
      let logContent = logElement.length > 0 ? logElement.text().trim() : "";

      let operation = {
        status: statusData.status,
        log: logContent,
        id: null,
        progress: null,
      };

      updateStatusWithProgressBar(statusField, operation);
    }
  });
}

function getStatusColor(status) {
  switch (status) {
    case "success":
      return "#70bf2b";
    case "failed":
      return "#dd4646";
    case "aborted":
      return "#efb80b";
    case "in-progress":
      return "#cce5ff";
    default:
      return "inherit";
  }
}

function isScrolledToBottom(element) {
  if (!element.length) return false;
  let el = element[0];
  return el.scrollHeight - el.clientHeight <= el.scrollTop + 1;
}

function scrollToBottom(element) {
  if (element.length) {
    let el = element[0];
    el.scrollTop = el.scrollHeight - el.clientHeight;
  }
}

function isUpgradeOperationsAbsent() {
  return document.getElementById("upgradeoperation_set-group") === null;
}

function getObjectIdFromUrl() {
  let objectId;
  try {
    objectId = /\/((\w{4,12}-?)){5}\//.exec(window.location)[0];
  } catch (error) {
    try {
      objectId = /\/(\d+)\//.exec(window.location)[0];
    } catch (error) {
      return null;
    }
  }
  return objectId.replace(/\//g, "");
}

function getWebSocketProtocol() {
  let protocol = "ws://";
  if (window.location.protocol === "https:") {
    protocol = "wss://";
  }
  return protocol;
}

function getFormattedDateTimeString(dateTimeString) {
  let dateTime = new Date(dateTimeString);
  return dateTime.toLocaleString();
}

function showCancelConfirmationModal(operationId) {
  const $ = django.jQuery;

  // Create modal if it doesn't exist
  if ($("#ow-cancel-confirmation-modal").length === 0) {
    createCancelConfirmationModal($);
  }

  // Set the operation ID and show the modal
  $("#ow-cancel-confirmation-modal").data("operation-id", operationId);
  $("#ow-cancel-confirmation-modal").removeClass("ow-hide");
}

function createCancelConfirmationModal($) {
  const modalHtml = `
    <div id="ow-cancel-confirmation-modal" class="ow-overlay ow-overlay-notification ow-overlay-inner ow-hide">
      <div class="ow-dialog-notification ow-cancel-confirmation-dialog">
        <span class="ow-dialog-close ow-dialog-close-x">&times;</span>
        <div class="ow-cancel-confirmation-header">
          <h2 class="ow-cancel-confirmation-title">STOP UPGRADE OPERATION</h2>
        </div>
        <div class="ow-cancel-confirmation-content">
          <p>Are you sure you want to cancel this upgrade operation?</p>
        </div>
        <div class="ow-dialog-buttons ow-cancel-confirmation-buttons">
          <button class="ow-cancel-btn-confirm button default danger-btn">
            Yes
          </button>
          <button class="ow-dialog-close button default">
            No
          </button>
        </div>
      </div>
    </div>
  `;

  $("body").append(modalHtml);

  // Close modal handlers
  $("#ow-cancel-confirmation-modal .ow-dialog-close").on("click", function () {
    $("#ow-cancel-confirmation-modal").addClass("ow-hide");
  });

  // Confirm cancellation handler
  $("#ow-cancel-confirmation-modal .ow-cancel-btn-confirm").on(
    "click",
    function () {
      const operationId = $("#ow-cancel-confirmation-modal").data(
        "operation-id",
      );
      $("#ow-cancel-confirmation-modal").addClass("ow-hide");
      cancelUpgradeOperation(operationId);
    },
  );

  // Close on escape key
  $(document).on("keyup", function (e) {
    if (e.keyCode === 27 && $("#ow-cancel-confirmation-modal").is(":visible")) {
      $("#ow-cancel-confirmation-modal").addClass("ow-hide");
    }
  });

  // Close on overlay click (outside dialog)
  $("#ow-cancel-confirmation-modal").on("click", function (e) {
    if (e.target === this) {
      $(this).addClass("ow-hide");
    }
  });
}

function cancelUpgradeOperation(operationId) {
  const $ = django.jQuery;

  const csrfToken = $("[name=csrfmiddlewaretoken]").val();

  $.ajax({
    url: `/api/v1/firmware-upgrader/upgrade-operation/${operationId}/cancel/`,
    type: "POST",
    headers: {
      "X-CSRFToken": csrfToken,
    },
    success: function (response) {
      if (typeof django.contrib !== "undefined" && django.contrib.messages) {
        django.contrib.messages.success(
          "Upgrade operation cancelled successfully.",
        );
      }
    },
    error: function (xhr, status, error) {
      let errorMessage = "Failed to cancel upgrade operation.";

      if (xhr.responseJSON && xhr.responseJSON.error) {
        errorMessage = xhr.responseJSON.error;
      }

      if (typeof django.contrib !== "undefined" && django.contrib.messages) {
        django.contrib.messages.error(errorMessage);
      } else {
        alert(errorMessage);
      }
    },
  });
}
