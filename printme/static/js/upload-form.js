// Upload form interactivity (design-reference/upload-screen.html):
// service/size pickers, three file-add triggers feeding one cumulative
// file list, and live validation helper text. The server independently
// re-validates everything - this only blocks an obviously-incomplete
// submit from firing a request, it is not the authoritative gate.
(function () {
  const form = document.getElementById("upload-form");
  if (!form) return;

  const serviceInput = form.querySelector('input[name="service"]');
  const sizePicker = document.getElementById("size-picker");
  const colorModeInput = form.querySelector('input[name="color_mode"]');
  const paperFinishInput = form.querySelector('input[name="paper_finish"]');
  const qualityInput = form.querySelector('input[name="quality"]');
  const documentOptions = document.getElementById("document-options");
  const filesInput = document.getElementById("files-input");
  const fileListEl = document.getElementById("file-list");
  const cropFieldsEl = document.getElementById("crop-fields");
  const submitBtn = document.getElementById("submit-btn");
  const helperText = document.getElementById("helper-text");
  const nameInput = form.querySelector('input[name="name"]');
  const codeInput = form.querySelector('input[name="code"]');
  const stepFormEl = document.getElementById("step-form");
  const stepReviewEl = document.getElementById("step-review");
  const RATES = JSON.parse(document.getElementById("pm-rates").textContent);
  const peso = (n) => "₱" + n.toFixed(2);

  const state = {
    service: serviceInput.value || "photo",
    colorMode: colorModeInput.value || "bw",
    paperFinish: paperFinishInput.value || "bond",
    quality: qualityInput.value || "standard",
    files: [], // {id, file}[] - a stable id survives removal-by-splice, a bare index doesn't
    crops: new Map(), // file id -> {x, y, w, h} fractions from photo-crop.js
    nextFileId: 1,
  };

  function syncFilesInput() {
    const dt = new DataTransfer();
    state.files.forEach((entry) => dt.items.add(entry.file));
    filesInput.files = dt.files;
  }

  // Rebuilds the hidden crop_<i> fields from the CURRENT order of
  // state.files x state.crops - <i> is the file's position in that
  // order, matching how routes/upload.py positionally correlates
  // crop_<original_index> to request.files.getlist("files").
  function renderCropFields() {
    cropFieldsEl.innerHTML = "";
    state.files.forEach((entry, i) => {
      const crop = state.crops.get(entry.id);
      if (!crop) return;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = `crop_${i}`;
      input.value = JSON.stringify(crop);
      cropFieldsEl.appendChild(input);
    });
  }

  // photo-crop.js already knows the crop fractions once saved - draw them
  // to a small canvas so the row shows the ACTUAL crop, not just the word
  // "Edit crop". That's the proof something happened; the label change
  // alone never was (a real gap flagged in the transparency-pass design).
  const thumbCache = new Map(); // file id -> dataURL, keyed by its current crop state

  function renderThumb(entry) {
    const crop = state.crops.get(entry.id);
    const key = entry.id + ":" + (crop ? JSON.stringify(crop) : "auto");
    if (thumbCache.has(key)) return Promise.resolve(thumbCache.get(key));

    return new Promise((resolve) => {
      const url = URL.createObjectURL(entry.file);
      const image = new Image();
      image.onload = () => {
        const S = 104;
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = S;
        const ctx = canvas.getContext("2d");
        // Fractions are relative to the natural image; no crop = square
        // centre cover, matching the pipeline's auto-centre closely
        // enough for a small row thumbnail.
        let sx, sy, sw, sh;
        if (crop) {
          sx = crop.x * image.naturalWidth;
          sy = crop.y * image.naturalHeight;
          sw = crop.w * image.naturalWidth;
          sh = crop.h * image.naturalHeight;
        } else {
          sw = sh = Math.min(image.naturalWidth, image.naturalHeight);
          sx = (image.naturalWidth - sw) / 2;
          sy = (image.naturalHeight - sh) / 2;
        }
        ctx.drawImage(image, sx, sy, sw, sh, 0, 0, S, S);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.72);
        thumbCache.set(key, dataUrl);
        URL.revokeObjectURL(url);
        resolve(dataUrl);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      image.src = url;
    });
  }

  function buildFileRow(entry, i) {
    const cropped = state.crops.has(entry.id);
    const canCrop =
      state.service === "photo" &&
      window.PrintmePhotoCrop &&
      window.PrintmePhotoCrop.isImageFile(entry.file);

    const row = document.createElement("div");
    row.className =
      "flex items-center gap-3 rounded-xl bg-inset px-3 py-2.5" +
      (cropped ? " border border-ok-line" : "");

    const thumbWrap = document.createElement("span");
    thumbWrap.className =
      "relative h-[52px] w-[52px] flex-none overflow-hidden rounded-xl bg-thumb-a";

    if (canCrop) {
      const img = document.createElement("img");
      img.alt = "";
      img.className = "h-full w-full object-cover";
      thumbWrap.appendChild(img);
      renderThumb(entry).then((src) => {
        if (src) img.src = src;
      });
      if (cropped) {
        // The tick is the receipt: it appears the moment the dialog closes.
        const tick = document.createElement("span");
        tick.className =
          "animate-pop-in absolute -right-1 -bottom-1 flex h-[21px] w-[21px] items-center justify-center rounded-full border-2 border-inset bg-ok-dot text-ok-dot-text";
        tick.innerHTML =
          '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>';
        thumbWrap.appendChild(tick);
      }
    } else {
      thumbWrap.className += " flex items-center justify-center text-muted";
      thumbWrap.innerHTML =
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"></path><path d="M13 3v6h6"></path></svg>';
    }

    const meta = document.createElement("span");
    meta.className = "flex min-w-0 flex-1 flex-col gap-px";
    const name = document.createElement("span");
    name.className = "truncate text-[15px]";
    name.textContent = entry.file.name;
    meta.appendChild(name);
    if (cropped) {
      const note = document.createElement("span");
      note.className = "text-[13px] font-bold text-ok-dot";
      note.textContent = "Crop saved";
      meta.appendChild(note);
    } else if (!canCrop) {
      const ext = document.createElement("span");
      ext.className = "text-[13px] text-muted";
      ext.textContent = (entry.file.name.split(".").pop() || "").toUpperCase();
      meta.appendChild(ext);
    }

    row.append(thumbWrap, meta);

    if (canCrop) {
      const cropBtn = document.createElement("button");
      cropBtn.type = "button";
      cropBtn.className =
        "flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl border border-line bg-panel px-3.5 text-[14.5px] font-bold";
      cropBtn.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4l10-10-4-4L4 16z"></path><path d="M14 6l4 4"></path></svg>' +
        (cropped ? "Edit" : "Crop");
      cropBtn.addEventListener("click", () => {
        window.PrintmePhotoCrop.openCropDialog({
          file: entry.file,
          existingCrop: state.crops.get(entry.id) || null,
          onSave: (fractions) => {
            state.crops.set(entry.id, fractions);
            renderFileList();
            renderCropFields();
          },
          onClear: () => {
            state.crops.delete(entry.id);
            renderFileList();
            renderCropFields();
          },
        });
      });
      row.append(cropBtn);
    }

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "min-h-[44px] cursor-pointer px-2 text-[14.5px] text-muted";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      state.files.splice(i, 1);
      state.crops.delete(entry.id);
      syncFilesInput();
      renderFileList();
      renderCropFields();
      updateUI();
    });
    row.append(removeBtn);
    return row;
  }

  function renderFileList() {
    fileListEl.innerHTML = "";
    state.files.forEach((entry, i) => {
      fileListEl.appendChild(buildFileRow(entry, i));
    });
    fileListEl.classList.toggle("hidden", state.files.length === 0);
  }

  function addFiles(fileList) {
    Array.from(fileList || []).forEach((file) => {
      state.files.push({ id: state.nextFileId++, file });
    });
    syncFilesInput();
    renderFileList();
    renderCropFields();
    updateUI();
  }

  function setService(service) {
    state.service = service;
    serviceInput.value = service;
    sizePicker.classList.toggle("hidden", service !== "photo");
    documentOptions.classList.toggle("hidden", service !== "document");
    document.querySelectorAll("[data-service-pick]").forEach((btn) => {
      const active = btn.dataset.servicePick === service;
      // Toggle each pair explicitly - adding the active class without
      // also removing its inactive counterpart leaves both present,
      // and Tailwind's cascade order (not DOM order) decides the
      // winner, which is not reliably the one added last.
      btn.classList.toggle("border-text", active);
      btn.classList.toggle("border-2", active);
      btn.classList.toggle("border", !active);
      btn.classList.toggle("border-line", !active);
      btn.classList.toggle("bg-panel", active);
      btn.classList.toggle("bg-panel-soft", !active);
    });
    renderFileList();
    updateUI();
  }

  function photoQtyTotal() {
    let total = 0;
    document.querySelectorAll('#size-picker [data-stepper-input]').forEach((input) => {
      total += parseInt(input.value || "0", 10) || 0;
    });
    return total;
  }

  // Shared pill-toggle styling for any single-choice picker (color,
  // paper finish, quality) - one active pill, the rest plain.
  function setPickButtonStyles(dataAttr, value) {
    document.querySelectorAll(`[${dataAttr}]`).forEach((btn) => {
      const active = btn.dataset[toCamelCase(dataAttr)] === value;
      btn.classList.toggle("bg-btn-bg", active);
      btn.classList.toggle("bg-panel", !active);
      btn.classList.toggle("text-btn-text", active);
      btn.classList.toggle("border-2", active);
      btn.classList.toggle("border", !active);
      btn.classList.toggle("border-text", active);
      btn.classList.toggle("border-line", !active);
    });
  }

  function toCamelCase(dataAttr) {
    return dataAttr.replace(/^data-/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  }

  function setColorMode(colorMode) {
    state.colorMode = colorMode;
    colorModeInput.value = colorMode;
    setPickButtonStyles("data-color-pick", colorMode);
  }

  function setPaperFinish(paperFinish) {
    state.paperFinish = paperFinish;
    paperFinishInput.value = paperFinish;
    setPickButtonStyles("data-finish-pick", paperFinish);
  }

  function setQuality(quality) {
    state.quality = quality;
    qualityInput.value = quality;
    setPickButtonStyles("data-quality-pick", quality);
  }

  function isReady() {
    const nameOk = nameInput.value.trim().length > 0;
    const codeOk = /^\d{4}$/.test(codeInput.value.trim());
    const qtyOk = state.service !== "photo" || photoQtyTotal() > 0;
    const filesOk = state.files.length > 0;
    return { nameOk, codeOk, qtyOk, filesOk, ready: nameOk && codeOk && qtyOk && filesOk };
  }

  function updateUI() {
    const { nameOk, codeOk, qtyOk, filesOk, ready } = isReady();

    submitBtn.disabled = !ready;
    submitBtn.classList.toggle("cursor-not-allowed", !ready);
    submitBtn.classList.toggle("cursor-pointer", ready);
    submitBtn.classList.toggle("bg-btn-disabled-bg", !ready);
    submitBtn.classList.toggle("text-btn-disabled-text", !ready);
    submitBtn.classList.toggle("bg-btn-bg", ready);
    submitBtn.classList.toggle("text-btn-text", ready);
    submitBtn.classList.toggle("shadow-[0_8px_20px_rgba(0,0,0,0.18)]", ready);

    helperText.textContent = ready
      ? "Bring your phone to the counter if we need you."
      : !qtyOk
        ? "Pick at least one size and quantity to continue."
        : !filesOk
          ? "Add at least one file to continue."
          : !nameOk
            ? "Add your name to continue."
            : "Enter today's 4-digit code to continue.";
  }

  // ---------------------------------------------------- step 2: review/price
  // Mirrors services/pricing.py::compute_cost. Photo jobs price exactly;
  // document jobs can't (page_count is server-side only, known only after
  // upload + DOCX->PDF conversion), so they return a null total and the
  // review shows the rate/copies instead - the real total appears on the
  // confirmation screen after processing actually runs.
  function priceLines() {
    if (state.service === "photo") {
      const lines = [];
      document
        .querySelectorAll("#size-picker [data-stepper-input]")
        .forEach((input) => {
          const qty = parseInt(input.value || "0", 10) || 0;
          if (qty <= 0) return;
          const size = input.name.replace(/^qty_/, "");
          const rate = RATES[`${size}-${state.paperFinish}-${state.quality}`];
          if (rate === undefined) return;
          lines.push({
            label: `${size} photo`,
            detail: `${peso(rate)} each × ${qty}`,
            amount: rate * qty,
          });
        });
      const total = lines.reduce((sum, l) => sum + l.amount, 0);
      return { lines, total, note: null };
    }

    const rate = RATES[state.colorMode === "color" ? "color_page" : "bw_page"];
    const copies =
      parseInt(
        document.querySelector("#document-options [data-stepper-input]").value || "1",
        10
      ) || 1;
    return {
      lines: [
        {
          label: state.colorMode === "color" ? "Color printing" : "Black & white",
          detail: `${peso(rate)} per page × ${copies} ${copies === 1 ? "copy" : "copies"}`,
          amount: null,
        },
      ],
      total: null,
      note: "We'll count the pages when your file opens — staff will tell you the total at the counter.",
    };
  }

  function reviewSpecLine() {
    if (state.service === "photo") {
      const parts = [];
      document
        .querySelectorAll("#size-picker [data-stepper-input]")
        .forEach((input) => {
          const qty = parseInt(input.value || "0", 10) || 0;
          if (qty > 0) parts.push(`${input.name.replace(/^qty_/, "")} × ${qty}`);
        });
      const finish = state.paperFinish === "glossy" ? "Glossy" : "Bond paper";
      const quality = state.quality === "high" ? "high" : "standard";
      return `${parts.join(", ")} · ${finish}, ${quality}`;
    }
    const copies =
      parseInt(
        document.querySelector("#document-options [data-stepper-input]").value || "1",
        10
      ) || 1;
    return `${state.colorMode === "color" ? "Color" : "Black & white"} · ${copies} ${copies === 1 ? "copy" : "copies"} · A4`;
  }

  function buildReviewThumb(entry) {
    const wrap = document.createElement("div");
    wrap.className =
      "h-[82px] w-[82px] flex-none overflow-hidden rounded-[14px] bg-thumb-a";
    const canCrop =
      state.service === "photo" &&
      window.PrintmePhotoCrop &&
      window.PrintmePhotoCrop.isImageFile(entry.file);
    if (canCrop) {
      const img = document.createElement("img");
      img.alt = "";
      img.className = "h-full w-full object-cover";
      wrap.appendChild(img);
      renderThumb(entry).then((src) => {
        if (src) img.src = src;
      });
    } else {
      wrap.className += " flex items-center justify-center text-muted";
      wrap.innerHTML =
        '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"></path><path d="M13 3v6h6"></path></svg>';
    }
    return wrap;
  }

  function renderReview() {
    const { lines, total, note } = priceLines();
    const firstName = nameInput.value.trim().split(" ")[0] || "";

    stepReviewEl.querySelector("[data-review-name]").textContent = firstName ? ", " + firstName : "";
    stepReviewEl.querySelector("[data-review-detail-name]").textContent = nameInput.value.trim();
    stepReviewEl.querySelector("[data-review-detail-code]").textContent =
      codeInput.value.trim().split("").join(" ");
    stepReviewEl.querySelector("[data-review-files-heading]").textContent =
      state.service === "photo" ? "Your photos" : "Your files";

    // File cards: thumbnail + what will print + an Edit crop shortcut that
    // reopens the same dialog, so "change something" never means starting over.
    const filesEl = stepReviewEl.querySelector("[data-review-files]");
    filesEl.innerHTML = "";
    state.files.forEach((entry) => {
      const card = document.createElement("div");
      card.className =
        "flex items-center gap-3.5 rounded-[20px] border border-line bg-panel p-3.5";
      card.appendChild(buildReviewThumb(entry));

      const meta = document.createElement("div");
      meta.className = "flex min-w-0 flex-1 flex-col gap-0.5";
      const name = document.createElement("div");
      name.className = "truncate text-[16.5px] font-bold";
      name.textContent = entry.file.name;
      const spec = document.createElement("div");
      spec.className = "text-[14.5px] text-muted";
      spec.textContent = reviewSpecLine();
      meta.append(name, spec);

      const cropNote = document.createElement("div");
      if (state.crops.has(entry.id)) {
        cropNote.className = "flex items-center gap-1.5 text-[13.5px] font-bold text-ok-dot";
        cropNote.innerHTML =
          '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>You cropped this yourself';
      } else if (state.service === "photo") {
        cropNote.className = "text-[13.5px] text-muted";
        cropNote.textContent = "We centred the face for you";
      }
      meta.appendChild(cropNote);
      card.appendChild(meta);
      filesEl.appendChild(card);
    });

    const linesEl = stepReviewEl.querySelector("[data-review-price-lines]");
    linesEl.innerHTML = "";
    lines.forEach((l) => {
      const row = document.createElement("div");
      row.className = "flex items-baseline justify-between gap-3.5 px-[18px] py-4";
      const left = document.createElement("span");
      left.className = "text-[16.5px]";
      left.innerHTML = `${l.label} <span class="text-muted">· ${l.detail}</span>`;
      const right = document.createElement("span");
      right.className = "text-[17px] font-bold tabular-nums";
      right.textContent = l.amount === null ? "—" : peso(l.amount);
      row.append(left, right);
      linesEl.appendChild(row);
    });

    const totalText = total === null ? "At the counter" : peso(total);
    stepReviewEl.querySelector("[data-review-total]").textContent = totalText;
    stepReviewEl.querySelector("[data-review-submit-total]").textContent =
      total === null ? "this" : peso(total);
    stepReviewEl.querySelector("[data-review-price-note]").textContent =
      note || "Prices are today's shop rates. Staff will confirm the total when you pay.";
  }

  // #submit-btn stops being a submit button: it validates, then reveals
  // step 2. The only type="submit" in the form now lives on the review
  // panel, so the point of no return is a single button the customer has
  // to deliberately reach.
  function showStep(step) {
    const review = step === "review";
    stepFormEl.classList.toggle("hidden", review);
    stepReviewEl.classList.toggle("hidden", !review);
    stepReviewEl.classList.toggle("flex", review);
    if (review) renderReview();
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  const moreSizesToggle = document.getElementById("more-sizes-toggle");
  const moreSizes = document.getElementById("more-sizes");
  const moreSizesLabel = document.getElementById("more-sizes-toggle-label");
  const moreSizesIcon = document.getElementById("more-sizes-toggle-icon");
  moreSizesToggle.addEventListener("click", () => {
    const expanded = moreSizesToggle.getAttribute("aria-expanded") === "true";
    moreSizesToggle.setAttribute("aria-expanded", String(!expanded));
    moreSizes.classList.toggle("hidden", expanded);
    moreSizesLabel.textContent = expanded ? "More sizes" : "Fewer sizes";
    moreSizesIcon.innerHTML = expanded ? "&#9662;" : "&#9652;";
  });

  document.getElementById("open-camera").addEventListener("click", () => {
    document.getElementById("camera-input").click();
  });
  document.getElementById("open-gallery").addEventListener("click", () => {
    document.getElementById("gallery-input").click();
  });
  document.getElementById("open-files").addEventListener("click", () => {
    document.getElementById("file-input").click();
  });

  ["camera-input", "gallery-input", "file-input"].forEach((id) => {
    document.getElementById(id).addEventListener("change", (e) => {
      addFiles(e.target.files);
      e.target.value = "";
    });
  });

  document.querySelectorAll("[data-service-pick]").forEach((btn) => {
    btn.addEventListener("click", () => setService(btn.dataset.servicePick));
  });
  document.querySelectorAll("[data-color-pick]").forEach((btn) => {
    btn.addEventListener("click", () => setColorMode(btn.dataset.colorPick));
  });
  document.querySelectorAll("[data-finish-pick]").forEach((btn) => {
    btn.addEventListener("click", () => setPaperFinish(btn.dataset.finishPick));
  });
  document.querySelectorAll("[data-quality-pick]").forEach((btn) => {
    btn.addEventListener("click", () => setQuality(btn.dataset.qualityPick));
  });

  codeInput.addEventListener("input", () => {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 4);
    updateUI();
  });
  nameInput.addEventListener("input", updateUI);

  submitBtn.type = "button";
  submitBtn.textContent = "Review before sending";
  submitBtn.addEventListener("click", () => {
    if (isReady().ready) showStep("review");
  });
  document
    .querySelectorAll("#review-back, #review-back-bottom")
    .forEach((btn) => btn.addEventListener("click", () => showStep("form")));

  // Guard: a stale review panel must never submit. If anything in step 1
  // changed while step 2 was open (or step 2 was never actually reached),
  // the submit is refused and step 1 is shown again instead.
  form.addEventListener("submit", (e) => {
    if (!isReady().ready || stepReviewEl.classList.contains("hidden")) {
      e.preventDefault();
      showStep("form");
    }
  });
  form.addEventListener("change", (e) => {
    if (e.target.matches("[data-stepper-input]")) updateUI();
  });

  setService(state.service);
  setColorMode(state.colorMode);
  setPaperFinish(state.paperFinish);
  setQuality(state.quality);
  renderFileList();
  updateUI();

  // Splash flash: brief brand moment before the form beneath is
  // revealed. Only present when there are no validation errors (see
  // the {% if not errors %} guard in the template) - a failed submit
  // re-renders this same page and shouldn't re-flash over the error.
  const splash = document.getElementById("splash");
  if (splash) {
    setTimeout(() => {
      splash.classList.add("opacity-0");
      setTimeout(() => splash.remove(), 300);
    }, 650);
  }
})();
