"use strict";

django.jQuery(function ($) {
  // Detect page type and get appropriate ID
  const pageType = detectPageType();
  const pageId = getPageId(pageType);

  if (!pageId) {
    return;
  }

  window.upgradePageType = pageType;
  window.upgradePageId = pageId;

  // Initialize based on page type
  if (pageType === "device") {
    // Device page with multiple operations
    initializeExistingUpgradeOperations($);
  } else if (pageType === "operation") {
    // Single operation page
    initializeExistingUpgradeOperation($);
  }

  // Use the controller API host (always defined in change_form.html)
  const wsHost = owFirmwareUpgraderApiHost.host;
  const wsUrl = getWebSocketUrl(pageType, pageId, wsHost);

  const upgradeProgressWebSocket = new ReconnectingWebSocket(wsUrl, null, {
    automaticOpen: false,
    timeoutInterval: 7000,
    maxRetries: 5,
    retryInterval: 3000,
  });

  window.upgradeProgressWebSocket = upgradeProgressWebSocket;
  // Initialize websocket connection
  initUpgradeProgressWebSockets($, upgradeProgressWebSocket);
});

let upgradeOperationsInitialized = false;

// Store accumulated log content to preserve across WebSocket reconnections
let accumulatedLogContent = new Map();
// For single operation pages, use a simple string
let singleOperationLogContent = "";

function formatLogForDisplay(logContent) {
  return logContent ? logContent.replace(/\n/g, "<br>") : "";
}

