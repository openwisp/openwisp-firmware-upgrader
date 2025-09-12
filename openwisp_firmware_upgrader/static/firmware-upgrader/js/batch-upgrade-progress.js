"use strict";

django.jQuery(function ($) {
  const batchUpgradeId = getBatchUpgradeIdFromUrl();

  window.batchUpgradeId = batchUpgradeId;
  if (!batchUpgradeId) {
    return;
  }
  initializeExistingBatchUpgradeOperations($);
  initializeMainProgressBar($);

  const wsHost = owControllerApiHost.host;
  const wsUrl = `${getWebSocketProtocol()}${wsHost}/ws/firmware-upgrader/batch-upgrade-operation/${batchUpgradeId}/`;

  const batchUpgradeProgressWebSocket = new ReconnectingWebSocket(wsUrl, null, {
    automaticOpen: false,
    timeoutInterval: 7000,
    maxRetries: 5,
    retryInterval: 3000,
  });

  window.batchUpgradeProgressWebSocket = batchUpgradeProgressWebSocket;
  // Initialize websocket connection
  initBatchUpgradeProgressWebSockets($, batchUpgradeProgressWebSocket);
});

let batchUpgradeOperationsInitialized = false;

function requestCurrentBatchState(websocket) {
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      const requestMessage = {
        type: "request_current_state",
        batch_id: getBatchUpgradeIdFromUrl(),
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
    let statusText = statusCell.find(".status-content").text().trim();
    if (!statusText) {
      let cellText = statusCell.text().trim();
      statusText = cellText.replace(/\d+%.*$/, "").trim();
    }
    if (
      statusText &&
      (statusText.includes("progress") ||
        statusText === "success" ||
        statusText === "completed successfully" ||
        statusText === "completed with some failures" ||
        statusText === "failed" ||
        statusText === "aborted" ||
        statusText === "cancelled")
    ) {
      let operationId = statusCell.attr("data-operation-id") || "unknown";

      let operation = {
        status: statusText,
        id: operationId,
        progress: null,
      };
      updateBatchStatusWithProgressBar(statusCell, operation);
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
      if (data.type === "batch_status") {
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
    let statusClass = (data.status || "").replace(/\s+/g, "-");
    let showPercentageText = true;

    if (data.status === "success") {
      progressPercentage = 100;
      statusClass = "completed-successfully";
      showPercentageText = true;
    } else if (data.status === "failed") {
      let successfulOpsCount = $("#result_list tbody tr").filter(function () {
        let statusText = $(this).find(".status-cell .status-content").text().trim();
        return statusText === "success" || statusText === "completed successfully";
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
        statusClass = "partial-success";
        showPercentageText = false;
      } else {
        // All operations failed - total failure (red)
        progressPercentage = 100;
        statusClass = "failed";
        showPercentageText = false;
      }
    }

    let progressHtml = `
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${statusClass}" style="width: ${progressPercentage}%"></div>
      </div>
    `;
    if (showPercentageText) {
      progressHtml += `<span class="upgrade-progress-text">${progressPercentage}%</span>`;
    }

    mainProgressElement.html(progressHtml);
  }

  // Update completion information in the admin form if available
  if (data.total && data.completed) {
    let completedInfo = $(".field-completed .readonly");
    if (completedInfo.length > 0) {
      completedInfo.text(`${data.completed} out of ${data.total}`);
    }
  }
  let statusField = $(".field-status .readonly");
  if (statusField.length > 0 && data.status) {
    let displayStatus = data.status;
    if (data.status === "success") {
      displayStatus = "completed successfully";
    } else if (data.status === "failed") {
      displayStatus = "completed with some failures";
    } else if (data.status === "in-progress") {
      displayStatus = "in progress";
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

      updateBatchStatusWithProgressBar(statusCell, operation);
      if (data.modified) {
        let modifiedCell = row.find("td:nth-child(4)");
        modifiedCell.html(getFormattedDateTimeString(data.modified));
      }
    }
  });

  if (!found) {
    addNewOperationRow(data);
  }
}

function addNewOperationRow(data) {
  let $ = django.jQuery;

  if (!data.device_name || !data.device_id) {
    return;
  }
  let tbody = $("#result_list tbody");
  let existingRows = tbody.find("tr").length;
  let rowClass = existingRows % 2 === 0 ? "row1" : "row2";
  tbody.find("tr td[colspan]").parent().remove();
  let deviceUrl = `/admin/firmware_upgrader/upgradeoperation/${data.operation_id}/change/`;
  let imageDisplay = data.image_name || "None";
  let modifiedTime = data.modified
    ? getFormattedDateTimeString(data.modified)
    : "Just now";

  let newRowHtml = `
    <tr class="${rowClass}">
      <td>
        <a href="${deviceUrl}" class="device-link" aria-label="View device ${data.device_name}">
          ${data.device_name}
        </a>
      </td>
      <td class="status-cell" data-operation-id="${data.operation_id}">
        <div class="status-content">${data.status}</div>
      </td>
      <td>${imageDisplay}</td>
      <td>${modifiedTime}</td>
    </tr>
  `;

  tbody.append(newRowHtml);
  let newRow = tbody.find(`tr:last`);
  let statusCell = newRow.find(".status-cell");
  let operation = {
    status: data.status,
    id: data.operation_id,
    progress: data.progress,
  };
  updateBatchStatusWithProgressBar(statusCell, operation);
}

function updateBatchStatusWithProgressBar(statusCell, operation) {
  let $ = django.jQuery;
  let status = operation.status;
  let progressPercentage = getBatchProgressPercentage(status, operation.progress);
  statusCell.empty();
  statusCell.append('<div class="upgrade-status-container"></div>');
  let statusContainer = statusCell.find(".upgrade-status-container");
  let statusHtml = "";

  if (status === "in-progress" || status === "in progress") {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill in-progress" style="width: ${progressPercentage}%"></div>
      </div>`;
  } else if (status === "success" || status === "completed successfully") {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill success" style="width: 100%"></div>
      </div>`;
  } else if (status === "failed") {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill failed" style="width: 100%"></div>
      </div>`;
  } else if (status === "aborted") {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill aborted" style="width: 100%"></div>
      </div>`;
  } else if (status === "cancelled") {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill cancelled" style="width: 100%"></div>
      </div>`;
  } else {
    statusHtml = `<div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill" style="width: ${progressPercentage}%"></div>
      </div>`;
  }
  statusContainer.html(statusHtml);
}

function getBatchProgressPercentage(status, operationProgress = null) {
  if (operationProgress !== null && operationProgress !== undefined) {
    return Math.min(100, Math.max(5, operationProgress));
  }
  if (
    status === "completed successfully" ||
    status === "success" ||
    status === "failed" ||
    status === "aborted" ||
    status === "cancelled"
  ) {
    return 100;
  }
  return 5;
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

function getWebSocketProtocol() {
  let protocol = "ws://";
  if (window.location.protocol === "https:") {
    protocol = "wss://";
  }
  return protocol;
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
      let showPercentageText = true;

      if (currentStatusText === "completed successfully") {
        statusClass = "completed-successfully";
        showPercentageText = true;
      } else if (currentStatusText === "completed with some failures") {
        statusClass = "partial-success";
        showPercentageText = false;
      } else if (currentStatusText === "in progress") {
        statusClass = "in-progress";
        showPercentageText = true;
        progressPercentage = 0;
      } else {
        statusClass = "failed";
        showPercentageText = false;
      }

      let progressHtml = `
        <div class="upgrade-progress-bar">
          <div class="upgrade-progress-fill ${statusClass}" style="width: ${progressPercentage}%"></div>
        </div>
      `;
      if (showPercentageText) {
        progressHtml += `<span class="upgrade-progress-text">${progressPercentage}%</span>`;
      }
      mainProgressElement.html(progressHtml);
    }
  }
}

function getFormattedDateTimeString(dateTimeString) {
  let dateTime = new Date(dateTimeString);
  return dateTime.toLocaleString();
}
