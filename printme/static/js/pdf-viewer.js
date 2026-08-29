// Swipeable full-page PDF viewer, driven by an already-loaded pdf.js
// document (upload-form.js owns loading/caching one per file via
// pdf-preview.js, so this never re-parses the same PDF the file row's
// thumbnail already loaded). Own module - a page-navigation dialog has
// nothing in common with the small-thumbnail rendering pdf-preview.js
// wraps, beyond both eventually calling the same renderPageToCanvas().
(function () {
  const dialog = document.getElementById("pdf-viewer-dialog");
  if (!dialog || !window.PrintmePdfPreview) return;

  const filenameEl = dialog.querySelector("[data-pdf-viewer-filename]");
  const canvas = dialog.querySelector("[data-pdf-viewer-canvas]");
  const stage = dialog.querySelector("[data-pdf-viewer-stage]");
  const pageLabelEl = dialog.querySelector("[data-pdf-viewer-page-label]");
  const prevBtn = dialog.querySelector("[data-pdf-viewer-prev]");
  const nextBtn = dialog.querySelector("[data-pdf-viewer-next]");
  const closeBtn = dialog.querySelector("[data-pdf-viewer-close-btn]");

  let pdfDoc = null;
  let currentPage = 1;
  let renderToken = 0;

  async function showPage(n) {
    if (!pdfDoc || n < 1 || n > pdfDoc.numPages) return;
    currentPage = n;
    pageLabelEl.textContent = `Page ${currentPage} of ${pdfDoc.numPages}`;
    prevBtn.disabled = currentPage === 1;
    nextBtn.disabled = currentPage === pdfDoc.numPages;

    // A fast swipe through several pages shouldn't leave slower earlier
    // renders finishing (and overwriting the canvas) after a later one -
    // only the most recently requested render is allowed to draw.
    const token = ++renderToken;
    const longEdge = Math.max(stage.clientWidth, stage.clientHeight, 600);
    await window.PrintmePdfPreview.renderPageToCanvas(pdfDoc, currentPage, canvas, longEdge);
    if (token !== renderToken) return;
  }

  prevBtn.addEventListener("click", () => showPage(currentPage - 1));
  nextBtn.addEventListener("click", () => showPage(currentPage + 1));
  closeBtn.addEventListener("click", () => dialog.close());

  let touchStartX = null;
  stage.addEventListener(
    "touchstart",
    (e) => {
      touchStartX = e.changedTouches[0].clientX;
    },
    { passive: true }
  );
  stage.addEventListener(
    "touchend",
    (e) => {
      if (touchStartX === null) return;
      const dx = e.changedTouches[0].clientX - touchStartX;
      touchStartX = null;
      if (Math.abs(dx) < 40) return; // too small to count as a deliberate swipe
      if (dx < 0) showPage(currentPage + 1);
      else showPage(currentPage - 1);
    },
    { passive: true }
  );

  function openPdfViewer({ pdfDoc: doc, filename }) {
    pdfDoc = doc;
    filenameEl.textContent = filename || "";
    dialog.showModal();
    showPage(1);
  }

  window.PrintmePdfViewer = { openPdfViewer };
})();
