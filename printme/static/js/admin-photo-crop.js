// Wires each photo job card's "Crop photo" button to the shared crop
// dialog (photo-crop.js, also used by the customer upload portal).
// Unlike the upload flow, there's no in-memory File object to hand to
// openCropDialog() here - the photo already lives on the server - so
// the original upload is fetched as a Blob first (a Blob works
// interchangeably with a File for URL.createObjectURL()).
//
// No client-side state is kept between opens: the admin side doesn't
// track what crop (if any) is currently applied, so every open starts
// framed on the whole photo rather than restoring a previous crop -
// an accepted limitation, not an oversight.
(function () {
  if (!window.PrintmePhotoCrop) return;

  document.querySelectorAll("[data-admin-crop-trigger]").forEach((btn) => {
    const jobId = btn.dataset.jobId;
    const imageUrl = btn.dataset.originalImageUrl;
    const form = document.getElementById(`recrop-form-${jobId}`);
    if (!form) return;
    const cropField = form.querySelector("[data-recrop-crop-field]");

    btn.addEventListener("click", () => {
      btn.disabled = true;
      fetch(imageUrl, { credentials: "same-origin" })
        .then((r) => {
          if (!r.ok) throw new Error(`fetching original photo failed: ${r.status}`);
          return r.blob();
        })
        .then((blob) => {
          btn.disabled = false;
          window.PrintmePhotoCrop.openCropDialog({
            file: blob,
            existingCrop: null,
            onSave: (fractions) => {
              cropField.value = JSON.stringify(fractions);
              form.submit();
            },
            onClear: () => {
              cropField.value = "";
              form.submit();
            },
          });
        })
        .catch((err) => {
          btn.disabled = false;
          console.error(err);
          alert("Couldn't load the original photo to crop. Check the browser console for details.");
        });
    });
  });
})();
