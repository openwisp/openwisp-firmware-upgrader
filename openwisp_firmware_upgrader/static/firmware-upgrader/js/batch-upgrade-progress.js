"use strict";

(function() {
  function initBatchUpgrade() {
    console.log("Initializing batch upgrade progress...");
    
    var $ = window.jQuery || window.$ || (window.django && window.django.jQuery);
    
    if (!$) {
      console.log("jQuery not available yet, retrying...");
      setTimeout(initBatchUpgrade, 50);
      return;
    }
    
    console.log("jQuery available, proceeding with initialization");
    
    // Get batch ID from URL
    const batchId = getBatchIdFromUrl();
    console.log("Extracted batch ID:", batchId);
    
    if (!batchId) {
      console.warn("No batch ID found in URL");
      return;
    }

    // Initialize existing upgrade operations with progress bars
    console.log("Initializing existing operations...");
    initializeExistingOperations($);

    // Set up WebSocket connection for real-time updates
    console.log("Setting up WebSocket connection for batch:", batchId);
    setupBatchUpgradeWebSocket(batchId, $);
  }

  // Try to initialize when document is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBatchUpgrade);
  } else {
    // DOM is already loaded
    initBatchUpgrade();
  }
})();

function getBatchIdFromUrl() {
  const pathParts = window.location.pathname.split('/');
  const batchUpgradeIndex = pathParts.indexOf('batchupgradeoperation');
  if (batchUpgradeIndex !== -1 && batchUpgradeIndex + 1 < pathParts.length) {
    const batchId = pathParts[batchUpgradeIndex + 1];
    return batchId;
  }
  
  return null;
}

function setupBatchUpgradeWebSocket(batchId, $) {
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

  if (!wsHost) {
    console.error("Could not determine WebSocket host");
    return;
  }

  const wsUrl = `${getWebSocketProtocol()}${wsHost}/ws/batch-upgrade/${batchId}/`;
  console.log("WebSocket URL:", wsUrl);
  
  const batchWebSocket = new ReconnectingWebSocket(wsUrl, null, {
    automaticOpen: false,
    timeoutInterval: 7000,
    maxRetries: 5,
    retryInterval: 3000,
  });

  initBatchWebSocketHandlers($, batchWebSocket);
}

function initBatchWebSocketHandlers($, websocket) {
  websocket.addEventListener("open", function (e) {
    console.log("Batch upgrade WebSocket connected successfully");
  });

  websocket.addEventListener("close", function (e) {
    console.log("Batch upgrade WebSocket closed with code:", e.code);
    if (e.code === 1006) {
      console.error("Batch upgrade WebSocket closed unexpectedly");
    }
  });

  websocket.addEventListener("error", function (e) {
    console.error("Batch upgrade WebSocket error occurred", e);
  });

  websocket.addEventListener("message", function (e) {
    try {
      const data = JSON.parse(e.data);
      console.log("Received WebSocket message:", data);
      
      if (data.type === "batch_status") {
        console.log("Processing batch status update:", data);
        updateBatchStatus(data, $);
      } else if (data.type === "operation_progress") {
        console.log("Processing operation progress update:", data);
        updateOperationProgress(data, $);
      } else {
        console.log("Unknown message type:", data.type);
      }
    } catch (error) {
      console.error("Error parsing batch WebSocket message:", error, "Raw data:", e.data);
    }
  });
  
  websocket.open();
}

function updateBatchStatus(data, $) {
  $ = $ || window.jQuery || window.$ || (window.django && window.django.jQuery);
  
  updateBatchMetrics(data, $);
  updateMainStatusField(data, $);
}



function updateBatchMetrics(data, $) {
  $ = $ || window.jQuery || window.$ || (window.django && window.django.jQuery);
  
  // Update rates in the form fields if they exist
  if (data.success_rate !== undefined) {
    $('.field-success_rate .readonly').text(`${data.success_rate}%`);
  }
  if (data.failed_rate !== undefined) {
    $('.field-failed_rate .readonly').text(`${data.failed_rate}%`);
  }
  if (data.aborted_rate !== undefined) {
    $('.field-aborted_rate .readonly').text(`${data.aborted_rate}%`);
  }
  if (data.progress_report !== undefined) {
    $('.field-completed .readonly').text(data.progress_report);
  }
}



