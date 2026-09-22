"use strict";

django.jQuery(function ($) {
  const batchUpgradeId = getBatchUpgradeIdFromUrl();
  window.batchUpgradeId = batchUpgradeId;
  if (!batchUpgradeId) {
    return;
  }
  initializeExistingBatchUpgradeOperations($);
  initializeMainProgressBar($);
  const wsHost = getFirmwareUpgraderApiHost();
  if (!wsHost) {
    // helper already printed message; skip websocket setup
    return;
  }

  const wsUrl = `${getWebSocketProtocol()}${wsHost}/ws/firmware-upgrader/batch-upgrade-operation/${batchUpgradeId}/`;

  const batchUpgradeProgressWebSocket = new ReconnectingWebSocket(wsUrl, null, {
    automaticOpen: false,
    timeoutInterval: 7000,
    maxReconnectAttempts: 10,
    reconnectInterval: 30000,
    reconnectDecay: 2,
  });
  window.batchUpgradeProgressWebSocket = batchUpgradeProgressWebSocket;
  // Initialize websocket connection
  initBatchUpgradeProgressWebSockets($, batchUpgradeProgressWebSocket);
});

let batchUpgradeOperationsInitialized = false;
let batchUpgradeResultsRefreshTimeout = null;
let batchUpgradeResultsRefreshRequest = null;
let batchUpgradeResultsRefreshPending = false;

function requestCurrentBatchState(websocket) {
  let $ = django.jQuery;
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      const operationIds = $("#result_list tbody td.status-cell")
        .map(function () {
          return $(this).attr("data-operation-id");
        })
        .get()
        .filter(Boolean);

      const requestMessage = {
        type: "request_current_state",
        batch_id: window.batchUpgradeId,
        operation_ids: operationIds,
      };
      websocket.send(JSON.stringify(requestMessage));
    } catch (error) {
      console.error("Error requesting current batch state:", error);
    }
  }
}

function initializeExistingBatchUpgradeOperations($, isRetry = false) {
  if (batchUpgradeOperationsInitialized && isRetry) {
    return;
  }
  let statusCells = $("#result_list tbody td.status-cell");
  let processedCount = 0;
  statusCells.each(function () {
    let statusCell = $(this);
    if (statusCell.find(".upgrade-status-container").length > 0) {
      return;
    }
    let operationStatus = statusCell.attr("data-operation-status");
    if (operationStatus && FW_STATUS_HELPERS.isValid(operationStatus)) {
      let operationId = statusCell.attr("data-operation-id") || "unknown";
      let operation = {
        status: operationStatus,
        id: operationId,
        progress: null,
      };
      renderOperationProgressBarInCell(statusCell, operation);
      processedCount++;
    }
  });

  if (processedCount > 0 || isRetry) {
    batchUpgradeOperationsInitialized = true;
  } else if (!isRetry) {
    setTimeout(function () {
      initializeExistingBatchUpgradeOperations($, true);
    }, 1000);
  }
}

