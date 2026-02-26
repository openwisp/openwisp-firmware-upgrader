"use strict";

// Core firmware upgrade statuses
const FW_UPGRADE_STATUS = {
  SUCCESS: "success",
  FAILED: "failed",
  ABORTED: "aborted",
  CANCELLED: "cancelled",
  IN_PROGRESS: "in-progress",
};

// Display statuses
const FW_UPGRADE_DISPLAY_STATUS = {
  SUCCESS: gettext("success"),
  FAILED: gettext("failed"),
  ABORTED: gettext("aborted"),
  CANCELLED: gettext("cancelled"),
  IN_PROGRESS: gettext("in progress"),
  COMPLETED_SUCCESSFULLY: gettext("completed successfully"),
  COMPLETED_WITH_FAILURES: gettext("completed with some failures"),
  COMPLETED_WITH_CANCELLATIONS: gettext("completed with some cancellations"),
};

// CSS class names
const FW_UPGRADE_CSS_CLASSES = {
  COMPLETED_SUCCESSFULLY: "completed-successfully",
  PARTIAL_SUCCESS: "partial-success",
  CANCELLED: "cancelled",
  FAILED: "failed",
  IN_PROGRESS: "in-progress",
  SUCCESS: "success",
  ABORTED: "aborted",
};

const VALID_FW_STATUSES = new Set(Object.values(FW_UPGRADE_STATUS));

// For rendering checks (from HTML display values): include both backend and display statuses
const ALL_VALID_FW_STATUSES = new Set([
  ...Object.values(FW_UPGRADE_STATUS),
  ...Object.values(FW_UPGRADE_DISPLAY_STATUS),
]);

// Status groups for easier conditional checking
const FW_STATUS_GROUPS = {
  COMPLETED: new Set([
    FW_UPGRADE_STATUS.SUCCESS,
    FW_UPGRADE_STATUS.FAILED,
    FW_UPGRADE_STATUS.ABORTED,
    FW_UPGRADE_STATUS.CANCELLED,
    FW_UPGRADE_DISPLAY_STATUS.COMPLETED_SUCCESSFULLY,
    FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_FAILURES,
    FW_UPGRADE_DISPLAY_STATUS.COMPLETED_WITH_CANCELLATIONS,
  ]),

  IN_PROGRESS: new Set([
    FW_UPGRADE_STATUS.IN_PROGRESS,
    FW_UPGRADE_DISPLAY_STATUS.IN_PROGRESS,
  ]),

  SUCCESS: new Set([
    FW_UPGRADE_STATUS.SUCCESS,
    FW_UPGRADE_DISPLAY_STATUS.COMPLETED_SUCCESSFULLY,
  ]),

  FAILURE: new Set([
    FW_UPGRADE_STATUS.FAILED,
    FW_UPGRADE_STATUS.ABORTED,
    FW_UPGRADE_STATUS.CANCELLED,
  ]),
};

const FW_STATUS_HELPERS = {
  isValid: (status) => ALL_VALID_FW_STATUSES.has(status),
  isCompleted: (status) => FW_STATUS_GROUPS.COMPLETED.has(status),
  isInProgress: (status) => FW_STATUS_GROUPS.IN_PROGRESS.has(status),
  isSuccess: (status) => FW_STATUS_GROUPS.SUCCESS.has(status),
  isFailure: (status) => FW_STATUS_GROUPS.FAILURE.has(status),
  includesProgress: (status) => status && status.includes("progress"),
};

// Mapping of status to CSS class for progress bars
const STATUS_TO_CSS_CLASS = {
  [FW_UPGRADE_STATUS.IN_PROGRESS]: FW_UPGRADE_CSS_CLASSES.IN_PROGRESS,
  [FW_UPGRADE_STATUS.SUCCESS]: FW_UPGRADE_CSS_CLASSES.SUCCESS,
  [FW_UPGRADE_STATUS.FAILED]: FW_UPGRADE_CSS_CLASSES.FAILED,
  [FW_UPGRADE_STATUS.ABORTED]: FW_UPGRADE_CSS_CLASSES.ABORTED,
  [FW_UPGRADE_STATUS.CANCELLED]: FW_UPGRADE_CSS_CLASSES.CANCELLED,
};

