"use strict";

var gettext =
  window.gettext ||
  function (word) {
    return word;
  };
var interpolate = interpolate || function () {};

django.jQuery(function ($) {
  const firmwareDeviceId = getObjectIdFromUrl();

  setTimeout(function () {
    if (!firmwareDeviceId) {
      return;
    }

    let upgradeSection = $("#upgradeoperation_set-group");
    if (upgradeSection.length === 0) {
      upgradeSection = $("[id*='upgradeoperation']").closest(".inline-group");
    }

    // Initialize existing upgrade operations with progress bars
    initializeExistingUpgradeOperations($);

    // Debug: Check required variables
    console.log("Debugging WebSocket setup:");
    console.log("firmwareDeviceId:", firmwareDeviceId);
    console.log("owControllerApiHost available:", typeof owControllerApiHost !== "undefined");
    if (typeof owControllerApiHost !== "undefined") {
      console.log("owControllerApiHost:", owControllerApiHost);
      console.log("owControllerApiHost.host:", owControllerApiHost.host);
    } else {
      console.warn("owControllerApiHost is not defined - using fallback host");
    }

    // Determine the host to use for WebSocket connection
    let wsHost = null;
    if (typeof owControllerApiHost !== "undefined" && owControllerApiHost.host) {
      wsHost = owControllerApiHost.host;
      console.log("Using owControllerApiHost.host:", wsHost);
    } else {
      // Fallback to current window location host
      wsHost = window.location.host;
      console.log("Using fallback host from window.location.host:", wsHost);
    }

    if (wsHost && firmwareDeviceId) {
      const wsUrl = `${getWebSocketProtocol()}${wsHost}/ws/firmware-upgrader/device/${firmwareDeviceId}/`;
      
      console.log("WebSocket URL:", wsUrl);
      console.log("WebSocket protocol:", getWebSocketProtocol());
      console.log("Current window.location:", window.location.href);
      
      // Check if ReconnectingWebSocket is available
      if (typeof ReconnectingWebSocket === "undefined") {
        console.error("ReconnectingWebSocket is not defined - check if the library is loaded");
        return;
      }
      
      console.log("Creating ReconnectingWebSocket instance...");
      const upgradeProgressWebSocket = new ReconnectingWebSocket(
        wsUrl,
        null,
        {
          debug: true,  // Enable debug mode for ReconnectingWebSocket
          automaticOpen: false,
          timeoutInterval: 7000,
          maxRetries: 5,
          retryInterval: 3000,
        },
      );
      
      console.log("ReconnectingWebSocket instance created:", upgradeProgressWebSocket);

      // Initialize websocket connection
      initUpgradeProgressWebSockets($, upgradeProgressWebSocket);
      
      // Store reference globally for debugging
      window.debugWebSocket = upgradeProgressWebSocket;
      
      // Add a test function for manual debugging
      window.testWebSocketConnection = function() {
        console.log("Testing WebSocket connection...");
        console.log("WebSocket ready state:", upgradeProgressWebSocket.readyState);
        console.log("WebSocket URL:", upgradeProgressWebSocket.url);
        console.log("Expected device group: firmware_upgrader.device-" + firmwareDeviceId);
        
        // Check if user is authenticated
        console.log("User authentication check:");
        console.log("- Document cookies:", document.cookie);
        console.log("- CSRF token:", document.querySelector('[name=csrfmiddlewaretoken]')?.value);
        
        if (upgradeProgressWebSocket.readyState === WebSocket.OPEN) {
          console.log("✅ WebSocket is connected and ready");
        } else if (upgradeProgressWebSocket.readyState === WebSocket.CONNECTING) {
          console.log("🔄 WebSocket is connecting...");
        } else if (upgradeProgressWebSocket.readyState === WebSocket.CLOSING) {
          console.log("⚠️ WebSocket is closing...");
        } else if (upgradeProgressWebSocket.readyState === WebSocket.CLOSED) {
          console.log("❌ WebSocket is closed");
        }
        
        // Test if the connection stays open by sending a ping
        if (upgradeProgressWebSocket.readyState === WebSocket.OPEN) {
          console.log("Testing connection stability...");
          // Note: ReconnectingWebSocket might not support ping, but we can try
          try {
            upgradeProgressWebSocket.send('{"type":"ping"}');
            console.log("Ping sent successfully");
          } catch (e) {
            console.log("Ping failed (normal for some WebSocket implementations):", e.message);
          }
        }
      };
      
      // Add a test function to simulate a test message
      window.sendTestWebSocketMessage = function() {
        console.log("Testing if WebSocket can receive messages...");
        // This will test if we can at least receive a test message
        // Note: This is just to test the client-side reception
        const testMessage = {
          model: "UpgradeOperation",
          data: {
            type: "log",
            content: "Test message from JavaScript console",
            status: "in-progress",
            timestamp: new Date().toISOString()
          }
        };
        
        console.log("Simulating WebSocket message reception:", testMessage);
        
        // Create a proper MessageEvent and dispatch it to the WebSocket
        try {
          const messageEvent = new MessageEvent('message', {
            data: JSON.stringify(testMessage),
            origin: window.location.origin,
            source: window
          });
          
          // Dispatch the event to the WebSocket
          upgradeProgressWebSocket.dispatchEvent(messageEvent);
          console.log("Test message dispatched successfully");
        } catch (error) {
          console.error("Error dispatching test message:", error);
          
          // Fallback: manually call the message processing logic
          console.log("Trying fallback method...");
          try {
            const mockEvent = {
              data: JSON.stringify(testMessage)
            };
            
            // Directly call the message processing logic
            console.log("upgradeProgressWebSocket.addEventListener('message') called", mockEvent);
            console.log("Raw message data:", mockEvent.data);
            
            let data = JSON.parse(mockEvent.data);
            console.log("Parsed data:", data);

            // Check if this is an upgrade operation update
            if (data.model !== "UpgradeOperation") {
              console.log("Not an UpgradeOperation, received model:", data.model);
              return;
            }

            data = data.data;
            console.log("Processing UpgradeOperation data:", data);

            // Handle different types of updates
            if (data.type === "operation_update") {
              console.log("Handling operation_update");
              updateUpgradeOperationDisplay(data.operation);
            } else if (data.type === "log") {
              console.log("Handling log update");
              updateUpgradeOperationLog(data);
            } else if (data.type === "status") {
              console.log("Handling status update");
              updateUpgradeOperationStatus(data);
            } else {
              console.log("Unknown data type:", data.type);
            }
            
            console.log("Fallback test message processed successfully");
          } catch (fallbackError) {
            console.error("Error in fallback processing:", fallbackError);
          }
        }
      };
      
      console.log("WebSocket debugging functions available:");
      console.log("- window.testWebSocketConnection() - Test connection status");
      console.log("- window.sendTestWebSocketMessage() - Simulate message reception");
      console.log("- window.debugWebSocket - Direct access to WebSocket instance");
    } else {
      console.error("Cannot initialize WebSocket: missing host or firmwareDeviceId");
      console.error("wsHost:", wsHost);
      console.error("firmwareDeviceId:", firmwareDeviceId);
    }
  }, 500);
});

