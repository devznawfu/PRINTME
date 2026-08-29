// Client-side PDF page rendering for the customer upload flow - real
// thumbnails and page counts before a file ever uploads, using a
// self-hosted pdf.js build (printme/static/js/vendor/pdfjs/) rather
// than a CDN, same no-internet-at-runtime reasoning as the self-hosted
// DM Sans font in input.css. pdf.js itself ships as an ES module even
// in its "legacy" build, so this loads it via dynamic import() - that
// works from a plain classic <script> too, no need to make every
// script on the page type="module" just for this one dependency.
//
// Exposes window.PrintmePdfPreview = { loadDocument, renderPageToCanvas }
// - a thin wrapper, not a new abstraction: callers get back the real
// pdf.js PDFDocumentProxy (pdfDoc.numPages, pdfDoc.getPage(n), etc.)
// rather than a bespoke object, so nothing here has to keep up with
// what pdf.js itself can already do.
(function () {
  const PDFJS_URL = "/static/js/vendor/pdfjs/pdf.min.mjs";
  const PDFJS_WORKER_URL = "/static/js/vendor/pdfjs/pdf.worker.min.mjs";

  let pdfjsLibPromise = null;
  function loadPdfjsLib() {
    if (!pdfjsLibPromise) {
      pdfjsLibPromise = import(PDFJS_URL).then((lib) => {
        lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
        return lib;
      });
    }
    return pdfjsLibPromise;
  }

  async function loadDocument(file) {
    const pdfjsLib = await loadPdfjsLib();
    const data = await file.arrayBuffer();
    return pdfjsLib.getDocument({ data }).promise;
  }

  // maxDim caps the LONGER edge in CSS pixels - a thumbnail (~200) and
  // a full swipe-viewer page (~1200) ask for very different budgets;
  // rendering every page at full print resolution client-side for a
  // large PDF on a customer's phone would be slow and memory-heavy for
  // no visual benefit at preview size.
  async function renderPageToCanvas(pdfDoc, pageNumber, canvas, maxDim) {
    const page = await pdfDoc.getPage(pageNumber);
    const unscaled = page.getViewport({ scale: 1 });
    const scale = maxDim / Math.max(unscaled.width, unscaled.height);
    const viewport = page.getViewport({ scale });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const ctx = canvas.getContext("2d");
    await page.render({ canvasContext: ctx, viewport }).promise;
  }

  window.PrintmePdfPreview = { loadDocument, renderPageToCanvas };
})();
