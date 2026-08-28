// Auto-refresh for the admin dashboard: staff shouldn't have to
// manually reload to see a new job arrive. Polls a cheap fingerprint
// endpoint (job count + latest update time) instead of blindly
// reloading on a timer - a reload only fires when something actually
// changed, and never while a <dialog> is open (crop, print-confirm),
// so an admin mid-action isn't yanked away. If the fingerprint changed
// while a dialog was open, the reload is simply deferred to the next
// poll, once nothing is open.
(function () {
  const POLL_INTERVAL_MS = 5000;
  let lastFingerprint = null;

  function anyDialogOpen() {
    return Array.from(document.querySelectorAll("dialog")).some((d) => d.open);
  }

  function poll() {
    fetch("/admin/status", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        const fingerprint = `${data.count}:${data.latest}`;

        if (lastFingerprint === null) {
          lastFingerprint = fingerprint;
          return;
        }
        if (fingerprint === lastFingerprint) return;
        if (anyDialogOpen()) return; // try again next poll, once free

        location.reload();
      })
      .catch(() => {});
  }

  setInterval(poll, POLL_INTERVAL_MS);
})();
