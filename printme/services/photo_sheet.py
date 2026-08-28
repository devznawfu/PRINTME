"""Persist Smart Layout Engine output as PhotoSheet / PhotoSheetItem rows."""

import uuid

from printme.layout_engine.packer import pack
from printme.layout_engine.types import PackedSheet
from printme.models.job import Job, JobStatus
from printme.models.photo_sheet import PhotoSheet, PhotoSheetItem


def record_packing_result(session, packed_sheets, item_to_job):
    """Store pack() output as one batch of PhotoSheets.

    `packed_sheets` is the list[PackedSheet] returned by
    printme.layout_engine.pack(); `item_to_job` maps each placement's
    item_id to its owning Job id - the caller built those items from job
    rows, so it owns this mapping.

    Returns the new batch_id.
    """
    if not packed_sheets:
        raise ValueError("packed_sheets must not be empty")

    for sheet in packed_sheets:
        if not isinstance(sheet, PackedSheet):
            raise TypeError(f"expected PackedSheet, got {type(sheet).__name__}")
        for placed in sheet.items:
            if placed.item_id not in item_to_job:
                raise ValueError(
                    f"no job mapping for placement {placed.item_id!r} - "
                    "the caller must map every packed item_id to a Job id"
                )

    batch_id = uuid.uuid4().hex
    for sheet in packed_sheets:
        photo_sheet = PhotoSheet(
            batch_id=batch_id,
            sheet_number=sheet.sheet_index,
            width_px=sheet.width,
            height_px=sheet.height,
            margin_px=sheet.margin,
        )
        for placed in sheet.items:
            photo_sheet.items.append(
                PhotoSheetItem(
                    job_id=item_to_job[placed.item_id],
                    item_key=placed.item_id,
                    size_name=placed.size_name,
                    x_px=placed.x,
                    y_px=placed.y,
                    width_px=placed.width,
                    height_px=placed.height,
                    rotated=placed.rotated,
                )
            )
        session.add(photo_sheet)

    session.commit()
    return batch_id


def _latest_batch_item_ids(session):
    """(batch_id, item_ids) for the most recently created batch, or
    (None, set()) if no batch has ever been packed. item_ids are the
    expanded per-print keys (e.g. "job12-row3-7", one per copy - see
    PhotoItemRow.to_layout_items), not job ids - see pack_pending_
    photo_jobs's docstring for why that distinction matters."""
    latest = (
        session.query(PhotoSheet.batch_id)
        .order_by(PhotoSheet.id.desc())
        .first()
    )
    if latest is None:
        return None, set()

    batch_id = latest[0]
    item_ids = {
        row.item_key
        for row in session.query(PhotoSheetItem.item_key)
        .join(PhotoSheet)
        .filter(PhotoSheet.batch_id == batch_id)
    }
    return batch_id, item_ids


def pack_pending_photo_jobs(session):
    """Gather every ready-for-review, unflagged photo job's requested
    prints, pack them onto the minimum number of A4 sheets, and persist
    the result. Flagged jobs are excluded - CLAUDE.md: never auto-print
    a flagged job before staff have reviewed it; once approved, staff
    clear the flag and it's picked up by the next pack.

    Idempotent: if the exact set of individual prints requested (one
    entry per copy) is unchanged since the last pack, the existing
    batch is reused instead of repacking - this is called on every
    admin page load, so without this a page refresh would otherwise
    mint a fresh duplicate batch each time.

    This compares the expanded per-print id set, not just which job ids
    are pending - comparing job ids alone (a real bug an earlier version
    of this function had) missed the case where a job already in the
    pending set has its own quantity changed after being packed, e.g.
    an admin qty increment on an already-packed job: the job SET stays
    identical even though what it's asking for grew, so the stale batch
    got silently reused and the extra prints never made it onto any
    sheet - the job row itself showed the new quantity, but nothing
    was ever queued to print it.

    Returns the batch_id (new or reused), or None if there was nothing
    to pack.
    """
    jobs = (
        session.query(Job)
        .filter(
            Job.service_type == "photo",
            Job.status == JobStatus.READY_FOR_REVIEW,
            Job.needs_attention.is_(False),
        )
        .all()
    )

    if not jobs:
        return None

    item_to_job = {}
    items = []
    for job in jobs:
        for row in job.photo_items:
            for layout_item in row.to_layout_items():
                items.append(layout_item)
                item_to_job[layout_item.item_id] = job.id

    if not items:
        return None

    latest_batch_id, latest_item_ids = _latest_batch_item_ids(session)
    if {item.item_id for item in items} == latest_item_ids:
        return latest_batch_id

    packed_sheets = pack(items)
    return record_packing_result(session, packed_sheets, item_to_job)
