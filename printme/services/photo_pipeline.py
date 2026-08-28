"""Photo job processing pipeline (CLAUDE.md): face detection -> auto-
crop/center -> background removal -> white background.

Produces ONE canonical processed photo per job (matching Job.processed_
path and the admin review UI's single before/after comparison), even
when the job requests multiple print sizes. That single image is square
and face-centered, wide enough to cover every fixed size's aspect ratio
without upscaling - the Smart Layout Engine's sheet renderer (Phase 4)
crops it down further to each requested size at print time.

needs_attention (CLAUDE.md): flags 0 or 2+ detected faces, or visible
background-removal artifacts, each with the SPECIFIC reason.
"""

from dataclasses import dataclass

from PIL import Image, ImageOps

from printme.models.job import JobStatus
from printme.services.background_removal import detect_artifacts, remove_background
from printme.services.face_detection import detect_faces
from printme.services.pricing import price_job

# The Haar cascade's face box covers roughly eyebrows-to-chin, not the
# full head - this is that face box's height as a fraction of the square
# crop's side, tuned so the crop includes hair/forehead above and
# shoulders below (typical ID-photo framing) rather than clipping the
# top of the head.
FACE_HEIGHT_RATIO = 0.33

# High enough for good print quality at any fixed size even after a
# further center-crop to a narrower target aspect ratio at render time.
# Largest kept size is 5x7 (7in long side @ 300 DPI = 2100px); for a
# square source cropped down to a narrower aspect ratio, the source
# side must be >= the target's longer dimension to avoid upscaling -
# 2100 is the exact minimum that clears every current fixed size.
CANONICAL_SIZE_PX = 2100

# A manual crop this small in its *source* pixel dimensions would need
# more than a 10x LANCZOS upscale to reach CANONICAL_SIZE_PX - visibly
# soft in a real print. Treat a crop this degenerate as if none was
# supplied at all (silent fallback to automatic), rather than printing
# a blurry photo just because the customer drew a tiny box.
MIN_MANUAL_CROP_SIDE_PX = 200


@dataclass
class PhotoProcessingResult:
    processed_path: str
    face_count: int
    needs_attention: bool
    attention_reason: str | None


def _face_count_reason(face_count):
    if face_count == 0:
        return "No face was found in the uploaded photo. Check the image before printing."
    if face_count >= 2:
        return (
            f"{face_count} faces were found in the uploaded photo. "
            "Check which person should be printed."
        )
    return None


def compute_square_crop_box(image_size, face_box=None):
    """A square (left, top, right, bottom) crop box in `image_size`,
    centered on face_box if given, else centered on the whole image.
    Square is the widest aspect ratio among the fixed sizes, so it can
    always be further center-cropped down to any of them later without
    needing to upscale/pad in either dimension."""
    img_w, img_h = image_size
    side = min(img_w, img_h)

    if face_box is not None:
        fx, fy, fw, fh = face_box
        cx, cy = fx + fw / 2, fy + fh / 2
        side = min(fh / FACE_HEIGHT_RATIO, img_w, img_h)
    else:
        cx, cy = img_w / 2, img_h / 2

    left, right = _clamp_span(cx - side / 2, cx + side / 2, img_w)
    top, bottom = _clamp_span(cy - side / 2, cy + side / 2, img_h)
    return (round(left), round(top), round(right), round(bottom))


def _clamp_span(start, end, limit):
    span = end - start
    if start < 0:
        start, end = 0, span
    if end > limit:
        start, end = limit - span, limit
    return start, end


def compute_manual_crop_box(image_size, crop_fractions):
    """A square (left, top, right, bottom) crop box in `image_size`,
    centered on the customer-supplied crop_fractions (x, y, w, h - all
    0-1, from manual_crop.parse_crop_fractions). Mirrors
    compute_square_crop_box: the customer's frame is UI-constrained to
    be square, but fractions are trusted input from the wire, not the
    box itself, so this still derives a square side (the smaller of the
    fraction box's own width/height) rather than assuming w == h.
    Returns None if that side is smaller than MIN_MANUAL_CROP_SIDE_PX -
    callers must treat that exactly like no manual crop was supplied.
    """
    img_w, img_h = image_size
    x, y, w, h = crop_fractions

    px_w, px_h = w * img_w, h * img_h
    cx, cy = (x * img_w) + px_w / 2, (y * img_h) + px_h / 2
    side = min(px_w, px_h, img_w, img_h)
    if side < MIN_MANUAL_CROP_SIDE_PX:
        return None

    left, right = _clamp_span(cx - side / 2, cx + side / 2, img_w)
    top, bottom = _clamp_span(cy - side / 2, cy + side / 2, img_h)
    return (round(left), round(top), round(right), round(bottom))


def process_photo_job(
    session, job, source_image_path, processed_dir, manual_crop_fractions=None
):
    """Run the full pipeline for one photo Job and persist the result:
    Job.processed_path, needs_attention/attention_reason, and status ->
    ready_for_review. The caller is expected to have already moved the
    job to `processing` before calling this (this function owns the
    processing step itself, not the "processing has started" marker).

    manual_crop_fractions (optional): an (x, y, w, h) tuple from
    manual_crop.parse_crop_fractions - a customer-drawn crop to use
    instead of the automatic face-centered one. Face detection always
    runs regardless (needs_attention's 0/2+-face check is about the
    source photo's content, not which crop path was used). A missing
    or degenerate manual crop silently falls back to automatic.

    On an unrecoverable processing error, the job is flagged and moved
    to `failed` instead of raising - a photo job that can't be processed
    is exactly the kind of thing staff must not lose track of.
    """
    try:
        faces = detect_faces(source_image_path)
        face_count = len(faces)
        face_box = faces[0] if face_count == 1 else None

        with Image.open(source_image_path) as src:
            src = src.convert("RGB")

            manual_box = None
            transposed = None
            if manual_crop_fractions is not None:
                # Browsers auto-rotate the <img> preview per EXIF
                # orientation for display - everything the customer
                # dragged/zoomed against is in that rotated space, so
                # the crop must be applied there too. detect_faces()
                # (cv2.imread) never auto-rotates, so face_box stays in
                # raw space and the automatic fallback below must keep
                # using the untransposed `src`, not this one.
                transposed = ImageOps.exif_transpose(src)
                manual_box = compute_manual_crop_box(
                    transposed.size, manual_crop_fractions
                )

            if manual_box is not None:
                crop_source, box = transposed, manual_box
                job.processed_source = "manual"
            else:
                crop_source = src
                box = compute_square_crop_box(src.size, face_box)
                job.processed_source = "auto"

            cropped = crop_source.crop(box).resize(
                (CANONICAL_SIZE_PX, CANONICAL_SIZE_PX), Image.LANCZOS
            )

            out_path = processed_dir / f"job{job.id}.png"
            alpha = remove_background(cropped, out_path)

        reason = _face_count_reason(face_count)
        if reason is None:
            artifact_reasons = detect_artifacts(alpha)
            reason = artifact_reasons[0] if artifact_reasons else None

        job.processed_path = str(out_path)
        if reason:
            job.flag_for_attention(reason)
        else:
            job.clear_attention()
        job.status = JobStatus.READY_FOR_REVIEW
        price_job(session, job)

        return PhotoProcessingResult(
            processed_path=str(out_path),
            face_count=face_count,
            needs_attention=bool(reason),
            attention_reason=reason,
        )
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.flag_for_attention(f"Photo processing failed: {exc}. Try re-uploading.")
        session.commit()
        raise
