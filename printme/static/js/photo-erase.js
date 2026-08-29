// Manual "snip" tool: freehand erase directly on an already-processed
// photo (see printme/services/photo_erase.py). Its own module, not
// grown onto photo-crop.js - a paint tool sharing nothing with a
// pan/zoom crop rectangle beyond both being photo dialogs.
//
// window.PrintmePhotoErase.openEraseDialog({imageUrl, onSave}) is the
// public entry point, called from admin-photo-erase.js (job cards +
// the flagged review page) and, later, admin-photo-sheets.js (per-item
// hotspots on a packed sheet) - all three just need "open this image,
// give me back a strokes payload," not the drawing internals.
(function () {
  const dialog = document.getElementById("erase-dialog");
  if (!dialog) return;

  const wrapper = dialog.querySelector("[data-erase-wrapper]");
  const img = dialog.querySelector("[data-erase-image]");
  const canvas = dialog.querySelector("[data-erase-canvas]");
  const ctx = canvas.getContext("2d");
  const undoBtn = dialog.querySelector("[data-erase-undo-btn]");
  const clearBtn = dialog.querySelector("[data-erase-clear-btn]");
  const saveBtn = dialog.querySelector("[data-erase-save-btn]");
  const cancelBtn = dialog.querySelector("[data-erase-cancel-btn]");

  const RADIUS_BY_SIZE = { small: 0.015, medium: 0.03, large: 0.06 };

  let strokes = [];
  let currentStroke = null;
  let drawing = false;
  let radiusFraction = RADIUS_BY_SIZE.medium;
  let onSaveCallback = null;

  function redraw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const r = radiusFraction * canvas.width;
    ctx.lineWidth = r * 2;

    const allStrokes = currentStroke ? [...strokes, currentStroke] : strokes;
    allStrokes.forEach((stroke) => {
      if (!stroke.length) return;
      const px = stroke.map((p) => ({ x: p.x * canvas.width, y: p.y * canvas.height }));
      ctx.beginPath();
      ctx.arc(px[0].x, px[0].y, r, 0, Math.PI * 2);
      ctx.fill();
      if (px.length > 1) {
        ctx.beginPath();
        ctx.moveTo(px[0].x, px[0].y);
        px.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
        ctx.stroke();
        const last = px[px.length - 1];
        ctx.beginPath();
        ctx.arc(last.x, last.y, r, 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }

  function pointFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return { x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) };
  }

  function setBrushSize(size) {
    radiusFraction = RADIUS_BY_SIZE[size] || RADIUS_BY_SIZE.medium;
    dialog.querySelectorAll("[data-brush-size]").forEach((btn) => {
      const active = btn.dataset.brushSize === size;
      btn.classList.toggle("border-btn-bg", active);
      btn.classList.toggle("border-line", !active);
    });
    redraw();
  }
  dialog.querySelectorAll("[data-brush-size]").forEach((btn) => {
    btn.addEventListener("click", () => setBrushSize(btn.dataset.brushSize));
  });

  canvas.addEventListener("pointerdown", (e) => {
    drawing = true;
    currentStroke = [pointFromEvent(e)];
    canvas.setPointerCapture(e.pointerId);
    redraw();
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    currentStroke.push(pointFromEvent(e));
    redraw();
  });
  function endStroke() {
    if (!drawing) return;
    drawing = false;
    if (currentStroke && currentStroke.length) strokes.push(currentStroke);
    currentStroke = null;
    redraw();
  }
  canvas.addEventListener("pointerup", endStroke);
  canvas.addEventListener("pointercancel", endStroke);

  undoBtn.addEventListener("click", () => {
    strokes.pop();
    redraw();
  });
  clearBtn.addEventListener("click", () => {
    strokes = [];
    redraw();
  });
  cancelBtn.addEventListener("click", () => dialog.close());

  saveBtn.addEventListener("click", () => {
    dialog.close();
    if (strokes.length === 0) return;
    const payload = JSON.stringify({
      strokes: strokes.map((stroke) => stroke.map((p) => ({ x: p.x, y: p.y }))),
      radius: radiusFraction,
    });
    if (onSaveCallback) onSaveCallback(payload);
  });

  function sizeCanvasToWrapper() {
    const rect = wrapper.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    redraw();
  }

  function openEraseDialog({ imageUrl, onSave }) {
    strokes = [];
    currentStroke = null;
    onSaveCallback = onSave;
    setBrushSize("medium");

    img.onload = () => {
      // Locks the wrapper to the real photo's own aspect ratio, so the
      // image fills it exactly (no object-contain letterboxing) and the
      // overlay canvas's pixel grid lines up 1:1 with the image - a
      // stroke's fraction coordinates are only meaningful if "the whole
      // box" and "the whole image" are the same rectangle.
      wrapper.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
      requestAnimationFrame(sizeCanvasToWrapper);
    };
    img.src = imageUrl;

    dialog.showModal();
  }

  window.addEventListener("resize", () => {
    if (dialog.open) sizeCanvasToWrapper();
  });

  window.PrintmePhotoErase = { openEraseDialog };
})();
