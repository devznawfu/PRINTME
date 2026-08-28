// Manual photo-crop tool for the customer upload portal (per-photo, not
// per-batch): a fixed square frame, drag-to-pan via the Pointer Events
// API (unifies mouse/touch/pen - no hand-rolled pinch-gesture math),
// and a zoom slider. The one deliberate exception to this app's
// zero-global-JS convention: window.PrintmePhotoCrop, since
// upload-form.js's file list and this dialog genuinely need to
// cooperate (which file is being cropped, what crop it already has).
//
// Crop state is stored and sent to the server as fractions (x, y, w,
// h - all 0-1) of the image's NATURAL width/height, i.e. img.
// naturalWidth/naturalHeight - the space browsers decode a photo into
// after applying its own EXIF-orientation auto-rotation. That is
// exactly the space printme/services/photo_pipeline.py's manual-crop
// branch reconstructs server-side via PIL.ImageOps.exif_transpose(),
// so the crop the customer drew lines up with what the server crops.
(function () {
  const dialog = document.getElementById("crop-dialog");
  if (!dialog) return;

  const frame = dialog.querySelector("[data-crop-frame]");
  const img = dialog.querySelector("[data-crop-image]");
  const zoomInput = dialog.querySelector("[data-crop-zoom]");
  const saveBtn = dialog.querySelector("[data-crop-save-btn]");
  const clearBtn = dialog.querySelector("[data-crop-clear-btn]");
  const cancelBtn = dialog.querySelector("[data-crop-cancel-btn]");

  const MIN_ZOOM = parseFloat(zoomInput.min) || 1;
  const MAX_ZOOM = parseFloat(zoomInput.max) || 3;

  let currentObjectUrl = null;
  let pendingOnSave = null;
  let pendingOnClear = null;
  let dragState = null;

  // Geometry for the file currently loaded into the dialog. Recomputed
  // fresh every time openCropDialog() runs.
  let naturalWidth = 0;
  let naturalHeight = 0;
  let frameSize = 0;
  let baseScale = 1; // scale at zoom=1: the image's SHORTER side exactly fills the frame ("cover" fit)
  let displayScale = 1; // baseScale * current zoom
  let displayWidth = 0;
  let displayHeight = 0;
  let panX = 0; // image's top-left corner position, in frame-relative CSS px
  let panY = 0;

  function clamp(value, lo, hi) {
    return Math.min(hi, Math.max(lo, value));
  }

  function isImageFile(file) {
    return !!file && typeof file.type === "string" && file.type.startsWith("image/");
  }

  function setPan(x, y) {
    // displayWidth/displayHeight are always >= frameSize (baseScale
    // guarantees the shorter side covers the frame at zoom=1, and zoom
    // only ever increases it) - so both ranges below are valid with
    // min <= max, and pan can never reveal empty space at an edge.
    const minX = frameSize - displayWidth;
    const minY = frameSize - displayHeight;
    panX = clamp(x, minX, 0);
    panY = clamp(y, minY, 0);
  }

  function render() {
    img.style.width = displayWidth + "px";
    img.style.height = displayHeight + "px";
    img.style.left = panX + "px";
    img.style.top = panY + "px";
  }

  function setZoom(zoom, anchorX, anchorY) {
    zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const anchorFrameX = anchorX === undefined ? frameSize / 2 : anchorX;
    const anchorFrameY = anchorY === undefined ? frameSize / 2 : anchorY;
    // Keep whichever image content sits under the anchor point fixed in
    // place while the zoom level changes, instead of always zooming
    // from the image's top-left corner.
    const imageX = (anchorFrameX - panX) / displayScale;
    const imageY = (anchorFrameY - panY) / displayScale;

    displayScale = baseScale * zoom;
    displayWidth = naturalWidth * displayScale;
    displayHeight = naturalHeight * displayScale;
    setPan(anchorFrameX - imageX * displayScale, anchorFrameY - imageY * displayScale);
    render();
  }

  function currentFractions() {
    const cropSideNatural = frameSize / displayScale;
    return {
      x: -panX / displayScale / naturalWidth,
      y: -panY / displayScale / naturalHeight,
      w: cropSideNatural / naturalWidth,
      h: cropSideNatural / naturalHeight,
    };
  }

  function closeDialog() {
    dialog.close();
  }

  dialog.addEventListener("close", () => {
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }
    pendingOnSave = null;
    pendingOnClear = null;
    dragState = null;
  });

  frame.addEventListener("pointerdown", (e) => {
    dragState = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startPanX: panX,
      startPanY: panY,
    };
    frame.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  frame.addEventListener("pointermove", (e) => {
    if (!dragState || e.pointerId !== dragState.pointerId) return;
    const dx = e.clientX - dragState.startClientX;
    const dy = e.clientY - dragState.startClientY;
    setPan(dragState.startPanX + dx, dragState.startPanY + dy);
    render();
  });

  function endDrag(e) {
    if (dragState && e.pointerId === dragState.pointerId) dragState = null;
  }
  frame.addEventListener("pointerup", endDrag);
  frame.addEventListener("pointercancel", endDrag);

  zoomInput.addEventListener("input", () => {
    setZoom(parseFloat(zoomInput.value));
  });

  saveBtn.addEventListener("click", () => {
    const fractions = currentFractions();
    const cb = pendingOnSave;
    closeDialog();
    if (cb) cb(fractions);
  });

  clearBtn.addEventListener("click", () => {
    const cb = pendingOnClear;
    closeDialog();
    if (cb) cb();
  });

  cancelBtn.addEventListener("click", () => closeDialog());

  function restoreFromCrop(crop) {
    // crop.w was itself derived as (frameSize / displayScale) /
    // naturalWidth when this crop was saved - inverting that recovers
    // the exact zoom level that produced it.
    const cropSideNatural = crop.w * naturalWidth;
    const zoom = clamp(frameSize / cropSideNatural / baseScale, MIN_ZOOM, MAX_ZOOM);
    displayScale = baseScale * zoom;
    displayWidth = naturalWidth * displayScale;
    displayHeight = naturalHeight * displayScale;
    setPan(-crop.x * naturalWidth * displayScale, -crop.y * naturalHeight * displayScale);
    zoomInput.value = String(zoom);
  }

  function openCropDialog({ file, existingCrop, onSave, onClear }) {
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }

    const objectUrl = URL.createObjectURL(file);
    currentObjectUrl = objectUrl;
    pendingOnSave = onSave;
    pendingOnClear = onClear;

    img.onload = () => {
      naturalWidth = img.naturalWidth;
      naturalHeight = img.naturalHeight;
      frameSize = frame.getBoundingClientRect().width;
      baseScale = frameSize / Math.min(naturalWidth, naturalHeight);

      if (existingCrop) {
        restoreFromCrop(existingCrop);
      } else {
        displayScale = baseScale;
        displayWidth = naturalWidth * displayScale;
        displayHeight = naturalHeight * displayScale;
        setPan((frameSize - displayWidth) / 2, (frameSize - displayHeight) / 2);
        zoomInput.value = String(MIN_ZOOM);
      }
      render();
      dialog.showModal();
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      currentObjectUrl = null;
    };
    img.src = objectUrl;
  }

  window.PrintmePhotoCrop = { openCropDialog, isImageFile };
})();
