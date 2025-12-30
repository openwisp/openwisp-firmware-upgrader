"use strict";

// Core firmware upgrade statuses
const FW_UPGRADE_STATUS = {
  SUCCESS: "success",
  FAILED: "failed",
  ABORTED: "aborted",
  CANCELLED: "cancelled",
  IN_PROGRESS: "in-progress",
  IN_PROGRESS_ALT: "in progress", // Alternative representation
};

// Display statuses
const FW_UPGRADE_DISPLAY_STATUS = {
  COMPLETED_SUCCESSFULLY: gettext("completed successfully"),
  COMPLETED_WITH_FAILURES: gettext("completed with some failures"),
  COMPLETED_WITH_CANCELLATIONS: gettext("completed with some cancellations"),
  IN_PROGRESS: gettext("in progress"),
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
const VALID_FW_DISPLAY_STATUSES = new Set(Object.values(FW_UPGRADE_DISPLAY_STATUS));

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
    FW_UPGRADE_STATUS.IN_PROGRESS_ALT,
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

if (typeof window !== "undefined") {
  window.FW_UPGRADE_STATUS = FW_UPGRADE_STATUS;
  window.FW_UPGRADE_DISPLAY_STATUS = FW_UPGRADE_DISPLAY_STATUS;
  window.FW_UPGRADE_CSS_CLASSES = FW_UPGRADE_CSS_CLASSES;
  window.VALID_FW_STATUSES = VALID_FW_STATUSES;
  window.VALID_FW_DISPLAY_STATUSES = VALID_FW_DISPLAY_STATUSES;
  window.ALL_VALID_FW_STATUSES = ALL_VALID_FW_STATUSES;
  window.FW_STATUS_GROUPS = FW_STATUS_GROUPS;
  window.FW_STATUS_HELPERS = FW_STATUS_HELPERS;
}
