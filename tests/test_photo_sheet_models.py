"""Tests for PhotoSheet/PhotoSheetItem persistence of pack() output.

Builds real packing results through the actual layout engine (Job ->
PhotoItemRow -> to_layout_items() -> pack()) so the whole intended data
path is exercised, not hand-built fixtures.
"""

import pytest

from printme.extensions import db
from printme.layout_engine.packer import pack
from printme.models import (
    Job,
    PhotoItemRow,
    PhotoSheet,
    PhotoSheetItem,
)
from printme.services.photo_sheet import record_packing_result


def seed_photo_job(ticket="P-001", size_name="2x2", quantity=4):
    job = Job(
        ticket_number=ticket,
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path="/uploads/photo.jpg",
    )
    job.photo_items.append(PhotoItemRow(size_name=size_name, quantity=quantity))
    db.session.add(job)
    db.session.commit()
    return job


def pack_job(job):
    """Expand a job's requested prints and run them through the real
    packer. Returns (packed_sheets, item_to_job)."""
    items = [
        item
        for row in job.photo_items
        for item in row.to_layout_items()
    ]
    packed_sheets = pack(items)
    item_to_job = {item.item_id: job.id for item in items}
    return packed_sheets, item_to_job


class TestRecordPackingResult:
    def test_persists_batch_with_correct_sheet_count(self, app):
        with app.app_context():
            job = seed_photo_job(quantity=30)  # forces multiple sheets
            sheets, item_to_job = pack_job(job)

            batch_id = record_packing_result(db.session, sheets, item_to_job)

            stored = (
                PhotoSheet.query.filter_by(batch_id=batch_id)
                .order_by(PhotoSheet.sheet_number)
                .all()
            )
            assert len(stored) == len(sheets)
            assert [s.sheet_number for s in stored] == list(range(len(sheets)))
            assert all(s.rendered_path is None for s in stored)

    def test_geometry_round_trips_verbatim(self, app):
        with app.app_context():
            job = seed_photo_job(size_name="Passport", quantity=10)
            sheets, item_to_job = pack_job(job)

            batch_id = record_packing_result(db.session, sheets, item_to_job)

            stored_items = (
                PhotoSheetItem.query.join(PhotoSheet)
                .filter(PhotoSheet.batch_id == batch_id)
                .all()
            )
            placed_by_key = {
                p.item_id: p for s in sheets for p in s.items
            }
            assert len(stored_items) == len(placed_by_key)

            for stored in stored_items:
                placed = placed_by_key[stored.item_key]
                assert stored.size_name == placed.size_name
                assert stored.x_px == placed.x
                assert stored.y_px == placed.y
                assert stored.width_px == placed.width
                assert stored.height_px == placed.height
                assert stored.rotated == placed.rotated

    def test_items_link_to_their_owning_job(self, app):
        with app.app_context():
            jobs = [seed_photo_job(ticket=f"P-{n:03d}", quantity=1) for n in (1, 2)]

            all_items = []
            item_to_job = {}
            for job in jobs:
                items = [
                    i for row in job.photo_items for i in row.to_layout_items()
                ]
                all_items.extend(items)
                item_to_job.update({i.item_id: job.id for i in items})
            sheets = pack(all_items)

            batch_id = record_packing_result(db.session, sheets, item_to_job)

            stored_jobs = {
                i.item_key: i.job_id
                for i in PhotoSheetItem.query.join(PhotoSheet)
                .filter(PhotoSheet.batch_id == batch_id)
            }
            assert stored_jobs == item_to_job

    def test_unknown_item_mapping_raises(self, app):
        with app.app_context():
            job = seed_photo_job(quantity=1)
            sheets, _ = pack_job(job)

            with pytest.raises(ValueError, match="no job mapping"):
                record_packing_result(db.session, sheets, {})

    def test_empty_batch_rejected(self, app):
        with app.app_context():
            with pytest.raises(ValueError, match="must not be empty"):
                record_packing_result(db.session, [], {})

    def test_non_packedsheet_input_rejected(self, app):
        with app.app_context():
            with pytest.raises(TypeError, match="expected PackedSheet"):
                record_packing_result(db.session, ["not-a-sheet"], {})


class TestBatches:
    def test_two_batches_coexist_and_query_independently(self, app):
        with app.app_context():
            batch_ids = []
            for ticket in ("P-001", "P-002"):
                job = seed_photo_job(ticket=ticket, quantity=5)
                sheets, item_to_job = pack_job(job)
                batch_ids.append(
                    record_packing_result(db.session, sheets, item_to_job)
                )

            assert len(set(batch_ids)) == 2  # distinct batches

            first = PhotoSheet.query.filter_by(batch_id=batch_ids[0]).all()
            second = PhotoSheet.query.filter_by(batch_id=batch_ids[1]).all()

            first_keys = {i.item_key for s in first for i in s.items}
            second_keys = {i.item_key for s in second for i in s.items}
            assert first_keys.isdisjoint(second_keys)

    def test_cascade_delete_removes_items(self, app):
        with app.app_context():
            job = seed_photo_job(quantity=3)
            sheets, item_to_job = pack_job(job)
            batch_id = record_packing_result(db.session, sheets, item_to_job)

            sheet = PhotoSheet.query.filter_by(batch_id=batch_id).first()
            sheet_id = sheet.id
            db.session.delete(sheet)
            db.session.commit()

            assert PhotoSheetItem.query.filter_by(sheet_id=sheet_id).count() == 0
            remaining = PhotoSheet.query.filter_by(batch_id=batch_id).count()
            assert remaining == len(sheets) - 1