function requestCurrentOperationState(websocket) {
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      let requestMessage = {
        type: "request_current_state",
      };

      // Add appropriate ID based on page type
      if (window.upgradePageType === "device") {
        requestMessage.device_id = window.upgradePageId;
      } else if (window.upgradePageType === "operation") {
        requestMessage.operation_id = window.upgradePageId;
      }

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
      (FW_STATUS_HELPERS.includesProgress(statusText) ||
        ALL_VALID_FW_STATUSES.has(statusText))
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

function initializeExistingUpgradeOperation($, isRetry = false) {
  if (upgradeOperationsInitialized && isRetry) {
    return;
  }

  let statusField = $(".field-status .readonly");
  let logElement = $(".field-log .readonly");

  if (statusField.find(".upgrade-status-container").length > 0) {
    return;
  }

  let statusText = statusField.text().trim();

  if (statusText) {
    let operationId = window.upgradePageId;
    let logContent;

    if (singleOperationLogContent) {
      logContent = singleOperationLogContent;
      if (logElement.length > 0) {
        logElement.html(formatLogForDisplay(logContent));
      }
    } else {
      logContent = logElement.length > 0 ? logElement.text().trim() : "";
      if (logContent && operationId) {
        singleOperationLogContent = logContent;
      }
    }

    let operation = {
      status: statusText,
      log: logContent,
      id: operationId,
      progress: null,
    };

    updateSingleOperationStatusWithProgressBar(statusField, operation);
    upgradeOperationsInitialized = true;
  } else if (!isRetry) {
    setTimeout(function () {
      initializeExistingUpgradeOperation($, true);
    }, 1000);
  }
}

function initUpgradeProgressWebSockets($, upgradeProgressWebSocket) {
  upgradeProgressWebSocket.addEventListener("open", function (e) {
    upgradeOperationsInitialized = false;
    requestCurrentOperationState(upgradeProgressWebSocket);

    // Initialize based on page type
    if (window.upgradePageType === "device") {
      initializeExistingUpgradeOperations($, false);
    } else if (window.upgradePageType === "operation") {
      initializeExistingUpgradeOperation($, false);
    }
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

      // Handle different message formats based on page type
      if (window.upgradePageType === "device") {
        // Device page - multiple operations
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
      } else if (window.upgradePageType === "operation") {
        // Single operation page
        if (data.type === "operation_update") {
          updateSingleUpgradeOperationDisplay(data.operation);
        } else if (data.type === "log") {
          updateSingleUpgradeOperationLog(data);
        } else if (data.type === "status") {
          updateSingleUpgradeOperationStatus(data);
        }
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
  if (FW_STATUS_HELPERS.isCompleted(operation.status)) {
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
  if (FW_STATUS_GROUPS.IN_PROGRESS.has(status)) {
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
      ? gettext("Cancel upgrade")
      : gettext("Cannot cancel - firmware flashing in progress");

    statusHtml += `
      <button class="${cancelButtonClass}"
              data-operation-id="${operation.id}"
              title="${cancelButtonTitle}"
              ${!canCancel ? "disabled" : ""}>
        ${gettext("Cancel")}
      </button>
    `;
  } else if (status === FW_UPGRADE_STATUS.SUCCESS) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill success" style="width: 100%"></div>
      </div>
      <span class="upgrade-progress-text">100%</span>
    `;
  } else if (FW_STATUS_GROUPS.FAILURE.has(status)) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${status}" style="width: 100%"></div>
      </div>
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
    return Math.min(100, Math.max(5, operationProgress));
  }
  if (status === FW_UPGRADE_STATUS.SUCCESS) {
    return 100;
  }
  return 5;
}

function calculateProgressFromLogLength(logContent = "") {
  if (!logContent) return 0;

  const logLines = logContent.split("\n").filter((line) => line.trim().length > 0);
  const estimatedTotalSteps = 20;
  const currentProgress = Math.min(95, (logLines.length / estimatedTotalSteps) * 100);

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
      FW_STATUS_GROUPS.IN_PROGRESS.has(currentStatusText) ||
      FW_STATUS_HELPERS.isCompleted(currentStatusText)
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

      let newLog = currentLog ? currentLog + "\n" + logData.content : logData.content;

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

    if (FW_STATUS_GROUPS.IN_PROGRESS.has(currentStatusText)) {
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

// Single operation update functions
function updateSingleUpgradeOperationDisplay(operation) {
  let $ = django.jQuery;
  let statusField = $(".field-status .readonly");
  let logElement = $(".field-log .readonly");

  if (operation.log && operation.id) {
    singleOperationLogContent = operation.log;
  }

  updateSingleOperationStatusWithProgressBar(statusField, operation);

  let shouldScroll = isScrolledToBottom(logElement);

  logElement.html(formatLogForDisplay(operation.log));
  if (FW_STATUS_HELPERS.isCompleted(operation.status)) {
    singleOperationLogContent = "";
  }

  if (shouldScroll) {
    scrollToBottom(logElement);
  }

  if (operation.modified) {
    $(".field-modified .readonly").html(getFormattedDateTimeString(operation.modified));
  }
}

function updateSingleOperationStatusWithProgressBar(statusField, operation) {
  let $ = django.jQuery;
  let status = operation.status;
  let progressPercentage = getProgressPercentage(status, operation.progress);
  let progressClass = status.replace(/\s+/g, "-");

  if (!statusField.find(".upgrade-status-container").length) {
    statusField.empty();
    statusField.append('<div class="upgrade-status-container"></div>');
  }

  let statusContainer = statusField.find(".upgrade-status-container");
  let statusHtml = `<span class="upgrade-status-${progressClass}">${status}</span>`;

  if (FW_STATUS_GROUPS.IN_PROGRESS.has(status)) {
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
      ? gettext("Cancel upgrade")
      : gettext("Cannot cancel - firmware flashing in progress");

    statusHtml += `
      <button class="${cancelButtonClass}"
              data-operation-id="${operation.id}"
              title="${cancelButtonTitle}"
              ${!canCancel ? "disabled" : ""}>
        ${gettext("Cancel")}
      </button>
    `;
  } else if (status === FW_UPGRADE_STATUS.SUCCESS) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill success" style="width: 100%"></div>
      </div>
      <span class="upgrade-progress-text">100%</span>
    `;
  } else if (status === FW_UPGRADE_STATUS.CANCELLED) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill cancelled" style="width: 100%"></div>
      </div>
    `;
  } else if (
    status === FW_UPGRADE_STATUS.FAILED ||
    status === FW_UPGRADE_STATUS.ABORTED
  ) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${status}" style="width: 100%"></div>
      </div>
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

function updateSingleUpgradeOperationLog(logData) {
  let $ = django.jQuery;
  let logElement = $(".field-log .readonly");
  let shouldScroll = isScrolledToBottom(logElement);

  let currentLog = singleOperationLogContent || logElement.text().replace(/\s*$/, "");
  let newLog = currentLog ? currentLog + "\n" + logData.content : logData.content;

  singleOperationLogContent = newLog;
  logElement.html(formatLogForDisplay(newLog));

  let statusField = $(".field-status .readonly");
  let currentStatusText =
    statusField.find(".upgrade-status-container span").text() ||
    statusField.text().trim();

  let operation = {
    status: currentStatusText,
    log: newLog,
    id: window.upgradePageId,
    progress: null,
  };

  updateSingleOperationStatusWithProgressBar(statusField, operation);

  if (shouldScroll) {
    scrollToBottom(logElement);
  }
}

function updateSingleUpgradeOperationStatus(statusData) {
  let $ = django.jQuery;
  let statusField = $(".field-status .readonly");
  let logElement = $(".field-log .readonly");
  let logContent = logElement.length > 0 ? logElement.text().trim() : "";

  let operation = {
    status: statusData.status,
    log: logContent,
    id: window.upgradePageId,
    progress: null,
  };

  updateSingleOperationStatusWithProgressBar(statusField, operation);
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

function detectPageType() {
  // Check if it's a single upgrade operation page
  if (document.getElementById("upgradeoperation_form")) {
    return "operation";
  }
  // Check if it's a device page (with upgrade operations)
  if (document.getElementById("upgradeoperation_set-group")) {
    return "device";
  }
  return null;
}

function getPageId(pageType) {
  if (pageType === "operation") {
    return getOperationIdFromUrl();
  } else if (pageType === "device") {
    return getObjectIdFromUrl();
  }
  return null;
}

function getWebSocketUrl(pageType, pageId, wsHost) {
  const protocol = getWebSocketProtocol();
  if (pageType === "operation") {
    return `${protocol}${wsHost}/ws/firmware-upgrader/upgrade-operation/${pageId}/`;
  } else if (pageType === "device") {
    return `${protocol}${wsHost}/ws/firmware-upgrader/device/${pageId}/`;
  }
  return null;
}

function getOperationIdFromUrl() {
  try {
    let matches = window.location.pathname.match(/\/upgradeoperation\/([^\/]+)\//);
    return matches && matches[1] ? matches[1] : null;
  } catch (error) {
    console.error("Error extracting operation ID from URL:", error);
    return null;
  }
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
          <h2 class="ow-cancel-confirmation-title">${gettext("Stop upgrade operation")}</h2>
        </div>
        <div class="ow-cancel-confirmation-content">
          <p>${gettext("Are you sure you want to cancel this upgrade operation?")}</p>
        </div>
        <div class="ow-dialog-buttons ow-cancel-confirmation-buttons">
          <button class="ow-cancel-btn-confirm button default danger-btn">
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

  // Close modal handlers
  $("#ow-cancel-confirmation-modal .ow-dialog-close").on("click", function () {
    $("#ow-cancel-confirmation-modal").addClass("ow-hide");
  });

  // Confirm cancellation handler
  $("#ow-cancel-confirmation-modal .ow-cancel-btn-confirm").on("click", function () {
    const operationId = $("#ow-cancel-confirmation-modal").data("operation-id");
    $("#ow-cancel-confirmation-modal").addClass("ow-hide");
    cancelUpgradeOperation(operationId);
  });

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

  // Show loading overlay
  $("#ow-loading").show();

  $.ajax({
    url: `/api/v1/firmware-upgrader/upgrade-operation/${operationId}/cancel/`,
    type: "POST",
    headers: {
      "X-CSRFToken": $('input[name="csrfmiddlewaretoken"]').val(),
    },
    xhrFields: {
      withCredentials: true,
    },
    crossDomain: true,
    success: function (response) {
      $("#ow-loading").hide();

      if (typeof django.contrib !== "undefined" && django.contrib.messages) {
        django.contrib.messages.success(
          gettext("Upgrade operation cancelled successfully."),
        );
      }
    },
    error: function (xhr, status, error) {
      $("#ow-loading").hide();

      let errorMessage = gettext("Failed to cancel upgrade operation.");
      if (xhr.responseJSON && xhr.responseJSON.error) {
        errorMessage = xhr.responseJSON.error;
      }

      if (typeof django.contrib !== "undefined" && django.contrib.messages) {
        django.contrib.messages.error(errorMessage);
      } else {
        console.error(errorMessage);
      }
    },
  });
}
