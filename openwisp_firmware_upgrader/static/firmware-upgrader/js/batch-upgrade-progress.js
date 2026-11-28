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

function requestCurrentBatchState(websocket) {
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      const requestMessage = {
        type: "request_current_state",
        batch_id: window.batchUpgradeId,
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
          // Replay the initial snapshot onto each existing row.
          const mayAdd = snapshotMayAddRows($);
          data.operations.forEach(function (operation) {
            updateBatchOperationProgress(
              {
                operation_id: operation.id,
                status: operation.status,
                progress: operation.progress,
                modified: operation.modified,
                is_persistent: operation.is_persistent,
                retry_count: operation.retry_count,
                next_retry_at: operation.next_retry_at,
                device_id: operation.device_id,
                device_name: operation.device_name,
                image_name: operation.image_name,
              },
              mayAdd,
            );
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
          is_persistent: data.operation.is_persistent,
          retry_count: data.operation.retry_count,
          next_retry_at: data.operation.next_retry_at,
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
  if (data.status && FW_STATUS_HELPERS.isCompleted(data.status)) {
    // A terminal batch can no longer be cancelled or rescheduled.
    $(".batch-actions").remove();
    $("#upgrade-operations-section").removeClass("ow-hide");
  } else if (data.status && data.status !== "scheduled") {
    $("#batch-reschedule-btn, #batch-reschedule-form").remove();
    let $section = $("#upgrade-operations-section");
    if ($section.hasClass("ow-hide")) {
      $section.removeClass("ow-hide");
      requestCurrentBatchState(window.batchUpgradeProgressWebSocket);
    }
  }
  let mainProgressElement = $(".batch-main-progress");
  if (mainProgressElement.length > 0) {
    let progressPercentage =
      data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0;
    let showPercentageText = true;
    let statusClass = FW_UPGRADE_CSS_CLASSES.IN_PROGRESS; // Safe default

    switch (data.status) {
      case FW_UPGRADE_STATUS.SCHEDULED:
        progressPercentage = 0;
        statusClass = FW_UPGRADE_CSS_CLASSES.SCHEDULED;
        showPercentageText = false;
        break;
      case FW_UPGRADE_STATUS.SUCCESS:
        progressPercentage = 100;
        statusClass = FW_UPGRADE_CSS_CLASSES.COMPLETED_SUCCESSFULLY;
        showPercentageText = true;
        break;
      case FW_UPGRADE_STATUS.CANCELLED:
        progressPercentage = 100;
        statusClass = FW_UPGRADE_CSS_CLASSES.CANCELLED;
        showPercentageText = false;
        break;
      case FW_UPGRADE_STATUS.FAILED: {
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
        break;
      }
    }
    let segments = getBatchStatusSegments(data);
    let progressHtml;
    let legendHtml = "";
    if (segments.length > 0) {
      progressHtml = renderSegmentedProgressBar(segments, data.total);
      legendHtml = renderProgressLegend(segments);
    } else {
      // Fall back to a single color when per-status counts are not available
      progressHtml = `
        <div class="upgrade-progress-bar">
          <div class="upgrade-progress-fill ${escapeHtml(statusClass)}"
               style="width: ${escapeHtml(String(progressPercentage))}%">
          </div>
        </div>
      `;
    }
    if (showPercentageText) {
      progressHtml += `<span class="upgrade-progress-text">
        ${escapeHtml(String(progressPercentage))}%
      </span>`;
    }
    mainProgressElement.html(progressHtml + legendHtml);
  }
  // Update completion information in the admin form if available
  if (data.total !== undefined && data.completed !== undefined) {
    let completedInfo = $(".field-completed .readonly");
    if (completedInfo.length > 0) {
      let pending = data.pending !== undefined ? data.pending : 0;
      if (pending > 0) {
        completedInfo.text(
          gettext("%(completed)s complete, %(pending)s pending")
            .replace("%(completed)s", data.completed)
            .replace("%(pending)s", pending),
        );
      } else {
        completedInfo.text(
          gettext("%(completed)s out of %(total)s")
            .replace("%(completed)s", data.completed)
            .replace("%(total)s", data.total),
        );
      }
    }
  }

  let statusField = $(".field-status .readonly");
  if (statusField.length > 0 && data.status) {
    let displayStatus = data.status;
    switch (data.status) {
      case FW_UPGRADE_STATUS.SUCCESS:
        displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_SUCCESSFULLY;
        break;
      case FW_UPGRADE_STATUS.CANCELLED:
        displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_CANCELLATIONS;
        break;
      case FW_UPGRADE_STATUS.FAILED:
        displayStatus = FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_FAILURES;
        break;
      case FW_UPGRADE_STATUS.IN_PROGRESS:
        displayStatus = FW_UPGRADE_DISPLAY_STATUS.IN_PROGRESS;
        break;
      case FW_UPGRADE_STATUS.SCHEDULED:
        displayStatus = FW_UPGRADE_DISPLAY_STATUS.SCHEDULED;
        break;
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

function getBatchStatusSegments(data) {
  // Returns one segment per finished status with at least one operation,
  // or an empty list if the message does not include per-status counts.
  if (!(data.total > 0)) {
    return [];
  }
  let successful = data.successful || 0;
  let failed = data.failed || 0;
  let aborted = data.aborted || 0;
  let cancelled = data.cancelled || 0;
  let segments = [
    {
      count: successful,
      cssClass: FW_UPGRADE_CSS_CLASSES.SUCCESS,
      label: ngettext("%s successful", "%s successful", successful),
    },
    {
      count: failed,
      cssClass: FW_UPGRADE_CSS_CLASSES.FAILED,
      label: ngettext("%s failed", "%s failed", failed),
    },
    {
      count: aborted,
      cssClass: FW_UPGRADE_CSS_CLASSES.ABORTED,
      label: ngettext("%s aborted", "%s aborted", aborted),
    },
    {
      count: cancelled,
      cssClass: FW_UPGRADE_CSS_CLASSES.CANCELLED,
      label: ngettext("%s cancelled", "%s cancelled", cancelled),
    },
  ];
  return segments.filter(function (segment) {
    return segment.count > 0;
  });
}

function renderSegmentedProgressBar(segments, total) {
  // Widths are computed from the counts rather than the rounded percentage
  // shown as text, otherwise a nearly finished batch (e.g. 199 of 200) would
  // render a full bar. Cumulative positions are rounded to hundredths of a
  // percent, so the segments add up exactly to the finished share.
  // Very small segments keep a minimum width in CSS so they stay visible.
  let cumulativeCount = 0;
  let usedWidth = 0;
  let segmentsHtml = segments
    .map(function (segment) {
      cumulativeCount += segment.count;
      let cumulativeWidth = Math.round((cumulativeCount / total) * 10000);
      let width = (cumulativeWidth - usedWidth) / 100;
      usedWidth = cumulativeWidth;
      return `<div class="upgrade-progress-fill ${escapeHtml(segment.cssClass)}"
                   style="width: ${escapeHtml(String(width))}%"></div>`;
    })
    .join("");
  return `<div class="upgrade-progress-bar segmented">${segmentsHtml}</div>`;
}

function renderProgressLegend(segments) {
  let items = segments
    .map(function (segment) {
      return `<span class="legend-item">
          <span class="legend-dot ${escapeHtml(segment.cssClass)}"></span>
          ${escapeHtml(interpolate(segment.label, [segment.count]))}
        </span>`;
    })
    .join("");
  return `<div class="batch-progress-legend">${items}</div>`;
}

function snapshotMayAddRows($) {
  let params = new URLSearchParams(window.location.search);
  let filtered =
    params.has("status") ||
    params.has("organization") ||
    params.has("q") ||
    params.has("page");
  let paginated = $(".pagination").length > 0;
  return !filtered && !paginated;
}

function updateBatchOperationProgress(data, allowAdd = true) {
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
      if ("retry_count" in data) {
        row.find("td.retry-count-cell").text(data.retry_count);
      }
      if ("next_retry_at" in data) {
        let nextRetry =
          data.status === "pending" && data.next_retry_at
            ? getFormattedDateTimeString(data.next_retry_at)
            : "";
        row.find("td.next-retry-cell").text(nextRetry);
      }
      if ("modified" in data && data.modified) {
        row
          .find("td.last-updated-cell")
          .text(getFormattedDateTimeString(data.modified));
      }
    }
  });
  if (!found && allowAdd) {
    addNewOperationRow(data);
  }
}

function addNewOperationRow(data) {
  let $ = django.jQuery;
  if (!data.device_name || !data.device_id) {
    return;
  }
  let tbody = $("#result_list tbody");
  tbody.find("tr td[colspan]").parent().remove();
  let existingRows = tbody.find("tr").length;
  let rowClass = existingRows % 2 === 0 ? "row1" : "row2";
  let deviceUrl = owDeviceUpgradeOperationUrl.replace(
    "00000000-0000-0000-0000-000000000000",
    data.operation_id,
  );
  let imageDisplay = data.image_name || gettext("None");
  let modifiedTime = data.modified
    ? getFormattedDateTimeString(data.modified)
    : gettext("Just now");
  // Build row using DOM attributes to prevent XSS vulnerability due to string interpolation
  let $row = $("<tr>").addClass(rowClass);
  let $deviceTd = $("<td>");
  let $link = $("<a>")
    .addClass("device-link")
    .attr("href", deviceUrl)
    .attr("aria-label", gettext("View upgrade operation for") + " " + data.device_name)
    .text(data.device_name);
  $deviceTd.append($link);
  let $statusTd = $("<td>")
    .addClass("status-cell")
    .attr("data-operation-id", data.operation_id);
  let $statusContent = $("<div>").addClass("status-content").text(data.status); // SAFE
  $statusTd.append($statusContent);
  let $imageTd = $("<td>").text(imageDisplay);
  $row.append($deviceTd, $statusTd, $imageTd);
  // add the retry columns present in the header, if any
  let extraColumns = $("#result_list thead th").length - 4;
  if (extraColumns >= 1) {
    $row.append(
      $("<td>")
        .addClass("retry-count-cell")
        .text(data.retry_count != null ? data.retry_count : ""),
    );
  }
  if (extraColumns >= 2) {
    let nextRetry =
      data.status === "pending" && data.next_retry_at
        ? getFormattedDateTimeString(data.next_retry_at)
        : "";
    $row.append($("<td>").addClass("next-retry-cell").text(nextRetry));
  }
  $row.append($("<td>").addClass("last-updated-cell").text(modifiedTime));
  tbody.append($row);

  let operation = {
    status: data.status,
    id: data.operation_id,
    progress: data.progress,
  };
  renderOperationProgressBarInCell($statusTd, operation);
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
    if (!statusField.find(".batch-main-progress").length) {
      statusField.append('<div class="batch-main-progress"></div>');
    }
    // Apply the batch state included in the page by the server, the same
    // snapshot the websocket sends, so both render an identical bar.
    let progressData = document.getElementById("batch-progress-data");
    if (progressData) {
      updateBatchProgress(JSON.parse(progressData.textContent));
    }
  }
}
