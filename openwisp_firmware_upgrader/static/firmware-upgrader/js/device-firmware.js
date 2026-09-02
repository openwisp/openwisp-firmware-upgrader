"use strict";

django.jQuery(function ($) {
  function updateImageMetadataDisplay(imageId) {
    var metadata = (window.owDeviceFirmwareImageMetadata || {})[imageId];
    $("#devicefirmware-0 .field-image_target_display .readonly").text(
      metadata ? metadata.target || "-" : "-",
    );
    $("#devicefirmware-0 .field-image_fw_version_display .readonly").text(
      metadata ? metadata.fw_version || "-" : "-",
    );
  }

  $("#devicefirmware-group").on(
    "change",
    "#id_devicefirmware-0-image",
    function (event) {
      updateImageMetadataDisplay($(event.target).val());
    },
  );

  if (firmwareUpgraderSchema === null) {
    return;
  }
  var firmwareImageChanged = false;
  if (
    $("#id_devicefirmware-0-upgrade_options").val() &&
    $("#id_devicefirmware-0-upgrade_options").val() !== "null"
  ) {
    firmwareImageChanged = true;
  }
  $("#devicefirmware-group").on(
    "change",
    "#id_devicefirmware-0-image",
    function (event) {
      if (!$(event.target).val()) {
        $("#id_devicefirmware-0-upgrade_options_jsoneditor").hide();
        return;
      }
      $("#id_devicefirmware-0-upgrade_options_jsoneditor").show();
      if (firmwareImageChanged) {
        django._loadJsonSchemaUi(
          $("#id_devicefirmware-0-upgrade_options").get(0),
          false,
          firmwareUpgraderSchema,
          true,
        );
      } else {
        firmwareImageChanged = true;
      }
    },
  );
  $("#devicefirmware-group .add-row a").click(function () {
    firmwareImageChanged = true;
  });
});