function updateOperationStatusCell(statusCell, status, progress, $) {
  $ = $ || window.jQuery || window.$ || (window.django && window.django.jQuery);
  
  let progressClass = status.replace(/\s+/g, "-");
  let percentage = progress;
  
  // Calculate percentage based on status if progress not provided
  if (status === "success") {
    percentage = 100;
  } else if (status === "failed" || status === "aborted") {
    percentage = Math.max(progress, 0);
  } else if (status === "in-progress") {
    percentage = Math.max(progress, 5);
  } else {
    percentage = 0;
  }

  const statusHtml = `
    <div class="operation-status-container">
      <div class="operation-status-bar">
        <div class="operation-status-fill ${progressClass}" style="width: ${percentage}%"></div>
      </div>
    </div>
  `;

  statusCell.html(statusHtml);
}

function initializeExistingOperations($) {
  console.log("Initializing existing operations...");
  
  // Initialize progress bars for existing operations that are already in the table
  const tableRows = $('#result_list tbody tr[data-operation-id]');
  
  console.log("Found", tableRows.length, "existing operation rows to initialize");
  
  if (tableRows.length === 0) {
    console.log("No existing operations found in table - this is normal for new batch operations");
    return;
  }
  
  tableRows.each(function() {
    const row = $(this);
    const operationId = row.attr('data-operation-id');
    const statusCell = row.find('td:nth-child(2)'); // Status column
    const statusText = statusCell.text().trim();
    
    console.log(`Initializing operation ${operationId} with status: ${statusText}`);
    
    if (statusText && statusText !== '-') {
      statusCell.addClass('status-cell');
      updateOperationStatusCell(statusCell, statusText, 0, $);
      console.log(`Initialized progress bar for operation ${operationId}`);
    }
  });

  // Initialize the main status field with progress bar
  initializeMainStatusField($);
}

function initializeMainStatusField($) {
  // Try multiple selectors to find the Django admin status field
  let mainStatusField = $('.field-status .readonly');
  if (mainStatusField.length === 0) {
    mainStatusField = $('.form-row.field-status .readonly');
  }
  if (mainStatusField.length === 0) {
    mainStatusField = $('div:contains("Status:") + div, div:contains("Status:") .readonly');
  }
  
  console.log("Found main status field:", mainStatusField.length);
  
  if (mainStatusField.length > 0) {
    const statusText = mainStatusField.text().trim();
    console.log("Main status text:", statusText);
    
    if (statusText && statusText !== '-') {
      // Determine initial progress based on status
      let initialProgress = 0;
      if (statusText.includes('completed successfully') || statusText.includes('success')) {
        initialProgress = 100;
      } else if (statusText.includes('completed with some failures') || statusText.includes('failed')) {
        initialProgress = 100;
      } else if (statusText.includes('in progress') || statusText.includes('in-progress')) {
        // For in-progress, calculate from completed operations
        const completedField = $('.field-completed .readonly');
        if (completedField.length > 0) {
          const completedText = completedField.text().trim();
          // Extract numbers from text like "5 out of 10"
          const match = completedText.match(/(\d+)\s+out\s+of\s+(\d+)/);
          if (match) {
            const completed = parseInt(match[1]);
            const total = parseInt(match[2]);
            initialProgress = Math.round((completed / total) * 100);
          }
        }
      }
      
      // Create progress bar with appropriate initial value
      let progressClass = statusText.replace(/\s+/g, "-");
      
      if (!mainStatusField.find(".upgrade-status-container").length) {
        mainStatusField.empty();
        mainStatusField.append('<div class="upgrade-status-container"></div>');
      }

      let statusContainer = mainStatusField.find(".upgrade-status-container");
      
      // Get completed/total info for display
      let progressText = `${initialProgress}%`;
      const completedField = $('.field-completed .readonly');
      if (completedField.length > 0) {
        const completedText = completedField.text().trim();
        const match = completedText.match(/(\d+)\s+out\s+of\s+(\d+)/);
        if (match) {
          progressText = `${initialProgress}% (${match[1]}/${match[2]})`;
        }
      }
      
      let statusHtml = `
        <span class="upgrade-status-${progressClass}">${statusText}</span>
        <div class="upgrade-progress-bar">
          <div class="upgrade-progress-fill ${progressClass}" style="width: ${initialProgress}%"></div>
        </div>
        <span class="upgrade-progress-text">${progressText}</span>
      `;

      statusContainer.html(statusHtml);
      console.log(`Initialized main status progress bar with ${initialProgress}% progress`);
    }
  }
}

