from pathlib import Path
from unittest.mock import patch

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow
from printme.services.printing.base import PrintError

FIXTURES = Path(__file__).parent / "fixtures"


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


def make_ready_photo_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
        processed_path=str(FIXTURES / "face_one.jpg"),
        status=JobStatus.READY_FOR_REVIEW,
        total_cost=15.0,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
    return job


class TestPrintSheetFailure:
    def test_print_error_shows_flash_message_instead_of_500(self, app, client):
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)

        # Populate a real, rendered sheet the normal way.
        client.get("/admin/photo-sheets/")
        with app.app_context():
            from printme.models import PhotoSheet

            sheet_id = PhotoSheet.query.first().id

        with patch(
            "printme.routes.admin_photo_sheets._printer_backend.print_file",
            side_effect=PrintError("DCP-T420W didn't respond"),
        ):
            resp = client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "DCP-T420W"})

        assert resp.status_code == 302

        follow = client.get(resp.headers["Location"])
        assert b"Print failed" in follow.data
        assert b"DCP-T420W" in follow.data

    def test_print_error_leaves_jobs_untouched(self, app, client):
        with app.app_context():
            job = make_ready_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        client.get("/admin/photo-sheets/")
        with app.app_context():
            from printme.models import PhotoSheet

            sheet_id = PhotoSheet.query.first().id

        with patch(
            "printme.routes.admin_photo_sheets._printer_backend.print_file",
            side_effect=PrintError("no response"),
        ):
            client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "DCP-T420W"})

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.READY_FOR_REVIEW
            assert job.needs_attention is False

    def test_successful_print_still_marks_jobs_done(self, app, client):
        """Regression guard: the try/except shouldn't change the
        success path."""
        with app.app_context():
            job = make_ready_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        client.get("/admin/photo-sheets/")
        with app.app_context():
            from printme.models import PhotoSheet

            sheet_id = PhotoSheet.query.first().id

        with patch("printme.routes.admin_photo_sheets._printer_backend.print_file"):
            resp = client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "DCP-T420W"})

        assert resp.status_code == 302
        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.DONE
