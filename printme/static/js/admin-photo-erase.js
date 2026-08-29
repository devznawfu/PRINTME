// Wires every "Erase" trigger (job cards, the flagged-job review page)
// to the shared erase dialog (photo-erase.js). Simpler than
// admin-photo-crop.js's equivalent wiring - openEraseDialog() takes a
// plain image URL directly, no blob-fetch dance needed, since the
// dialog just sets img.src itself.
(function () {
  if (!window.PrintmePhotoErase) return;

  document.querySelectorAll("[data-erase-trigger]").forEach((btn) => {
    const jobId = btn.dataset.jobId;
    const imageUrl = btn.dataset.processedImageUrl;
    const form = document.getElementById(`erase-form-${jobId}`);
    if (!form) return;
    const strokesField = form.querySelector("[data-erase-strokes-field]");

    btn.addEventListener("click", () => {
      window.PrintmePhotoErase.openEraseDialog({
        imageUrl,
        onSave: (payload) => {
          strokesField.value = payload;
          form.submit();
        },
      });
    });
  });
})();