function initBatchUpgradeProgressWebSockets($, batchUpgradeProgressWebSocket) {
  batchUpgradeProgressWebSocket.addEventListener("open", function (e) {
    let existingContainers = $(
      "#result_list tbody td.status-cell .upgrade-status-container",
    );
    if (existingContainers.length === 0) {
      batchUpgradeOperationsInitialized = false;
      requestCurrentBatchState(batchUpgradeProgressWebSocket);
      initializeExistingBatchUpgradeOperations($, false);
    } else {
      // Just request current state without reinitializing
      requestCurrentBatchState(batchUpgradeProgressWebSocket);
    }
  });

  batchUpgradeProgressWebSocket.addEventListener("close", function (e) {
    batchUpgradeOperationsInitialized = false;
    if (e.code === 1006) {
      console.error("WebSocket closed");
    }
  });

  batchUpgradeProgressWebSocket.addEventListener("error", function (e) {
    console.error("WebSocket error occurred", e);
  });

  batchUpgradeProgressWebSocket.addEventListener("message", function (e) {
    try {
      let data = JSON.parse(e.data);
      if (data.type === "batch_state") {
        updateBatchProgress(data.batch_status);
        if (data.operations && Array.isArray(data.operations)) {
          data.operations.forEach(function (operation) {
            updateBatchOperationProgress({
              operation_id: operation.id,
              status: operation.status,
              progress: operation.progress,
              modified: operation.modified,
            });
          });
        }
      } else if (data.type === "batch_status") {
        updateBatchProgress(data);
      } else if (data.type === "operation_progress") {
        updateBatchOperationProgress(data);
      } else if (data.type === "operation_update") {
        updateBatchOperationProgress({
          operation_id: data.operation.id,
          status: data.operation.status,
          progress: data.operation.progress,
          modified: data.operation.modified,
        });
      }
    } catch (error) {
      console.error("Error parsing WebSocket message:", error);
    }
  });
  batchUpgradeProgressWebSocket.open();
}
function updateBatchProgress(data) {
  let $ = django.jQuery;
  let mainProgressElement = $(".batch-main-progress");
  if (mainProgressElement.length > 0) {
    let progressPercentage =
      data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0;
    let showPercentageText = true;
    let statusClass = FW_UPGRADE_CSS_CLASSES.IN_PROGRESS; // Safe default

    if (data.status === FW_UPGRADE_STATUS.SUCCESS) {
      progressPercentage = 100;
      statusClass = FW_UPGRADE_CSS_CLASSES.COMPLETED_SUCCESSFULLY;
      showPercentageText = true;
    } else if (data.status === FW_UPGRADE_STATUS.CANCELLED) {
      progressPercentage = 100;
      statusClass = FW_UPGRADE_CSS_CLASSES.CANCELLED;
      showPercentageText = false;
    } else if (data.status === FW_UPGRADE_STATUS.FAILED) {
      let successfulOpsCount = $("#result_list tbody tr").filter(function () {
        let statusText = $(this).find(".status-cell .status-content").text().trim();
        return FW_STATUS_GROUPS.SUCCESS.has(statusText);
      }).length;
      // Also check individual operation containers for success
      if (successfulOpsCount === 0) {
        $("#result_list tbody tr").each(function () {
          let statusContainer = $(this).find(".upgrade-status-container");
          if (
            statusContainer.length &&
            statusContainer.find(".upgrade-progress-fill.success").length
          ) {
            successfulOpsCount++;
          }
        });
      }
      if (successfulOpsCount > 0) {
        // Some operations succeeded - partial success (orange)
        progressPercentage = 100;
        statusClass = FW_UPGRADE_CSS_CLASSES.PARTIAL_SUCCESS;
        showPercentageText = false;
      } else {
        // All operations failed - total failure (red)
        progressPercentage = 100;
        statusClass = FW_UPGRADE_CSS_CLASSES.FAILED;
        showPercentageText = false;
      }
    }
    let progressHtml = `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${escapeHtml(statusClass)}"
             style="width: ${escapeHtml(String(progressPercentage))}%">
        </div>
      </div>
    `;
    if (showPercentageText) {
      progressHtml += `<span class="upgrade-progress-text">
        ${escapeHtml(String(progressPercentage))}%
      </span>`;
    }
    mainProgressElement.html(progressHtml);
  }
  // Update completion information in the admin form if available
  if (data.total !== undefined && data.completed !== undefined) {
    let completedInfo = $(".field-completed .readonly");
    if (completedInfo.length > 0) {
      completedInfo.text(`${data.completed} out of ${data.total}`);
    }
  }

  let statusField = $(".field-status .readonly");
  if (statusField.length > 0 && data.status) {
    let displayStatus = data.status;
    if (data.status === FW_UPGRADE_STATUS.SUCCESS) {
      displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_SUCCESSFULLY;
    } else if (data.status === FW_UPGRADE_STATUS.CANCELLED) {
      displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_CANCELLATIONS;
    } else if (data.status === FW_UPGRADE_STATUS.FAILED) {
      displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_FAILURES;
    } else if (data.status === FW_UPGRADE_STATUS.IN_PROGRESS) {
      displayStatus = FW_UPGRADE_DISPLAY_STATUS.IN_PROGRESS;
    }
    let progressBar = statusField.find(".batch-main-progress");
    let statusText = statusField
      .contents()
      .not(progressBar)
      .filter(function () {
        return this.nodeType === 3 && this.textContent.trim();
      })
      .first();
    if (statusText.length > 0) {
      statusText[0].textContent = displayStatus;
    } else {
      progressBar.before(document.createTextNode(displayStatus));
    }
  }
}

function updateBatchOperationProgress(data) {
  let $ = django.jQuery;
  let found = false;
  $("#result_list tbody tr").each(function () {
    let row = $(this);
    let statusCell = row.find("td.status-cell");
    let operationId = statusCell.attr("data-operation-id");

    if (operationId === data.operation_id) {
      found = true;
      let operation = {
        status: data.status,
        id: data.operation_id,
        progress: data.progress,
      };
      renderOperationProgressBarInCell(statusCell, operation);
      if (data.modified) {
        let modifiedCell = row.find("td:nth-child(4)");
        modifiedCell.text(getFormattedDateTimeString(data.modified));
      }
    }
  });
  if (!found) {
    scheduleBatchUpgradeResultsRefresh();
  }
}