function updateOperationProgress(data, $) {
  // Update individual operation progress in the table for existing devices
  $ = $ || window.jQuery || window.$ || (window.django && window.django.jQuery);
  const operationId = data.operation_id;
  const status = data.status;
  const progress = data.progress || 0;
  
  console.log(`Updating progress for operation ${operationId}: ${status} (${progress}%)`);
  
  // Find the existing row for this operation and update its status
  const operationRow = $(`#result_list tbody tr[data-operation-id="${operationId}"]`);
  
  if (operationRow.length === 0) {
    console.log(`Operation row not found for ID: ${operationId}`);
    return;
  }
  
  console.log(`Found operation row, updating status to: ${status}`);
  
  const statusCell = operationRow.find('td:nth-child(2)'); // Status column
  if (!statusCell.hasClass('status-cell')) {
    statusCell.addClass('status-cell');
  }
  
  updateOperationStatusCell(statusCell, status, progress, $);
  
  operationRow.addClass('operation-updated');
  setTimeout(() => {
    operationRow.removeClass('operation-updated');
  }, 1000);
  
}

function getWebSocketProtocol() {
  let protocol = "ws://";
  if (window.location.protocol === "https:") {
    protocol = "wss://";
  }
  return protocol;
}

function updateMainStatusField(data, $) {
  $ = $ || window.jQuery || window.$ || (window.django && window.django.jQuery);

  let statusField = $('.field-status .readonly');
  if (statusField.length === 0) {
    statusField = $('.form-row.field-status .readonly');
  }
  if (statusField.length === 0) {
    statusField = $('div:contains("Status:") + div, div:contains("Status:") .readonly');
  }
  
  if (statusField.length > 0) {
    const completed = data.completed || 0;
    const total = data.total || 1;
    let percentage = Math.round((completed / total) * 100);
    
    // Ensure progress stays at 100% when batch is completed
    if (data.status === "success" || data.status === "failed") {
      percentage = 100;
    }
    
    const currentProgressText = statusField.find('.upgrade-progress-text').text();
    if (currentProgressText && percentage < 100 && data.status !== "in-progress") {
      // Extract current percentage from text like "85% (17/20)"
      const match = currentProgressText.match(/(\d+)%/);
      const currentPercent = match ? parseInt(match[1]) : 0;
      if (currentPercent > percentage) {
        percentage = currentPercent;
      }
    }
    
    let progressClass = data.status.replace(/\s+/g, "-");

    if (!statusField.find(".upgrade-status-container").length) {
      statusField.empty();
      statusField.append('<div class="upgrade-status-container"></div>');
    }

    let statusContainer = statusField.find(".upgrade-status-container");

    let statusHtml = `
      <span class="upgrade-status-${progressClass}">${data.status}</span>
      <div class="upgrade-progress-bar">
        <div class="upgrade-progress-fill ${progressClass}" style="width: ${percentage}%"></div>
      </div>
      <span class="upgrade-progress-text">${percentage}% (${completed}/${total})</span>
    `;

    statusContainer.html(statusHtml);
  }
}

 