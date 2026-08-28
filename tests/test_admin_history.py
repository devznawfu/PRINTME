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

    def test_restore_flashes_a_visible_success_message(self, app, client):
        """Regression: restore() used to redirect silently on success -
        the row looked completely untouched, giving staff no sign
        anything happened (they'd have to go check the main queue).
        Now it flashes what ticket the job was restored as, styled as
        success (ok-* tokens), not lumped in with error styling."""
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id
        login(client)

        with patch("printme.services.photo_pipeline.process_photo_job"):
            resp = client.post(f"/admin/jobs/{old_id}/restore", follow_redirects=True)

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Restored P-001 as" in body
        assert "now in the print queue" in body
        assert "bg-ok-bg" in body  # success styling, not the error banner

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
        body = resp.get_data(as_text=True)
        assert "bg-err-bg" in body
        assert "bg-ok-bg" not in body  # a failure must never render as success
        with app.app_context():
            assert Job.query.count() == jobs_before

    def test_missing_job_redirects_without_error(self, client):
        login(client)
        resp = client.post("/admin/jobs/999999/restore")
        assert resp.status_code == 302


class TestReprintRoute:
    def test_requires_admin_login(self, client):
        resp = client.post("/admin/jobs/1/reprint", data={"reprint_reason": "bad_print"})
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_reprint_photo_job_defaults_to_zero_cost(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            old.paper_finish = "glossy"
            old.quality = "high"
            db.session.add(old)
            db.session.commit()
            old_id = old.id

        login(client)
        resp = client.post(
            f"/admin/jobs/{old_id}/reprint",
            data={"reprint_reason": "bad_print"},
        )

        assert resp.status_code == 302
        with app.app_context():
            new_job = Job.query.filter(Job.id != old_id).order_by(Job.id.desc()).first()
            assert new_job is not None
            assert new_job.reprint_of == old_id
            assert new_job.reprint_reason == "bad_print"
            assert new_job.status == JobStatus.READY_FOR_REVIEW
            assert new_job.total_cost == 0.0
            assert new_job.paper_finish == "glossy"
            assert new_job.quality == "high"
            assert [r.size_name for r in new_job.photo_items] == ["2x2"]
            assert new_job.display_ticket == "P-001-R"
            # Same aliasing protection as restore(): a fresh upload_path copy.
            assert new_job.upload_path != new_job.processed_path
            assert Path(new_job.upload_path).exists()

    def test_charge_normally_prices_the_reprint(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id

        login(client)
        resp = client.post(
            f"/admin/jobs/{old_id}/reprint",
            data={"reprint_reason": "wants_more", "charge_normally": "on"},
        )

        assert resp.status_code == 302
        with app.app_context():
            new_job = Job.query.filter(Job.id != old_id).order_by(Job.id.desc()).first()
            assert new_job.total_cost is not None
            assert new_job.total_cost > 0

    def test_second_reprint_of_the_same_original_gets_r2(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id

        login(client)
        client.post(f"/admin/jobs/{old_id}/reprint", data={"reprint_reason": "bad_print"})
        client.post(f"/admin/jobs/{old_id}/reprint", data={"reprint_reason": "paper_jam"})

        with app.app_context():
            reprints = (
                Job.query.filter(Job.reprint_of == old_id).order_by(Job.created_at).all()
            )
            assert len(reprints) == 2
            assert reprints[0].display_ticket == "P-001-R"
            assert reprints[1].display_ticket == "P-001-R2"

    def test_invalid_reason_shows_error_and_creates_no_job(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id
            jobs_before = Job.query.count()

        login(client)
        resp = client.post(
            f"/admin/jobs/{old_id}/reprint",
            data={"reprint_reason": "not-a-real-reason"},
            follow_redirects=True,
        )

        assert resp.status_code == 200
        assert b"Pick a reason" in resp.data
        with app.app_context():
            assert Job.query.count() == jobs_before

    def test_reprint_with_missing_file_shows_error_and_creates_no_job(
        self, app, client, tmp_path
    ):
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
        resp = client.post(
            f"/admin/jobs/{old_id}/reprint",
            data={"reprint_reason": "bad_print"},
            follow_redirects=True,
        )

        assert resp.status_code == 200
        assert b"no longer on disk" in resp.data
        with app.app_context():
            assert Job.query.count() == jobs_before

    def test_missing_job_redirects_without_error(self, client):
        login(client)
        resp = client.post("/admin/jobs/999999/reprint", data={"reprint_reason": "bad_print"})
        assert resp.status_code == 302

    def test_reprint_success_flash_renders_with_ok_styling_not_error(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()
            old_id = old.id

        login(client)
        resp = client.post(
            f"/admin/jobs/{old_id}/reprint",
            data={"reprint_reason": "bad_print"},
            follow_redirects=True,
        )

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Reprint" in body and "created" in body
        assert "bg-ok-bg" in body

    def test_history_page_shows_reprint_form(self, app, client):
        with app.app_context():
            old = make_terminal_photo_job(app, JobStatus.DONE, ticket="P-001")
            db.session.add(old)
            db.session.commit()

        login(client)
        resp = client.get("/admin/history/")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "reprint_reason" in body
        assert "Bad print" in body
        assert "charge_normally" in body
