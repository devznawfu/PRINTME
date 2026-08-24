"""Persistence for Smart Layout Engine output.

One PhotoSheet row per packed A4 sheet, one PhotoSheetItem per placed
photo. Distinct from PhotoItemRow (job.py), which stores a job's
REQUESTED prints (size + quantity) - these models store the RESULT of
packing those requests onto sheets.
"""

from datetime import datetime, timezone

from printme.extensions import db


class PhotoSheet(db.Model):
    __tablename__ = "photo_sheets"

    id = db.Column(db.Integer, primary_key=True)

    # Groups sheets produced by one pack() call; lets the pipeline
    # replace a whole batch when layouts are regenerated.
    batch_id = db.Column(db.String(32), nullable=False, index=True)
    sheet_number = db.Column(db.Integer, nullable=False)  # 0-based order in batch

    # Copied from PackedSheet so rendering never depends on recomputing
    # layout_engine constants.
    width_px = db.Column(db.Integer, nullable=False)
    height_px = db.Column(db.Integer, nullable=False)
    margin_px = db.Column(db.Integer, nullable=False)

    # PNG path once services/photo_sheet_renderer.py exists.
    rendered_path = db.Column(db.String(500))

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    items = db.relationship(
        "PhotoSheetItem",
        back_populates="sheet",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class PhotoSheetItem(db.Model):
    __tablename__ = "photo_sheet_items"

    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(
        db.Integer, db.ForeignKey("photo_sheets.id"), nullable=False, index=True
    )

    # Ownership: every placement belongs to a photo job. item_key is the
    # PlacedItem.item_id the packer emitted (e.g. "job3-row1-2") - the
    # trace-back key from printme/layout_engine/types.py.
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True
    )
    item_key = db.Column(db.String(64), nullable=False)

    size_name = db.Column(db.String(16), nullable=False)
    x_px = db.Column(db.Integer, nullable=False)
    y_px = db.Column(db.Integer, nullable=False)
    width_px = db.Column(db.Integer, nullable=False)
    height_px = db.Column(db.Integer, nullable=False)
    rotated = db.Column(db.Boolean, nullable=False, default=False)

    sheet = db.relationship("PhotoSheet", back_populates="items")
