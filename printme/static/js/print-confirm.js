// Shared print confirmation dialog for both document jobs and photo
// sheets, branching on data-print-kind. "Not yet" is the bold/focused
// button, "Yes, print" is the plain one - deliberately inverted from
// the usual primary-action styling, so a stray Enter or a fast click
// lands on the safe action, not an irreversible print (turn 3b: print
// is the one action in this app that can't be undone once it fires).
//
// The page-range grammar here mirrors printme/services/page_range.py
// for instant UX feedback only - the server re-validates independently
// and is the real authority (see printme/routes/api.py's print_document).
(function () {
  const dialog = document.getElementById("print-confirm-dialog");
  if (!dialog) return;

  const headingEl = dialog.querySelector("[data-print-heading]");
  const paperNoteEl = dialog.querySelector("[data-print-paper-note]");
  const summaryEl = dialog.querySelector("[data-print-summary]");
  const thumbsEl = dialog.querySelector("[data-print-thumbs]");
  const confirmBtn = dialog.querySelector("[data-print-confirm-btn]");
  const cancelBtn = dialog.querySelector("[data-print-cancel-btn]");

  const FINISH_LABELS = { glossy: "Glossy", bond: "Bond paper" };
  const QUALITY_LABELS = { standard: "Standard", high: "High" };

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

  function heading(form, fallback) {
    const ticket = form.dataset.ticket;
    const name = form.dataset.customerName;
    if (ticket && name) return `Print ${ticket} for ${name}?`;
    if (ticket) return `Print ${ticket}?`;
    return fallback || "Confirm print";
  }

  function openDocumentConfirm(form) {
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
      return false;
    }
    if (rangeInput) rangeInput.setCustomValidity("");

    headingEl.textContent = heading(form);
    paperNoteEl.textContent = `Load A4 paper - ${colorMode.toLowerCase()}.`;

    summaryEl.innerHTML = "";
    addSummaryRow("Copies", copies);
    addSummaryRow("Pages", describePageRange(pages, maxPages));
    addSummaryRow("Color", colorMode);

    thumbsEl.innerHTML = "";
    thumbsEl.classList.remove("hidden");
    const jobId = form.dataset.jobId;
    pages.forEach((p) => {
      const img = document.createElement("img");
      img.src = `/admin/jobs/${jobId}/preview/${p}.png`;
      img.alt = `Page ${p}`;
      img.className = "h-[70px] w-[70px] rounded-lg border border-line object-cover";
      thumbsEl.appendChild(img);
    });
    return true;
  }

  function openSheetConfirm(form) {
    const sheetNumber = form.dataset.sheetNumber || "1";
    const sheetCount = form.dataset.sheetCount || "1";
    const finish = FINISH_LABELS[form.dataset.paperFinish] || "Bond paper";
    const quality = QUALITY_LABELS[form.dataset.paperQuality] || "Standard";

    headingEl.textContent = heading(form, `Print sheet ${sheetNumber} of ${sheetCount}?`);
    paperNoteEl.textContent = `Load ${finish}, ${quality.toLowerCase()} quality, before printing.`;

    summaryEl.innerHTML = "";
    addSummaryRow("Sheet", `${sheetNumber} of ${sheetCount}`);
    addSummaryRow("Paper", `${finish}, ${quality}`);

    thumbsEl.innerHTML = "";
    thumbsEl.classList.add("hidden"); // the sheet preview is already visible on the page itself
    return true;
  }

  document.querySelectorAll("[data-print-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const form = trigger.closest("[data-print-form]");
      if (!form) return;

      const kind = form.dataset.printKind || "document";
      const ok = kind === "sheet" ? openSheetConfirm(form) : openDocumentConfirm(form);
      if (!ok) return;

      confirmBtn.setAttribute("form", form.id);
      dialog.showModal();
    });
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => dialog.close());
  }
})();