let upgradeOperationsInitialized = false;

// Store accumulated log content to preserve across WebSocket reconnections
let accumulatedLogContent = new Map(); // operationId -> full log content

function formatLogForDisplay(logContent) {
  // Convert newlines to <br> tags for proper line breaks in HTML
  return logContent ? logContent.replace(/\n/g, '<br>') : '';
}

function requestCurrentOperationState(websocket) {
  // Request current state of any in-progress operations to get full log content
  // This helps when switching tabs where DOM might show truncated logs
  if (websocket.readyState === WebSocket.OPEN) {
    try {
      const requestMessage = {
        type: "request_current_state",
        device_id: getObjectIdFromUrl()
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

  let statusFields = $(
    "#upgradeoperation_set-group .field-status .readonly, .field-status .readonly",
  );

  let processedCount = 0;
  statusFields.each(function (index) {
    let statusField = $(this);
    let statusText = statusField.text().trim();

    // Skip if already has progress bar
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
      let operationId = operationIdInput.length > 0 ? operationIdInput.val() : "unknown";
      
      // Use accumulated log content if available, fallback to DOM content
      let logContent;
      if (accumulatedLogContent.has(operationId)) {
        logContent = accumulatedLogContent.get(operationId);
        
        // Update DOM with accumulated content to ensure UI is in sync
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
  console.log("initUpgradeProgressWebSockets function called");
  
  // Add comprehensive WebSocket event handlers for debugging
  upgradeProgressWebSocket.addEventListener("open", function (e) {
    console.log("WebSocket connection opened successfully", e);
    
    // Reset initialization flag and re-initialize existing operations when WebSocket reconnects
    // This ensures progress bars and logs are properly restored after tab switches
    upgradeOperationsInitialized = false;
    
    // Request current state of in-progress operations from server to get full log content
    setTimeout(function() {
      requestCurrentOperationState(upgradeProgressWebSocket);
      
      // Wait a bit for the server response before initializing with DOM content
      setTimeout(function() {
        initializeExistingUpgradeOperations($, false);
      }, 200);
    }, 100);
  });

  upgradeProgressWebSocket.addEventListener("close", function (e) {
    console.log("WebSocket connection closed", e.code, e.reason, e.wasClean);
    
    // Reset initialization flag when WebSocket closes to ensure clean state
    upgradeOperationsInitialized = false;
    
    if (e.code === 1006) {
      console.error("WebSocket closed abnormally - possible authentication or routing issue");
    } else if (e.code === 1000) {
      console.log("WebSocket closed normally");
    } else {
      console.error("WebSocket closed with error code:", e.code, "reason:", e.reason);
    }
  });

  upgradeProgressWebSocket.addEventListener("error", function (e) {
    console.error("WebSocket error occurred", e);
  });

  upgradeProgressWebSocket.addEventListener("connecting", function (e) {
    console.log("WebSocket connecting...", e);
  });

  upgradeProgressWebSocket.addEventListener("message", function (e) {
    try {
      let data = JSON.parse(e.data);

      // Check if this is an upgrade operation update
      if (data.model !== "UpgradeOperation") {
        return;
      }

      data = data.data;

      // Handle different types of updates
      if (data.type === "operation_update") {
        updateUpgradeOperationDisplay(data.operation);
      } else if (data.type === "log") {
        updateUpgradeOperationLog(data);
      } else if (data.type === "status") {
        updateUpgradeOperationStatus(data);
      }
    } catch (error) {
      console.error("Error parsing WebSocket message:", error, "Raw data:", e.data);
    }
  });

  // Open the WebSocket connection
  console.log("Opening WebSocket connection...");
  upgradeProgressWebSocket.open();
}

function updateUpgradeOperationDisplay(operation) {
  console.log("updateUpgradeOperationDisplay function called", operation);
  let $ = django.jQuery;

  // Find the upgrade operation element by ID
  let operationIdInputField = $(`input[value="${operation.id}"]`);
  if (operationIdInputField.length === 0) {
    if (isUpgradeOperationsAbsent()) {
      location.reload();
    }
    return;
  }

  let operationFieldset = operationIdInputField.parent().children("fieldset");
  let statusField = operationFieldset.find(".field-status .readonly");

  // Store the log content in accumulated storage for future tab switches
  if (operation.log && operation.id) {
    accumulatedLogContent.set(operation.id, operation.log);
  }

  // Update status with progress bar
  updateStatusWithProgressBar(statusField, operation);

  // Update log with scroll-to-bottom behavior
  let logElement = operationFieldset.find(".field-log .readonly");
  let shouldScroll = isScrolledToBottom(logElement);

  if (operation.status === "in-progress") {
    // Show loading indicator for in-progress operations
    logElement.html(
      formatLogForDisplay(operation.log) + '<div class="loader upgrade-progress-loader"></div>',
    );
  } else {
    logElement.html(formatLogForDisplay(operation.log));
    
    // Clean up accumulated content for completed operations to prevent memory leaks
    if (operation.status === "success" || operation.status === "failed" || operation.status === "aborted") {
      accumulatedLogContent.delete(operation.id);
    }
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
  // Get log content to calculate real progress
  let logContent = operation.log || "";
  let progressPercentage = getProgressPercentage(status, logContent);
  let progressClass = status.replace(/\s+/g, "-"); // Replace all spaces with dashes

  // Create status container if it doesn't exist
  if (!statusField.find(".upgrade-status-container").length) {
    statusField.empty();
    statusField.append('<div class="upgrade-status-container"></div>');
  }

  let statusContainer = statusField.find(".upgrade-status-container");

  // Build the status HTML with progress bar
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
}

function getProgressPercentage(status, logContent = "") {
  if (status === "success") {
    return 100;
  } else if (status === "failed" || status === "aborted") {
    // Calculate progress based on how far we got before failing
    return calculateProgressFromLog(logContent);
  } else if (status === "in-progress" || status === "in progress") {
    // Calculate real progress from log content
    return calculateProgressFromLog(logContent);
  }
  return 0;
}

function calculateProgressFromLog(logContent = "") {
  if (!logContent) return 0;

  const upgradeSteps = [
    { keyword: "Connection successful, starting upgrade", progress: 10 },
    { keyword: "Device identity verified successfully", progress: 15 },
    { keyword: "Image checksum file found", progress: 20 },
    { keyword: "Checksum different, proceeding", progress: 25 },
    { keyword: "proceeding with the upload of the new image", progress: 30 },
    { keyword: "upload of the new image", progress: 35 },
    { keyword: "Enough available memory was freed up", progress: 40 },
    { keyword: "Proceeding to upload of the image file", progress: 45 },
    { keyword: "Sysupgrade test passed successfully", progress: 55 },
    { keyword: "proceeding with the upgrade operation", progress: 60 },
    { keyword: "Upgrade operation in progress", progress: 65 },
    { keyword: "SSH connection closed, will wait", progress: 70 },
    { keyword: "seconds before attempting to reconnect", progress: 75 },
    { keyword: "Trying to reconnect to device", progress: 80 },
    { keyword: "Connected! Writing checksum", progress: 90 },
    { keyword: "Upgrade completed successfully", progress: 100 },
  ];

  let currentProgress = 0;

  // Find the highest progress step that has been completed
  for (const step of upgradeSteps) {
    if (logContent.includes(step.keyword)) {
      currentProgress = Math.max(currentProgress, step.progress);
    }
  }

  // If no specific steps found but we're in progress, show at least 5%
  if (currentProgress === 0 && logContent.length > 0) {
    currentProgress = 5;
  }

  return currentProgress;
}

function updateUpgradeOperationLog(logData) {
  let $ = django.jQuery;

  // Find all in-progress operations and update their logs
  $(".field-status .readonly").each(function () {
    let statusField = $(this);
    let currentStatusText =
      statusField.find(".upgrade-status-container span").text() ||
      statusField.text().trim();

    if (
      currentStatusText === "in progress" ||
      currentStatusText === "in-progress"
    ) {
      let operationFieldset = $(this).closest("fieldset");
      let logElement = operationFieldset.find(".field-log .readonly");
      let shouldScroll = isScrolledToBottom(logElement);

      // Get operation ID for storing accumulated content
      let operationIdInput = operationFieldset.find("input[name*='id'][value]");
      let operationId = operationIdInput.length > 0 ? operationIdInput.val() : "unknown";

      // Get current log content - use accumulated content if available, fallback to DOM
      let currentLog;
      if (accumulatedLogContent.has(operationId)) {
        currentLog = accumulatedLogContent.get(operationId);
      } else {
        currentLog = logElement.text().replace(/\s*$/, ""); // Remove trailing whitespace
      }

      // Append new log line
      let newLog = currentLog
        ? currentLog + "\n" + logData.content
        : logData.content;
      
      // Store accumulated content in memory
      accumulatedLogContent.set(operationId, newLog);
      
      logElement.html(
        formatLogForDisplay(newLog) + '<div class="loader upgrade-progress-loader"></div>',
      );

      // Update progress bar with new log content
      let operation = {
        status: "in-progress",
        log: newLog,
        id: operationId,
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
  $(".field-status .readonly").each(function () {
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

      // Create operation object for updateStatusWithProgressBar
      let operation = {
        status: statusData.status,
        log: logContent,
        id: null,
      };

      updateStatusWithProgressBar(statusField, operation);

      // Remove loader if operation completed
      if (statusData.status !== "in-progress") {
        logElement.find(".upgrade-progress-loader").remove();
      }
    }
  });
}

function getStatusColor(status) {
  switch (status) {
    case "success":
      return "#bbffbb";
    case "failed":
      return "#ff949461";
    case "aborted":
      return "#ffcc99";
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
