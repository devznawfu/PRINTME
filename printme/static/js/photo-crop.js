// Manual photo-crop tool for the customer upload portal (per-photo, not
// per-batch): a fixed square frame, drag-to-pan and two-finger pinch-
// to-zoom via the Pointer Events API (unifies mouse/touch/pen in one
// code path - tracking up to two simultaneous pointers by id is still
// far simpler and more robust than the touch-event-specific gesture
// APIs), plus a zoom slider staying in sync either way. The one
// deliberate exception to this app's zero-global-JS convention:
// window.PrintmePhotoCrop, since upload-form.js's file list and this
// dialog genuinely need to cooperate (which file is being cropped,
// what crop it already has).
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
  // A fresh crop starts a little zoomed in, not sitting exactly at
  // MIN_ZOOM. At MIN_ZOOM the image is scaled to *just barely* cover
  // the square frame ("cover" fit) - for any photo whose aspect ratio
  // is close to square (very common for face/ID photos), that leaves
  // zero or near-zero room to drag until the zoom slider is touched
  // first. Dragging then visibly does nothing, which reads as "the
  // crop tool is broken" rather than "zoom in first" - starting with
  // guaranteed slack in both directions avoids that trap entirely.
  const DEFAULT_START_ZOOM = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, 1.15));

  let currentObjectUrl = null;
  let pendingOnSave = null;
  let pendingOnClear = null;
  let dragState = null;
  // pointerId -> {x, y} (viewport coords) for every pointer currently
  // down on the frame - up to 2 tracked; a 3rd is simply ignored.
  const activePointers = new Map();
  let pinchState = null; // {startDistance, startZoom} while 2 pointers are down

  // Geometry for the file currently loaded into the dialog. Recomputed
  // fresh every time openCropDialog() runs.
  let naturalWidth = 0;
  let naturalHeight = 0;
  let frameSize = 0;
  let frameLeft = 0; // viewport position, cached alongside frameSize - the
  let frameTop = 0; // dialog is modal and doesn't move during one session
  let baseScale = 1; // scale at zoom=1: the image's SHORTER side exactly fills the frame ("cover" fit)
  let displayScale = 1; // baseScale * current zoom
  let currentZoom = 1;
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
    currentZoom = zoom;
    const anchorFrameX = anchorX === undefined ? frameSize / 2 : anchorX;
    const anchorFrameY = anchorY === undefined ? frameSize / 2 : anchorY;
    // Keep whichever image content sits under the anchor point fixed in
    // place while the zoom level changes, instead of always zooming
    // from the image's top-left corner. For pinch, the anchor is the
    // gesture's own centroid, so the image tracks both fingers as it
    // scales - not the whole point of the "anchor" parameter's design,
    // but exactly what it was already built to do.
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
    pinchState = null;
    activePointers.clear();
  });

  function startSingleDrag(pointerId, clientX, clientY) {
    pinchState = null;
    dragState = { pointerId, startClientX: clientX, startClientY: clientY, startPanX: panX, startPanY: panY };
  }

  function pointerDistance(p1, p2) {
    return Math.hypot(p1.x - p2.x, p1.y - p2.y);
  }

  function pointerCentroidInFrame(p1, p2) {
    return { x: (p1.x + p2.x) / 2 - frameLeft, y: (p1.y + p2.y) / 2 - frameTop };
  }

  frame.addEventListener("pointerdown", (e) => {
    frame.setPointerCapture(e.pointerId);
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    e.preventDefault();

    if (activePointers.size === 2) {
      // A second finger landed mid-drag: stop panning, start pinching.
      dragState = null;
      const [p1, p2] = Array.from(activePointers.values());
      pinchState = { startDistance: pointerDistance(p1, p2), startZoom: currentZoom };
    } else if (activePointers.size === 1) {
      startSingleDrag(e.pointerId, e.clientX, e.clientY);
    }
    // A 3rd simultaneous pointer is simply ignored - not tracked, not
    // captured, doesn't disturb whatever 2-finger pinch is already
    // in progress.
  });

  frame.addEventListener("pointermove", (e) => {
    if (!activePointers.has(e.pointerId)) return;
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pinchState && activePointers.size >= 2) {
      const [p1, p2] = Array.from(activePointers.values());
      const distance = pointerDistance(p1, p2);
      if (distance > 0 && pinchState.startDistance > 0) {
        const centroid = pointerCentroidInFrame(p1, p2);
        setZoom((distance / pinchState.startDistance) * pinchState.startZoom, centroid.x, centroid.y);
        zoomInput.value = String(currentZoom);
      }
      return;
    }

    if (dragState && e.pointerId === dragState.pointerId) {
      const dx = e.clientX - dragState.startClientX;
      const dy = e.clientY - dragState.startClientY;
      setPan(dragState.startPanX + dx, dragState.startPanY + dy);
      render();
    }
  });

  function endDrag(e) {
    activePointers.delete(e.pointerId);
    if (dragState && e.pointerId === dragState.pointerId) dragState = null;

    if (activePointers.size === 1) {
      // Dropped from 2 fingers to 1 (or a stray extra pointer lifted) -
      // restart the pan anchor from the remaining finger's CURRENT
      // position, so single-finger drag doesn't jump using a start
      // point from before the pinch began.
      const [[remainingId, pos]] = Array.from(activePointers.entries());
      startSingleDrag(remainingId, pos.x, pos.y);
    } else if (activePointers.size === 0) {
      pinchState = null;
      dragState = null;
    }
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
    currentZoom = zoom;
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

      // showModal() MUST happen before measuring the frame: a native
      // <dialog> is `display: none` until shown, so anything inside it
      // (including this frame) has a zero-sized layout box beforehand -
      // reading getBoundingClientRect() any earlier silently produces
      // frameSize=0, which cascades into a 0x0 image (invisible, just
      // the frame's own background color showing through).
      dialog.showModal();

      const rect = frame.getBoundingClientRect();
      frameSize = rect.width;
      frameLeft = rect.left;
      frameTop = rect.top;
      baseScale = frameSize / Math.min(naturalWidth, naturalHeight);

      if (existingCrop) {
        restoreFromCrop(existingCrop);
      } else {
        currentZoom = DEFAULT_START_ZOOM;
        displayScale = baseScale * DEFAULT_START_ZOOM;
        displayWidth = naturalWidth * displayScale;
        displayHeight = naturalHeight * displayScale;
        setPan((frameSize - displayWidth) / 2, (frameSize - displayHeight) / 2);
        zoomInput.value = String(DEFAULT_START_ZOOM);
      }
      render();
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      currentObjectUrl = null;
    };
    img.src = objectUrl;
  }

  window.PrintmePhotoCrop = { openCropDialog, isImageFile };
})();
