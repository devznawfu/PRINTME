// Wires each photo job card's thumbnail to a shared enlarge dialog -
// same native <dialog> + .showModal() pattern as print-confirm.js and
// photo-crop.js. Reuses the existing crop trigger already on the card
// (data-admin-crop-trigger) rather than duplicating a crop entry point,
// so window.PrintmePhotoCrop stays the app's only intentional global.
(function () {
  const dialog = document.getElementById("photo-preview-dialog");
  if (!dialog) return;

  const img = dialog.querySelector("[data-preview-image]");
  const titleEl = dialog.querySelector("[data-preview-title]");
  const cropBtn = dialog.querySelector("[data-preview-crop-btn]");
  const closeBtn = dialog.querySelector("[data-preview-close-btn]");
  let activeJobId = null;

  document.querySelectorAll("[data-photo-preview]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeJobId = btn.dataset.jobId;
      // Cache-bust: the crop tool rewrites the processed file in place,
      // so a browser-cached enlarge image would show stale content -
      // the same reason admin_review.thumb serves with max_age=0.
      img.src = `/admin/jobs/${activeJobId}/thumb.png?t=${Date.now()}`;
      titleEl.innerHTML = btn.dataset.previewTitle || "";
      dialog.showModal();
    });
  });

  cropBtn.addEventListener("click", () => {
    dialog.close();
    const trigger = document.querySelector(
      `[data-admin-crop-trigger][data-job-id="${activeJobId}"]`
    );
    if (trigger) trigger.click();
  });
  closeBtn.addEventListener("click", () => dialog.close());
})();
