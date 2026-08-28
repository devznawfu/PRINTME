// Print confirmation popup for document jobs: shows a summary
// (copies/pages/color) plus small per-page thumbnails before the
// print form actually submits. The page-range grammar here mirrors
// printme/services/page_range.py for instant UX feedback only - the
// server re-validates independently and is the real authority (see
// printme/routes/api.py's print_document).
(function () {
  const dialog = document.getElementById("print-confirm-dialog");
  if (!dialog) return;

  const summaryEl = dialog.querySelector("[data-print-summary]");
  const thumbsEl = dialog.querySelector("[data-print-thumbs]");
  const confirmBtn = dialog.querySelector("[data-print-confirm-btn]");
  const cancelBtn = dialog.querySelector("[data-print-cancel-btn]");

  function parsePageRange(spec, maxPages) {
    const trimmed = (spec || "").trim();
    if (!trimmed) {
      const all = [];
      for (let i = 1; i <= maxPages; i++) all.push(i);
      return all;
    }
    const pages = new Set();
    for (const rawToken of trimmed.split(",")) {
      const token = rawToken.trim();
      if (!token) continue;
      if (token.includes("-")) {
        const [startRaw, endRaw] = token.split("-");
        const start = (startRaw || "").trim();
        const end = (endRaw || "").trim();
        if (!/^\d+$/.test(start) || !/^\d+$/.test(end)) return null;
        const startN = parseInt(start, 10);
        const endN = parseInt(end, 10);
        if (startN > endN) return null;
        for (let i = startN; i <= endN; i++) pages.add(i);
      } else {
        if (!/^\d+$/.test(token)) return null;
        pages.add(parseInt(token, 10));
      }
    }
    if (pages.size === 0) return null;
    for (const p of pages) {
      if (p < 1 || p > maxPages) return null;
    }
    return Array.from(pages).sort((a, b) => a - b);
  }

  function describePageRange(pages, maxPages) {
    if (pages.length === maxPages) {
      return `All ${maxPages} page${maxPages !== 1 ? "s" : ""}`;
    }
    const sorted = [...pages].sort((a, b) => a - b);
    const spans = [];
    let start = sorted[0];
    let prev = sorted[0];
    for (let i = 1; i < sorted.length; i++) {
      const p = sorted[i];
      if (p === prev + 1) {
        prev = p;
        continue;
      }
      spans.push(start === prev ? `${start}` : `${start}-${prev}`);
      start = prev = p;
    }
    spans.push(start === prev ? `${start}` : `${start}-${prev}`);
    return `Pages ${spans.join(", ")} (${sorted.length} of ${maxPages})`;
  }

  function addSummaryRow(label, value) {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    dt.className = "inline font-bold";
    dt.textContent = label + ": ";
    const dd = document.createElement("dd");
    dd.className = "inline";
    dd.textContent = value;
    row.append(dt, dd);
    summaryEl.appendChild(row);
  }

  document.querySelectorAll("[data-print-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const form = trigger.closest("[data-print-form]");
      if (!form) return;

      const jobId = form.dataset.jobId;
      const maxPages = parseInt(form.dataset.pageCount, 10) || 1;
      const copies = form.dataset.copies || "1";
      const colorMode = form.dataset.colorMode === "color" ? "Color" : "Black & white";
      const rangeInput = form.querySelector("[data-page-range-input]");

      const pages = parsePageRange(rangeInput ? rangeInput.value : "", maxPages);
      if (pages === null) {
        if (rangeInput) {
          rangeInput.setCustomValidity(
            `Enter a valid page range, e.g. 1-3,5 (this document has ${maxPages} page${maxPages !== 1 ? "s" : ""}).`
          );
          rangeInput.reportValidity();
        }
        return;
      }
      if (rangeInput) rangeInput.setCustomValidity("");

      summaryEl.innerHTML = "";
      addSummaryRow("Copies", copies);
      addSummaryRow("Pages", describePageRange(pages, maxPages));
      addSummaryRow("Color", colorMode);

      thumbsEl.innerHTML = "";
      pages.forEach((p) => {
        const img = document.createElement("img");
        img.src = `/admin/jobs/${jobId}/preview/${p}.png`;
        img.alt = `Page ${p}`;
        img.className = "h-[70px] w-[70px] rounded-lg border border-line object-cover";
        thumbsEl.appendChild(img);
      });

      confirmBtn.setAttribute("form", `print-form-${jobId}`);
      dialog.showModal();
    });
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => dialog.close());
  }
})();
