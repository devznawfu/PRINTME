from pathlib import Path

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow

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
        status=JobStatus.READY_FOR_REVIEW,
        total_cost=15.0,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
    return job


def make_ready_document_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Ben",
        service_type="document",
        original_filename="form.pdf",
        upload_path="/uploads/form.pdf",
        processed_path="/uploads/form.pdf",
        status=JobStatus.READY_FOR_REVIEW,
        color_mode="bw",
        page_count=1,
        copies=1,
        total_cost=5.0,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestCancelJob:
    def test_requires_admin_login(self, client):
        resp = client.post("/admin/jobs/1/cancel")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_cancels_a_ready_photo_job(self, app, client):
        with app.app_context():
            job = make_ready_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.post(f"/admin/jobs/{job_id}/cancel", data={"reason": "Customer wants a redo"})

        assert resp.status_code == 302
        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.CANCELLED
            assert job.attention_reason == "Customer wants a redo"

    def test_cancels_a_ready_document_job(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        client.post(f"/admin/jobs/{job_id}/cancel")

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.CANCELLED

    def test_default_reason_when_none_given(self, app, client):
        with app.app_context():
            job = make_ready_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        client.post(f"/admin/jobs/{job_id}/cancel")

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.attention_reason == "Cancelled by staff"

    def test_already_done_job_is_left_alone(self, app, client):
        """Cancelling a job that's already past ready_for_review is a
        no-op, not an error - the redirect still succeeds."""
        with app.app_context():
            job = make_ready_document_job(status=JobStatus.DONE)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.post(f"/admin/jobs/{job_id}/cancel")

        assert resp.status_code == 302
        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.DONE

    def test_missing_job_redirects_without_error(self, client):
        login(client)
        resp = client.post("/admin/jobs/999999/cancel")
        assert resp.status_code == 302
