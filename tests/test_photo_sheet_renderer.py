from pathlib import Path

from PIL import Image

from printme.extensions import db
from printme.layout_engine import sizes
from printme.models import Job, JobStatus, PhotoItemRow, PhotoSheet, seed_defaults
from printme.services.photo_pipeline import process_photo_job
from printme.services.photo_sheet import pack_pending_photo_jobs
from printme.services.photo_sheet_renderer import render_photo_sheet

FIXTURES = Path(__file__).parent / "fixtures"


def make_processed_photo_job(session, tmp_path, ticket="P-001", size_name="2x2", quantity=1):
    """A job that's gone through the REAL photo pipeline (face detection
    + rembg), so it has a real processed_path to render from."""
    seed_defaults(session)
    job = Job(
        ticket_number=ticket,
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
    )
    job.photo_items.append(PhotoItemRow(size_name=size_name, quantity=quantity))
    session.add(job)
    session.commit()

    process_photo_job(session, job, FIXTURES / "face_one.jpg", tmp_path)
    assert job.status == JobStatus.READY_FOR_REVIEW
    assert job.needs_attention is False
    return job


class TestRenderPhotoSheet:
    def test_renders_full_a4_canvas_with_a_real_photo_pasted_in(self, app, tmp_path):
        with app.app_context():
            make_processed_photo_job(db.session, tmp_path, size_name="2x2")
            batch_id = pack_pending_photo_jobs(db.session)
            sheet = PhotoSheet.query.filter_by(batch_id=batch_id).first()

            out_path = tmp_path / "sheet-01.png"
            render_photo_sheet(db.session, sheet, out_path)

            assert out_path.exists()
            with Image.open(out_path) as img:
                assert img.size == (sizes.A4_WIDTH_PX, sizes.A4_HEIGHT_PX)

                item = sheet.items[0]
                center = (
                    item.x_px + item.width_px // 2,
                    item.y_px + item.height_px // 2,
                )
                # Somewhere in the middle of a real face photo shouldn't
                # be pure white (that would mean nothing got pasted).
                assert img.getpixel(center) != (255, 255, 255)

    def test_renders_a_rotated_item_at_its_swapped_footprint(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            # Enough Passports that at least one gets rotated by the
            # packer (same batch size test_packer.py's rotation test uses).
            job = Job(
                ticket_number="P-001",
                customer_name="Maria",
                service_type="photo",
                original_filename="photo.jpg",
                upload_path=str(FIXTURES / "face_one.jpg"),
            )
            job.photo_items.append(PhotoItemRow(size_name="Passport", quantity=40))
            db.session.add(job)
            db.session.commit()
            process_photo_job(db.session, job, FIXTURES / "face_one.jpg", tmp_path)

            batch_id = pack_pending_photo_jobs(db.session)
            sheets = PhotoSheet.query.filter_by(batch_id=batch_id).all()

            rendered_any_rotated = False
            for i, sheet in enumerate(sheets):
                out_path = tmp_path / f"sheet-{i}.png"
                render_photo_sheet(db.session, sheet, out_path)
                assert out_path.exists()
                if any(item.rotated for item in sheet.items):
                    rendered_any_rotated = True

            assert rendered_any_rotated, "expected at least one rotated Passport in this batch"

    def test_missing_processed_photo_draws_placeholder_without_crashing(self, app, tmp_path):
        with app.app_context():
            job = Job(
                ticket_number="P-001",
                customer_name="Maria",
                service_type="photo",
                original_filename="photo.jpg",
                upload_path=str(FIXTURES / "face_one.jpg"),
                status=JobStatus.READY_FOR_REVIEW,
                processed_path=str(tmp_path / "never_created.png"),
            )
            job.photo_items.append(PhotoItemRow(size_name="1x1", quantity=1))
            db.session.add(job)
            db.session.commit()

            batch_id = pack_pending_photo_jobs(db.session)
            sheet = PhotoSheet.query.filter_by(batch_id=batch_id).first()

            out_path = tmp_path / "sheet-01.png"
            render_photo_sheet(db.session, sheet, out_path)  # must not raise
            assert out_path.exists()
