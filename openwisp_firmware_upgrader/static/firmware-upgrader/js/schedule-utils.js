"use strict";

/** Return the browser's IANA timezone, or "" to request server-time interpretation. */
function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (error) {
    return "";
  }
}

/** Keep the schedule's timezone explanation consistent with backend interpretation. */
function labelScheduleTimezone(container, browserTimezone) {
  const serverTimezone = container.data("server-tz") || "";
  let text;
  if (browserTimezone) {
    // These inputs are interpreted in the submitted browser timezone, not the
    // server timezone. Django's usual server-offset warning would be misleading.
    django.jQuery("body").removeAttr("data-admin-utc-offset");
    text = interpolate(gettext("Entered in your timezone (%s)."), [browserTimezone]);
    if (serverTimezone) {
      text += " " + interpolate(gettext("The server runs in %s."), [serverTimezone]);
    }
  } else {
    // An empty scheduled_at_tz makes the backend use its current timezone.
    text = interpolate(gettext("Entered in the server timezone (%s)."), [
      serverTimezone,
    ]);
  }
  container.find(".ow-schedule-tz-note").text(text);
}
