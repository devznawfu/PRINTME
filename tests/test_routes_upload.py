import io
from pathlib import Path
from unittest.mock import patch

from printme.extensions import db
from printme.models import Job, seed_defaults
from printme.services.secret_code import reset_now

FIXTURES = Path(__file__).parent / "fixtures"


def todays_code(app):
    with app.app_context():
        return reset_now(db.session).code


def submit_form(client, code, **overrides):
    data = {
        "name": "Maria Alvarez",
        "code": code,
        "service": "photo",
        "size": "2x2",
        "qty": "1",
        "files": (io.BytesIO(b"fake jpeg bytes"), "photo.jpg"),
    }
    data.update(overrides)
    return client.post("/upload", data=data, content_type="multipart/form-data")


class TestUploadForm:
    def test_get_renders_the_form(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"What are we printing?" in resp.data


class TestUploadSubmitValidation:
    def test_missing_name_rerenders_with_error(self, app, client):
        resp = submit_form(client, todays_code(app), name="")
        assert resp.status_code == 400
        assert b"enter your name" in resp.data

    def test_wrong_code_rerenders_with_error(self, app, client):
        submit_form(client, todays_code(app))  # establish a code exists
        resp = submit_form(client, "0000")
        assert resp.status_code == 400
        assert b"doesn" in resp.data  # "doesn't look right"

    def test_photo_without_size_rerenders_with_error(self, app, client):
        resp = submit_form(client, todays_code(app), size="")
        assert resp.status_code == 400
        assert b"Please pick a photo size" in resp.data

    def test_no_files_rerenders_with_error(self, app, client):
        resp = client.post(
            "/upload",
            data={
                "name": "Maria",
                "code": todays_code(app),
                "service": "photo",
                "size": "2x2",
                "qty": "1",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert b"add at least one file" in resp.data

    def test_bad_extension_rejects_whole_submission_atomically(self, app, client):
        """Regression: a single bad file among several used to be
        silently dropped (fewer tickets than files, no visible error).
        It must now reject the whole submission instead."""
        with app.app_context():
            before = Job.query.count()

        resp = submit_form(
            client,
            todays_code(app),
            files=(io.BytesIO(b"x"), "virus.exe"),
        )
        assert resp.status_code == 400
        assert b"supported file type" in resp.data

        with app.app_context():
            assert Job.query.count() == before  # nothing was created


class TestUploadSubmitHappyPathMocked:
    """Mocks the processing pipelines so these stay fast and focused on
    routing/DB/session behavior - the real pipelines are covered by
    their own test suites, plus one real end-to-end test below."""

    def test_successful_submission_redirects_to_confirmation(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            resp = submit_form(client, todays_code(app))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/confirmation")

    def test_creates_a_job_with_a_ticket_and_photo_item(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app), size="Passport", qty="3")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.ticket_number.startswith("P-")
            assert job.service_type == "photo"
            assert len(job.photo_items) == 1
            assert job.photo_items[0].size_name == "Passport"
            assert job.photo_items[0].quantity == 3

    def test_multiple_files_create_multiple_jobs_with_distinct_tickets(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            resp = client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "files": [
                        (io.BytesIO(b"pdf bytes"), "a.pdf"),
                        (io.BytesIO(b"pdf bytes"), "b.pdf"),
                    ],
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

        with app.app_context():
            jobs = Job.query.filter_by(customer_name="Ben").all()
            assert len(jobs) == 2
            assert len({j.ticket_number for j in jobs}) == 2

    def test_document_job_gets_sensible_defaults(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "2",
                    "files": (io.BytesIO(b"pdf bytes"), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "bw"
            assert job.duplex is False
            assert job.paper_size == "Letter"
            assert job.copies == 2

    def test_document_job_honors_customer_chosen_options(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "2",
                    "color_mode": "color",
                    "duplex": "1",
                    "paper_size": "A4",
                    "files": (io.BytesIO(b"pdf bytes"), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "color"
            assert job.duplex is True
            assert job.paper_size == "A4"

    def test_document_job_rejects_invalid_options_with_defaults(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "color_mode": "sepia",
                    "paper_size": "Tabloid",
                    "files": (io.BytesIO(b"pdf bytes"), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "bw"
            assert job.paper_size == "Letter"

    def test_confirmation_page_shows_ticket_then_clears_session(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app))

        first = client.get("/confirmation")
        assert first.status_code == 200
        assert b"Your ticket" in first.data

        second = client.get("/confirmation")
        assert second.status_code == 302  # nothing pending - back to the form

    def test_confirmation_without_a_submission_redirects_to_form(self, client):
        resp = client.get("/confirmation")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_a_processing_failure_does_not_fail_the_request(self, app, client):
        """No mocking - a genuinely corrupt image (valid extension, but
        not a real photo) triggers a REAL failure inside process_photo_job,
        proving both that the route survives it (customer still gets
        their ticket) and that the job actually lands in failed+flagged,
        not just that a raised exception is swallowed."""
        resp = submit_form(
            client,
            todays_code(app),
            files=(io.BytesIO(b"not a real jpeg"), "photo.jpg"),
        )
        assert resp.status_code == 302

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.status == "failed"
            assert job.needs_attention is True
            assert "processing failed" in job.attention_reason.lower()


class TestUploadSubmitRealPipeline:
    """No mocking - proves the route is actually wired to the real
    photo pipeline (face detection + background removal), not just to
    a function that happens to exist."""

    def test_real_photo_job_ends_up_ready_for_review(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
        with open(FIXTURES / "face_one.jpg", "rb") as fh:
            resp = client.post(
                "/upload",
                data={
                    "name": "Maria",
                    "code": todays_code(app),
                    "service": "photo",
                    "size": "2x2",
                    "qty": "1",
                    "files": (fh, "face_one.jpg"),
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria").one()
            assert job.status == "ready_for_review"
            assert job.needs_attention is False
            assert job.processed_path
            assert Path(job.processed_path).exists()
