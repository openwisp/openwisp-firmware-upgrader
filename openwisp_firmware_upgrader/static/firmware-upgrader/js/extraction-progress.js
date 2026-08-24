"use strict";

(function () {
  var TERMINAL_STATUSES = ["success", "failed", "manually_confirmed", "invalid"];

  var imageId = typeof owFirmwareImageId !== "undefined" ? owFirmwareImageId : null;
  if (!imageId) {
    return;
  }

  var currentStatus =
    typeof owFirmwareExtractionStatus !== "undefined"
      ? owFirmwareExtractionStatus
      : null;
  if (currentStatus && TERMINAL_STATUSES.indexOf(currentStatus) !== -1) {
    return;
  }

  var wsHost =
    typeof owFirmwareUpgraderApiHost !== "undefined" && owFirmwareUpgraderApiHost.host;
  if (!wsHost) {
    return;
  }

  var protocol = location.protocol === "https:" ? "wss://" : "ws://";
  var wsUrl =
    protocol + wsHost + "/ws/firmware-upgrader/firmware-image/" + imageId + "/";

  var ws = new ReconnectingWebSocket(wsUrl, null, {
    automaticOpen: false,
    timeoutInterval: 7000,
    maxReconnectAttempts: 5,
    reconnectInterval: 3000,
  });

  ws.addEventListener("open", function () {
    ws.send(JSON.stringify({ type: "request_current_state" }));
  });

  ws.addEventListener("message", function (e) {
    try {
      var data = JSON.parse(e.data);
      if (
        data.type === "extraction_status" &&
        TERMINAL_STATUSES.indexOf(data.extraction_status) !== -1
      ) {
        ws.close();
        window.location.reload();
      }
    } catch (error) {
      console.error("Error parsing WebSocket message:", error);
    }
  });

  ws.addEventListener("error", function (e) {
    console.error("WebSocket error occurred", e);
  });
  window.extractionStatusWebSocket = ws;
  ws.open();
})();