// Statuses that should show 100% progress
const STATUSES_WITH_FULL_PROGRESS = new Set([
  FW_UPGRADE_STATUS.SUCCESS,
  FW_UPGRADE_STATUS.FAILED,
  FW_UPGRADE_STATUS.ABORTED,
  FW_UPGRADE_STATUS.CANCELLED,
]);

// returns the object key of statusMap corresponding to value
function getKeyFromValue(statusMap, value) {
  return Object.keys(statusMap).find((key) => statusMap[key] === value);
}

// Normalize numeric progress input and fallback to sensible defaults.
function normalizeProgress(operationProgress = null, status) {
  if (operationProgress !== null && operationProgress !== undefined) {
    let parsed = parseInt(operationProgress, 10);
    if (isNaN(parsed)) {
      return 0;
    }
    return Math.min(100, Math.max(0, parsed));
  }
  if (FW_STATUS_HELPERS.isCompleted(status)) {
    return 100;
  }
  return 0;
}

// Return progress bar HTML fragment given percentage and CSS class.
function renderProgressBarHtml(
  progressPercentage,
  statusClass,
  showPercentageText = true,
) {
  return `
    <div class="upgrade-progress-bar">
      <div class="upgrade-progress-fill ${statusClass}" style="width: ${progressPercentage}%"></div>
    </div>
    ${showPercentageText ? `<span class="upgrade-progress-text">${progressPercentage}%</span>` : ""}
  `;
}

function getWebSocketProtocol() {
  let protocol = "ws://";
  if (window.location.protocol === "https:") {
    protocol = "wss://";
  }
  return protocol;
}

/**
 * HTML-escape a string to prevent insertion of untrusted content into DOM
 * fragments.
 */
function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) {
    return "";
  }
  unsafe = String(unsafe);
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Return the host portion of the firmware upgrader API host configured
 * by the server.  When the global `owFirmwareUpgraderApiHost` object is
 * missing or does not contain a `host` property we log an error and return
 * null so callers can bail out gracefully.
 */
function getFirmwareUpgraderApiHost() {
  if (
    typeof owFirmwareUpgraderApiHost === "undefined" ||
    !owFirmwareUpgraderApiHost.host
  ) {
    console.error("owFirmwareUpgraderApiHost is not defined or missing host property");
    return null;
  }
  return owFirmwareUpgraderApiHost.host;
}

function getFormattedDateTimeString(dateTimeString) {
  let dateTime = new Date(dateTimeString);
  let locale = window.djangoLocale || "en-us";
  return dateTime.toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function isScrolledToBottom(element) {
  if (!element || !element.length) return false;
  let el = element[0];
  return el.scrollHeight - el.clientHeight <= el.scrollTop + 1;
}

function scrollToBottom(element) {
  if (element && element.length) {
    let el = element[0];
    el.scrollTop = el.scrollHeight - el.clientHeight;
  }
}

if (typeof window !== "undefined") {
  window.FW_UPGRADE_STATUS = FW_UPGRADE_STATUS;
  window.FW_UPGRADE_DISPLAY_STATUS = FW_UPGRADE_DISPLAY_STATUS;
  window.FW_UPGRADE_CSS_CLASSES = FW_UPGRADE_CSS_CLASSES;
  window.VALID_FW_STATUSES = VALID_FW_STATUSES;
  window.VALID_FW_DISPLAY_STATUSES = new Set(Object.values(FW_UPGRADE_DISPLAY_STATUS));
  window.ALL_VALID_FW_STATUSES = ALL_VALID_FW_STATUSES;
  window.FW_STATUS_GROUPS = FW_STATUS_GROUPS;
  window.FW_STATUS_HELPERS = FW_STATUS_HELPERS;
  window.STATUS_TO_CSS_CLASS = STATUS_TO_CSS_CLASS;
  window.STATUSES_WITH_FULL_PROGRESS = STATUSES_WITH_FULL_PROGRESS;
  window.normalizeProgress = normalizeProgress;
  window.renderProgressBarHtml = renderProgressBarHtml;
  window.getWebSocketProtocol = getWebSocketProtocol;
  window.escapeHtml = escapeHtml;
  window.getFirmwareUpgraderApiHost = getFirmwareUpgraderApiHost;
  window.getFormattedDateTimeString = getFormattedDateTimeString;
  window.isScrolledToBottom = isScrolledToBottom;
  window.scrollToBottom = scrollToBottom;
}