function scheduleBatchUpgradeResultsRefresh() {
  if (batchUpgradeResultsRefreshRequest) {
    batchUpgradeResultsRefreshPending = true;
    return;
  }

  if (batchUpgradeResultsRefreshTimeout) {
    return;
  }

  batchUpgradeResultsRefreshTimeout = setTimeout(function () {
    batchUpgradeResultsRefreshTimeout = null;
    refreshBatchUpgradeResults();
  }, 250);
}

function refreshBatchUpgradeResults() {
  let $ = django.jQuery;

  if (batchUpgradeResultsRefreshRequest) {
    batchUpgradeResultsRefreshPending = true;
    return;
  }

  batchUpgradeResultsRefreshRequest = $.ajax({
    url: window.location.href,
    type: "GET",
    success: function (response) {
      let currentResults = $(".results-container");
      let updatedResults = $(response).find(".results-container");

      if (currentResults.length && updatedResults.length) {
        currentResults.replaceWith(updatedResults);
        batchUpgradeOperationsInitialized = false;
        initializeExistingBatchUpgradeOperations($, true);

        if (window.batchUpgradeProgressWebSocket) {
          requestCurrentBatchState(window.batchUpgradeProgressWebSocket);
        }
      }
    },
    error: function (xhr, status, error) {
      console.error("Failed to refresh batch upgrade results:", error);
    },
    complete: function () {
      batchUpgradeResultsRefreshRequest = null;

      if (batchUpgradeResultsRefreshPending) {
        batchUpgradeResultsRefreshPending = false;
        scheduleBatchUpgradeResultsRefresh();
      }
    },
  });
}

function renderOperationProgressBarInCell(statusCell, operation) {
  // Renders a visual progress bar in the given status cell based on the
  // operation's status and progress.
  let $ = django.jQuery;
  let status = operation.status;
  let progressPercentage = normalizeProgress(operation.progress, status);
  statusCell.empty();
  statusCell.append('<div class="upgrade-status-container"></div>');
  let statusContainer = statusCell.find(".upgrade-status-container");
  let statusClass = STATUS_TO_CSS_CLASS[status] || "";
  if (STATUSES_WITH_FULL_PROGRESS.has(status)) {
    progressPercentage = 100;
  }
  // Per operation bars do not show percentage text to keep table rows compact
  let progressHtml = renderProgressBarHtml(progressPercentage, statusClass, false);
  statusContainer.html(progressHtml);
}

function getBatchUpgradeIdFromUrl() {
  try {
    let matches = window.location.pathname.match(/\/batchupgradeoperation\/([^\/]+)\//);
    return matches && matches[1] ? matches[1] : null;
  } catch (error) {
    console.error("Error extracting batch ID from URL:", error);
    return null;
  }
}

function initializeMainProgressBar($) {
  let statusField = $(".field-status .readonly");
  if (statusField.length > 0) {
    let currentStatusText = statusField
      .contents()
      .filter(function () {
        return this.nodeType === 3 && this.textContent.trim();
      })
      .first()
      .text()
      .trim();
    let mainProgressElement = $(".batch-main-progress");
    if (mainProgressElement.length > 0 && currentStatusText) {
      let progressPercentage = 100;
      let statusClass = "";
      let showPercentageText;

      if (currentStatusText === FW_UPGRADE_DISPLAY_STATUS.COMPLETED_SUCCESSFULLY) {
        statusClass = FW_UPGRADE_CSS_CLASSES.COMPLETED_SUCCESSFULLY;
        showPercentageText = true;
      } else if (
        currentStatusText === FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_CANCELLATIONS
      ) {
        statusClass = FW_UPGRADE_CSS_CLASSES.CANCELLED;
        showPercentageText = false;
      } else if (
        currentStatusText === FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_FAILURES
      ) {
        statusClass = FW_UPGRADE_CSS_CLASSES.PARTIAL_SUCCESS;
        showPercentageText = false;
      } else if (currentStatusText === FW_UPGRADE_DISPLAY_STATUS.IN_PROGRESS) {
        statusClass = FW_UPGRADE_CSS_CLASSES.IN_PROGRESS;
        showPercentageText = true;
        progressPercentage = 0;
      } else {
        statusClass = FW_UPGRADE_CSS_CLASSES.FAILED;
        showPercentageText = false;
      }
      let progressHtml = `
        <div class="upgrade-progress-bar">
          <div class="upgrade-progress-fill ${escapeHtml(statusClass)}"
               style="width: ${escapeHtml(progressPercentage)}%">
          </div>
        </div>
      `;
      if (showPercentageText) {
        progressHtml += `<span class="upgrade-progress-text">
          ${escapeHtml(progressPercentage)}%
        </span>`;
      }
      mainProgressElement.html(progressHtml);
    }
  }
}
