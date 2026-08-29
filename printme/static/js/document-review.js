// "View details & print" for document jobs: one shared dialog, opened
// from any document job card's [data-document-review-trigger] button.
// Every option control lives inside the dialog but submits through the
// card's own hidden <form id="print-form-{jobId}"> via the HTML `form=""`
// attribute (bound dynamically per job at open time, same trick
// print-confirm.js already uses for its confirm button) - so there is
// still exactly one real <form> per job card, this dialog just supplies
// its fields from a different place in the DOM.
//
// The live preview (rotate for landscape, desaturate for black & white,
// inset border for margin, dim pages outside the selected range) is
// purely client-side CSS on the same thumbnail images real staff will
// look at before deciding anything - not a claim about exact print
// output, just enough to make each choice legible at a glance.
(function () {
  const dialog = document.getElementById("document-review-dialog");
  if (!dialog) return;

  const filenameEl = dialog.querySelector("[data-review-filename]");
  const pageCountEl = dialog.querySelector("[data-review-page-count]");
  const heroBtn = dialog.querySelector("[data-review-hero-btn]");
  const heroImg = dialog.querySelector("[data-review-hero-img]");
  const heroCaption = dialog.querySelector("[data-review-hero-caption]");
  const thumbsEl = dialog.querySelector("[data-review-thumbs]");
  const pageRangeInput = dialog.querySelector("[data-review-page-range-input]");
  const printerSelect = dialog.querySelector("[data-review-printer-select]");
  const copiesDisplay = dialog.querySelector("[data-review-copies-display]");
  const copiesInput = dialog.querySelector("[data-review-copies-input]");
  const cancelBtn = dialog.querySelector("[data-review-cancel-btn]");
  const printBtn = dialog.querySelector("[data-review-print-btn]");

  const boundFields = [pageRangeInput, printerSelect, copiesInput, ...dialog.querySelectorAll("[data-choice-input]")];

  let maxPages = 1;
  let includedPages = new Set();
  let currentJobId = null;
  let focusedPage = 1;

  function parsePageRange(spec, max) {
    const trimmed = (spec || "").trim();
    if (!trimmed) {
      const all = [];
      for (let i = 1; i <= max; i++) all.push(i);
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
      if (p < 1 || p > max) return null;
    }
    return Array.from(pages).sort((a, b) => a - b);
  }

  function describePageRange(pages, max) {
    if (pages.length === max) return "";
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
    return spans.join(",");
  }

  function applyThumbLooks() {
    const orientation = dialog.querySelector('[data-choice-input="orientation"]').value;
    const colorMode = dialog.querySelector('[data-choice-input="color_mode"]').value;
    const margin = dialog.querySelector('[data-choice-input="margin"]').value;
    const marginInset = { normal: "6%", narrow: "1%", wide: "14%" }[margin] || "6%";
    const transform = orientation === "landscape" ? "rotate(90deg)" : "none";
    const filter = colorMode === "bw" ? "grayscale(1)" : "none";

    thumbsEl.querySelectorAll("[data-thumb-page]").forEach((wrap) => {
      const page = parseInt(wrap.dataset.thumbPage, 10);
      const img = wrap.querySelector("img");
      const included = includedPages.has(page);
      wrap.classList.toggle("opacity-30", !included);
      wrap.querySelector("[data-thumb-toggle]").textContent = included ? "✓" : "";
      img.style.transform = transform;
      img.style.filter = filter;
      img.style.padding = marginInset;
    });

    heroImg.style.transform = transform;
    heroImg.style.filter = filter;
    heroImg.style.padding = marginInset;
  }

  function syncPageRangeInput() {
    pageRangeInput.value = describePageRange(Array.from(includedPages).sort((a, b) => a - b), maxPages);
  }

  function pageImageUrl(jobId, page) {
    return `/admin/jobs/${jobId}/preview/${page}.png`;
  }

  // The real 300 DPI render (same resolution the printer gets), not the
  // small 220px thumbnail - that thumbnail reopened in a new tab was the
  // literal bug "tap to view full size" reported: it was never actually
  // bigger, just the same tiny image on a bigger background.
  function pageImageUrlFull(jobId, page) {
    return `/admin/jobs/${jobId}/preview/${page}/full.png`;
  }

  function showInHero(page) {
    focusedPage = page;
    heroImg.src = pageImageUrlFull(currentJobId, page);
    heroCaption.textContent = `Page ${page} of ${maxPages} - tap the image to open it full size`;
    thumbsEl.querySelectorAll("[data-thumb-page]").forEach((wrap) => {
      const isFocused = parseInt(wrap.dataset.thumbPage, 10) === page;
      wrap.classList.toggle("border-btn-bg", isFocused);
      wrap.classList.toggle("border-line", !isFocused);
    });
  }

  heroBtn.addEventListener("click", () => {
    window.open(pageImageUrlFull(currentJobId, focusedPage), "_blank");
  });

  function buildThumbs(jobId) {
    thumbsEl.innerHTML = "";
    for (let p = 1; p <= maxPages; p++) {
      const wrap = document.createElement("div");
      wrap.dataset.thumbPage = String(p);
      wrap.className = "relative flex flex-col items-center gap-1 rounded-xl border-2 border-line bg-panel p-1.5 transition-opacity";

      const previewBtn = document.createElement("button");
      previewBtn.type = "button";
      previewBtn.title = `View page ${p} large`;
      previewBtn.className = "cursor-pointer";
      const img = document.createElement("img");
      img.src = pageImageUrl(jobId, p);
      img.alt = `Page ${p}`;
      img.className = "h-[90px] w-[70px] rounded-md object-cover transition-transform";
      previewBtn.appendChild(img);
      previewBtn.addEventListener("click", () => showInHero(p));

      const label = document.createElement("span");
      label.className = "text-[13px] font-bold text-muted";
      label.textContent = String(p);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.dataset.thumbToggle = "";
      toggleBtn.title = `Include or skip page ${p} when printing`;
      toggleBtn.className = "absolute -right-2 -top-2 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border-2 border-line bg-ok-bg text-[15px] font-bold text-ok-dot";
      toggleBtn.addEventListener("click", () => {
        if (includedPages.has(p)) {
          if (includedPages.size === 1) return; // never allow zero pages selected
          includedPages.delete(p);
        } else {
          includedPages.add(p);
        }
        syncPageRangeInput();
        applyThumbLooks();
      });

      wrap.append(previewBtn, label, toggleBtn);
      thumbsEl.appendChild(wrap);
    }
    showInHero(1);
  }

  function setChoice(group, value) {
    const input = dialog.querySelector(`[data-choice-input="${group}"]`);
    input.value = value;
    dialog.querySelectorAll(`[data-choice-group="${group}"] [data-choice-value]`).forEach((btn) => {
      const active = btn.dataset.choiceValue === value;
      btn.classList.toggle("border-btn-bg", active);
      btn.classList.toggle("bg-inset", active);
      btn.classList.toggle("border-line", !active);
    });
    applyThumbLooks();
  }

  dialog.querySelectorAll("[data-choice-group]").forEach((group) => {
    const name = group.dataset.choiceGroup;
    group.querySelectorAll("[data-choice-value]").forEach((btn) => {
      btn.addEventListener("click", () => setChoice(name, btn.dataset.choiceValue));
    });
  });

  function setCopies(value) {
    copiesDisplay.textContent = String(value);
    copiesInput.value = String(value);
  }
  dialog.querySelector("[data-review-copies-dec]").addEventListener("click", () => {
    setCopies(Math.max(1, parseInt(copiesInput.value, 10) - 1));
  });
  dialog.querySelector("[data-review-copies-inc]").addEventListener("click", () => {
    setCopies(Math.min(99, parseInt(copiesInput.value, 10) + 1));
  });

  pageRangeInput.addEventListener("input", () => {
    const parsed = parsePageRange(pageRangeInput.value, maxPages);
    if (parsed === null) return; // leave thumbnails as-is until it's valid again
    includedPages = new Set(parsed);
    applyThumbLooks();
  });

  document.querySelectorAll("[data-document-review-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const jobId = trigger.dataset.jobId;
      const formId = `print-form-${jobId}`;
      currentJobId = jobId;

      maxPages = parseInt(trigger.dataset.pageCount, 10) || 1;
      includedPages = new Set(Array.from({ length: maxPages }, (_, i) => i + 1));

      filenameEl.textContent = trigger.dataset.filename || "";
      pageCountEl.textContent = `${maxPages} page${maxPages !== 1 ? "s" : ""}`;

      buildThumbs(jobId);
      pageRangeInput.value = "";
      setCopies(parseInt(trigger.dataset.copies, 10) || 1);
      setChoice("color_mode", trigger.dataset.colorMode || "bw");
      setChoice("paper_size", trigger.dataset.paperSize || "A4");
      setChoice("orientation", trigger.dataset.orientation || "portrait");
      setChoice("margin", trigger.dataset.margin || "normal");
      setChoice("print_quality", trigger.dataset.printQuality || "normal");

      const printerValue = trigger.dataset.printer;
      if (printerValue) printerSelect.value = printerValue;

      boundFields.forEach((el) => el.setAttribute("form", formId));
      printBtn.setAttribute("form", formId);

      dialog.showModal();
    });
  });

  if (cancelBtn) cancelBtn.addEventListener("click", () => dialog.close());
  if (printBtn) {
    printBtn.addEventListener("click", () => {
      const form = document.getElementById(printBtn.getAttribute("form"));
      if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }
})();
