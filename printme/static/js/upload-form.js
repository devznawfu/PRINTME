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
  const duplexInput = form.querySelector('input[name="duplex"]');
  const documentOptions = document.getElementById("document-options");
  const filesInput = document.getElementById("files-input");
  const fileListEl = document.getElementById("file-list");
  const submitBtn = document.getElementById("submit-btn");
  const helperText = document.getElementById("helper-text");
  const nameInput = form.querySelector('input[name="name"]');
  const codeInput = form.querySelector('input[name="code"]');

  const state = {
    service: serviceInput.value || "photo",
    colorMode: colorModeInput.value || "bw",
    duplex: duplexInput.value || "",
    files: [],
  };

  function syncFilesInput() {
    const dt = new DataTransfer();
    state.files.forEach((f) => dt.items.add(f));
    filesInput.files = dt.files;
  }

  function renderFileList() {
    fileListEl.innerHTML = "";
    state.files.forEach((file, i) => {
      const row = document.createElement("div");
      row.className =
        "flex items-center gap-3 rounded-xl bg-inset px-3.5 py-3";

      const dot = document.createElement("span");
      dot.className = "h-1.5 w-1.5 flex-none rounded-full bg-text";

      const name = document.createElement("span");
      name.className = "flex-1 truncate text-sm";
      name.textContent = file.name;

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "cursor-pointer px-2 py-1 text-sm text-muted";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", () => {
        state.files.splice(i, 1);
        syncFilesInput();
        renderFileList();
        updateUI();
      });

      row.append(dot, name, removeBtn);
      fileListEl.appendChild(row);
    });
    fileListEl.classList.toggle("hidden", state.files.length === 0);
  }

  function addFiles(fileList) {
    Array.from(fileList || []).forEach((f) => state.files.push(f));
    syncFilesInput();
    renderFileList();
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
    updateUI();
  }

  function photoQtyTotal() {
    let total = 0;
    document.querySelectorAll('#size-picker [data-stepper-input]').forEach((input) => {
      total += parseInt(input.value || "0", 10) || 0;
    });
    return total;
  }

  function setColorMode(colorMode) {
    state.colorMode = colorMode;
    colorModeInput.value = colorMode;
    document.querySelectorAll("[data-color-pick]").forEach((btn) => {
      const active = btn.dataset.colorPick === colorMode;
      btn.classList.toggle("bg-btn-bg", active);
      btn.classList.toggle("bg-panel", !active);
      btn.classList.toggle("text-btn-text", active);
      btn.classList.toggle("border-2", active);
      btn.classList.toggle("border", !active);
      btn.classList.toggle("border-text", active);
      btn.classList.toggle("border-line", !active);
    });
  }

  function setDuplex(duplex) {
    state.duplex = duplex;
    duplexInput.value = duplex;
    document.querySelectorAll("[data-duplex-pick]").forEach((btn) => {
      const active = btn.dataset.duplexPick === duplex;
      btn.classList.toggle("bg-btn-bg", active);
      btn.classList.toggle("bg-panel", !active);
      btn.classList.toggle("text-btn-text", active);
      btn.classList.toggle("border-2", active);
      btn.classList.toggle("border", !active);
      btn.classList.toggle("border-text", active);
      btn.classList.toggle("border-line", !active);
    });
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
  document.querySelectorAll("[data-duplex-pick]").forEach((btn) => {
    btn.addEventListener("click", () => setDuplex(btn.dataset.duplexPick));
  });

  codeInput.addEventListener("input", () => {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 4);
    updateUI();
  });
  nameInput.addEventListener("input", updateUI);

  form.addEventListener("submit", (e) => {
    if (!isReady().ready) e.preventDefault();
  });
  form.addEventListener("change", (e) => {
    if (e.target.matches("[data-stepper-input]")) updateUI();
  });

  setService(state.service);
  setColorMode(state.colorMode);
  setDuplex(state.duplex);
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
