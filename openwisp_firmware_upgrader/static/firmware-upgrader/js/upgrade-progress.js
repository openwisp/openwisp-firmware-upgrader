"use strict";

django.jQuery &&
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
      initializeExistingMultiUpgrades($);
    } else if (pageType === "operation") {
      // Single operation page
      initializeExistingSingleUpgrade($);
    }

    const wsHost = getFirmwareUpgraderApiHost();
    if (!wsHost) {
      // error already logged by helper
      return;
    }
    const wsUrl = getWebSocketUrl(pageType, pageId, wsHost);

    const upgradeProgressWebSocket = new ReconnectingWebSocket(wsUrl, null, {
      automaticOpen: false,
      timeoutInterval: 7000,
      maxReconnectAttempts: 5,
      reconnectInterval: 3000,
    });

    window.upgradeProgressWebSocket = upgradeProgressWebSocket;
    // Initialize websocket connection
    initUpgradeProgressWebSockets($, upgradeProgressWebSocket);
  });

let upgradeOperationsInitialized = false;

// Store accumulated log content to preserve across WebSocket reconnections
let accumulatedLogContent = new Map();

function formatLogForDisplay(logContent) {
  return logContent ? escapeHtml(logContent).replace(/\n/g, "<br>") : "";
}

function getSanitizedStatusFromField(statusField) {
  let statusText =
    statusField.find(".upgrade-progress-text").text() || statusField.text().trim();
  statusText = statusText.replace(/\d+%.*$/, "").trim();
  let statusKey = getKeyFromValue(FW_UPGRADE_DISPLAY_STATUS, statusText);
  return FW_UPGRADE_STATUS[statusKey];
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

function initializeExistingMultiUpgrades($, isRetry = false) {
  if (upgradeOperationsInitialized && isRetry) {
    return;
  }
  let statusFields = $("#upgradeoperation_set-group .field-status .readonly");
  let processedCount = 0;
  // loop over all the stauts fields
  statusFields.each(function (index) {
    let statusField = $(this);
    let statusValue = getSanitizedStatusFromField(statusField);
    if (statusField.find(".upgrade-status-container").length > 0) {
      return;
    }
    if (
      statusValue &&
      (FW_STATUS_HELPERS.includesProgress(statusValue) ||
        ALL_VALID_FW_STATUSES.has(statusValue))
    ) {
      let operationFieldset = statusField.closest(".dynamic-upgradeoperation_set");
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
        status: statusValue,
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
      initializeExistingMultiUpgrades($, true);
    }, 1000);
  }
}

function initializeExistingSingleUpgrade($, isRetry = false) {
  if (upgradeOperationsInitialized && isRetry) {
    return;
  }
  let statusField = $(".field-status .readonly");
  let logElement = $(".field-log .readonly");
  if (statusField.find(".upgrade-status-container").length > 0) {
    return;
  }
  let statusValue = getSanitizedStatusFromField(statusField);
  if (statusValue) {
    let operationId = window.upgradePageId;
    let logContent = logElement.length > 0 ? logElement.text().trim() : "";
    if (logContent && operationId) {
      accumulatedLogContent.set(operationId, logContent);
    }
    let operation = {
      status: statusValue,
      log: logContent,
      id: operationId,
      progress: null,
    };
    updateStatusWithProgressBar(statusField, operation);
    upgradeOperationsInitialized = true;
  } else if (!isRetry) {
    setTimeout(function () {
      initializeExistingSingleUpgrade($, true);
    }, 1000);
  }
}

function initUpgradeProgressWebSockets($, upgradeProgressWebSocket) {
  upgradeProgressWebSocket.addEventListener("open", function (e) {
    upgradeOperationsInitialized = false;
    requestCurrentOperationState(upgradeProgressWebSocket);
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
      // Both device & operation pages receive "operation_update" events.
      if (data.type === "operation_update") {
        let op = data.operation;
        if (op) {
          updateUpgradeOperationDisplay(op);
        }
      }
    } catch (error) {
      console.error("Error parsing WebSocket message:", error);
    }
  });
  upgradeProgressWebSocket.open();
}

function updateUpgradeOperationDisplay(operation) {
  let $ = django.jQuery,
    operationFieldset;

  if (window.upgradePageType === "device") {
    let operationIdInputField = $(`input[value="${$.escapeSelector(operation.id)}"]`);
    if (!operationIdInputField.length) {
      return;
    }
    operationFieldset = operationIdInputField.parent().find("fieldset");
  } else if (window.upgradePageType === "operation") {
    operationFieldset = $("#upgradeoperation_form fieldset");
  }

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
  let progressPercentage = getProgressPercentage(status, operation.progress);
  let progressClass = status.replace(/\s+/g, "-");
  let statusKey = getKeyFromValue(FW_UPGRADE_STATUS, status);
  let statusHtml = `
    <span class="upgrade-status-${escapeHtml(progressClass)}">
      ${FW_UPGRADE_DISPLAY_STATUS[statusKey]}
    </span>
  `;
  if (FW_STATUS_GROUPS.IN_PROGRESS.has(status)) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill in-progress"
             style="width: ${escapeHtml(progressPercentage)}%">
        </div>
      </div>
      <span class="upgrade-progress-text">
        ${escapeHtml(progressPercentage)}%
      </span>
    `;
    const canCancel = progressPercentage < 65;
    const cancelButtonClass = canCancel
      ? "upgrade-cancel-btn"
      : "upgrade-cancel-btn disabled";
    const cancelButtonTitle = canCancel
      ? gettext("Cancel upgrade")
      : gettext("Cannot cancel - firmware flashing in progress");
    statusHtml += `
      <button class="${escapeHtml(cancelButtonClass)}"
              data-operation-id="${escapeHtml(operation.id)}"
              title="${escapeHtml(cancelButtonTitle)}"
              ${!canCancel ? "disabled" : ""}>
        ${gettext("Cancel")}
      </button>
    `;
  } else if (FW_STATUS_GROUPS.SUCCESS.has(status)) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill success"
             style="width: 100%">
        </div>
      </div>
      <span class="upgrade-progress-text">100%</span>
    `;
  } else if (FW_STATUS_GROUPS.FAILURE.has(status)) {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${escapeHtml(status)}"
             style="width: 100%">
        </div>
      </div>
    `;
  } else {
    statusHtml += `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill"
             style="width: ${progressPercentage}%">
        </div>
      </div>
      <span class="upgrade-progress-text">
        ${progressPercentage}%
      </span>
    `;
  }
  if (!statusField.find(".upgrade-status-container").length) {
    statusField.empty();
    statusField.append('<div class="upgrade-status-container"></div>');
  }
  let statusContainer = statusField.find(".upgrade-status-container");
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
  if (status === FW_UPGRADE_STATUS.SUCCESS) {
    return 100;
  }
  return 0;
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
    url: owUpgradeOperationCancelUrl.replace(
      "00000000-0000-0000-0000-000000000000",
      operationId,
    ),
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
    },
    error: function (xhr, status, error) {
      $("#ow-loading").hide();
      let errorMessage = gettext("Failed to cancel upgrade operation.");
      alert(errorMessage);
    },
  });
}
