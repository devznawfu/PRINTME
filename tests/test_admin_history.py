from pathlib import Path
from unittest.mock import patch

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults

FIXTURES = Path(__file__).parent / "fixtures"


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


def make_terminal_photo_job(app, status, ticket="P-001", processed_path=None):
    processed = processed_path or str(FIXTURES / "face_one.jpg")
    job = Job(
        ticket_number=ticket,
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
        processed_path=processed,
        status=status,
        total_cost=15.0,
    )
    job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=2))
    if status == JobStatus.CANCELLED:
        job.attention_reason = "Cancelled by staff"
    if status == JobStatus.FAILED:
        job.flag_for_attention("Something went wrong")
    return job


def make_terminal_document_job(app, status, ticket="P-002", processed_path=None):
    processed = processed_path or str(FIXTURES / "face_one.jpg")
    job = Job(
        ticket_number=ticket,
        customer_name="Ben",
        service_type="document",
        original_filename="form.pdf",
        upload_path=str(FIXTURES / "face_one.jpg"),
        processed_path=processed,
        status=status,
        color_mode="bw",
        page_count=3,
        copies=2,
        total_cost=30.0,
    )
    if status == JobStatus.CANCELLED:
        job.attention_reason = "Cancelled by staff"
    if status == JobStatus.FAILED:
        job.flag_for_attention("Something went wrong")
    return job


class TestHistoryRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/history/")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_lists_only_terminal_jobs(self, app, client):
        with app.app_context():
            done = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            cancelled = make_terminal_document_job(app, JobStatus.CANCELLED, ticket="P-002")
            failed = make_terminal_photo_job(app, JobStatus.FAILED, ticket="P-003")
            active = make_terminal_document_job(app, JobStatus.READY_FOR_REVIEW, ticket="P-004")
            db.session.add_all([done, cancelled, failed, active])
            db.session.commit()
        login(client)

        resp = client.get("/admin/history/")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "P-001" in body
        assert "P-002" in body
        assert "P-003" in body
        assert "P-004" not in body


class TestRestoreRoute:
    def test_requires_admin_login(self, client):
        resp = client.post("/admin/jobs/1/restore")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_restore_photo_job_creates_new_job_with_new_ticket(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id

            # P-001 is free again the instant `old` leaves the active
            # set - occupy it with an unrelated active job so this test
            # actually proves restore goes through normal fresh-ticket
            # allocation rather than reusing old.ticket_number verbatim
            # (which would otherwise collide, or - if it just happened
            # to pass silently - prove nothing).
            blocker = make_terminal_photo_job(
                app, JobStatus.READY_FOR_REVIEW, ticket="P-001"
            )
            db.session.add(blocker)
            db.session.commit()
        login(client)

        with (
            patch("printme.services.photo_pipeline.process_photo_job") as mock_photo,
            patch("printme.services.document_pipeline.process_document_job") as mock_doc,
        ):
            resp = client.post(f"/admin/jobs/{old_id}/restore")

        assert resp.status_code == 302
        mock_photo.assert_not_called()
        mock_doc.assert_not_called()

        with app.app_context():
            new_job = (
                Job.query.filter(Job.id != old_id).order_by(Job.id.desc()).first()
            )
            assert new_job is not None
            assert new_job.ticket_number != "P-001"
            assert new_job.status == JobStatus.READY_FOR_REVIEW
            assert new_job.needs_attention is False
            assert new_job.customer_name == "Maria"
            assert new_job.service_type == "photo"
            assert [r.size_name for r in new_job.photo_items] == ["2x2"]
            assert new_job.photo_items[0].quantity == 2
            assert new_job.total_cost is not None
            # upload_path must be a fresh copy, not the shared processed
            # file - otherwise the 2-day sweep could take it out.
            assert new_job.upload_path != new_job.processed_path
            assert Path(new_job.upload_path).exists()
            assert new_job.processed_path == str(FIXTURES / "face_one.jpg")

    def test_restore_document_job_copies_print_options(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_document_job(app, JobStatus.CANCELLED, ticket="P-002")
            db.session.add(old)
            db.session.commit()
            old_id = old.id
        login(client)

        resp = client.post(f"/admin/jobs/{old_id}/restore")

        assert resp.status_code == 302
        with app.app_context():
            new_job = (
                Job.query.filter(Job.id != old_id).order_by(Job.id.desc()).first()
            )
            assert new_job.service_type == "document"
            assert new_job.color_mode == "bw"
            assert new_job.page_count == 3
            assert new_job.copies == 2
            assert new_job.status == JobStatus.READY_FOR_REVIEW
            assert new_job.total_cost is not None

    def test_restore_with_missing_file_shows_error_and_creates_no_job(self, app, client, tmp_path):
        with app.app_context():
            ghost = tmp_path / "gone.jpg"  # never created
            old = make_terminal_photo_job(
                app, JobStatus.DONE, ticket="P-001", processed_path=str(ghost)
            )
            db.session.add(old)
            db.session.commit()
            old_id = old.id
            jobs_before = Job.query.count()
        login(client)

        resp = client.post(f"/admin/jobs/{old_id}/restore", follow_redirects=True)

        assert resp.status_code == 200
        assert b"no longer on disk" in resp.data
        with app.app_context():
            assert Job.query.count() == jobs_before

    def test_missing_job_redirects_without_error(self, client):
        login(client)
        resp = client.post("/admin/jobs/999999/restore")
        assert resp.status_code == 302
