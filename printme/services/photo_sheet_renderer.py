"""Render a persisted PhotoSheet as a preview PNG: each item's owning
job's canonical processed photo, center-cropped down to that item's
specific fixed size, placed at its packed position, with cutting-guide
grid lines - what the admin previews before printing a batch.
"""

from pathlib import Path

from PIL import Image, ImageDraw

from printme.layout_engine.render import render_sheet
from printme.layout_engine.sizes import PHOTO_SIZES_PX
from printme.layout_engine.types import PackedSheet, PlacedItem
from printme.models.job import Job

MISSING_PHOTO_OUTLINE = "red"
GRID_LINE_COLOR = "black"
MARGIN_OUTLINE_COLOR = "#999999"


def _to_packed_sheet(photo_sheet):
    """Rebuild the layout_engine PackedSheet a PhotoSheet row was
    created from, so render_sheet()'s grid-line math can be reused
    rather than duplicated here."""
    return PackedSheet(
        sheet_index=photo_sheet.sheet_number,
        width=photo_sheet.width_px,
        height=photo_sheet.height_px,
        margin=photo_sheet.margin_px,
        items=tuple(
            PlacedItem(
                item_id=item.item_key,
                size_name=item.size_name,
                x=item.x_px,
                y=item.y_px,
                width=item.width_px,
                height=item.height_px,
                rotated=item.rotated,
            )
            for item in photo_sheet.items
        ),
    )


def _center_crop_to_aspect(image, target_w, target_h):
    """The largest centered box of the target aspect ratio that fits
    inside `image`, without upscaling in either dimension."""
    img_w, img_h = image.size
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h

    if img_ratio > target_ratio:
        new_w = round(img_h * target_ratio)
        left = (img_w - new_w) // 2
        box = (left, 0, left + new_w, img_h)
    else:
        new_h = round(img_w / target_ratio)
        top = (img_h - new_h) // 2
        box = (0, top, img_w, top + new_h)
    return image.crop(box)


def _fitted_photo_for_item(job, item):
    """job's canonical processed photo, cropped/resized/rotated to
    exactly fill this placed item's (width_px, height_px) footprint."""
    target_w, target_h = PHOTO_SIZES_PX[item.size_name]  # pre-rotation size

    with Image.open(job.processed_path) as photo:
        fitted = _center_crop_to_aspect(photo, target_w, target_h)
        fitted = fitted.resize((target_w, target_h), Image.LANCZOS)
        if item.rotated:
            fitted = fitted.rotate(90, expand=True)
        return fitted.copy()  # detach from the `with`-closed file handle


def render_photo_sheet(session, photo_sheet, out_path):
    """Composite every item on `photo_sheet` onto a full A4 canvas and
    save it to out_path. A job whose processed photo is missing (not
    yet processed, or already cleaned up) gets a red placeholder outline
    instead of failing the whole sheet - one bad item shouldn't block
    staff from previewing everything else that's ready."""
    sheet_render = render_sheet(_to_packed_sheet(photo_sheet))

    canvas = Image.new("RGB", (photo_sheet.width_px, photo_sheet.height_px), "white")
    draw = ImageDraw.Draw(canvas)

    for item in photo_sheet.items:
        job = session.get(Job, item.job_id)
        box = (item.x_px, item.y_px, item.x_px + item.width_px, item.y_px + item.height_px)

        if job is None or not job.processed_path or not Path(job.processed_path).exists():
            draw.rectangle(box, outline=MISSING_PHOTO_OUTLINE, width=3)
            continue

        fitted = _fitted_photo_for_item(job, item)
        canvas.paste(fitted, (item.x_px, item.y_px))

    for line in sheet_render.grid_lines:
        draw.line([line.x1, line.y1, line.x2, line.y2], fill=GRID_LINE_COLOR, width=2)

    draw.rectangle(
        [
            sheet_render.usable_x,
            sheet_render.usable_y,
            sheet_render.usable_x + sheet_render.usable_width,
            sheet_render.usable_y + sheet_render.usable_height,
        ],
        outline=MARGIN_OUTLINE_COLOR,
        width=2,
    )

    canvas.save(out_path)
    return out_path
