from pathlib import Path

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults

FIXTURES = Path(__file__).parent / "fixtures"


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


def make_photo_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
        status=JobStatus.READY_FOR_REVIEW,
        total_cost=0.0,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestThumbRoute:
    def test_requires_admin_login(self, app, client):
        with app.app_context():
            job = make_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        resp = client.get(f"/admin/jobs/{job_id}/thumb.png")
        assert resp.status_code == 302

    def test_prefers_the_processed_photo_over_the_original(self, app, client):
        with app.app_context():
            job = make_photo_job(processed_path=str(FIXTURES / "face_two.jpg"))
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/thumb.png")
        assert resp.status_code == 200
        assert resp.data == (FIXTURES / "face_two.jpg").read_bytes()

    def test_falls_back_to_the_original_upload_when_not_processed_yet(self, app, client):
        with app.app_context():
            job = make_photo_job(processed_path=None)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/thumb.png")
        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"
        assert resp.data == (FIXTURES / "face_one.jpg").read_bytes()

    def test_not_cached(self, app, client):
        """The crop tool rewrites the processed file in place - a cached
        thumbnail would silently show a stale crop."""
        with app.app_context():
            job = make_photo_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/thumb.png")
        assert resp.status_code == 200
        assert "no-cache" in resp.headers.get("Cache-Control", "") or resp.headers.get(
            "Cache-Control"
        ) in ("public, max-age=0", "max-age=0")

    def test_missing_job_404s(self, client):
        login(client)
        resp = client.get("/admin/jobs/999999/thumb.png")
        assert resp.status_code == 404

    def test_job_with_no_files_at_all_404s(self, app, client):
        with app.app_context():
            job = make_photo_job(
                processed_path=None, upload_path=str(Path("/tmp/does-not-exist.jpg"))
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/thumb.png")
        assert resp.status_code == 404


class TestRecropRequiresAdminLogin:
    def test_requires_admin_login(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job()
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        resp = client.post(f"/admin/jobs/{job_id}/recrop", data={"crop": ""})
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]


class TestRecrop:
    def _make_ready_job(self, app, **overrides):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(**overrides)
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(job)
            db.session.commit()
            return job.id

    def test_valid_crop_marks_processed_source_manual(self, app, client):
        job_id = self._make_ready_job(app)
        login(client)

        resp = client.post(
            f"/admin/jobs/{job_id}/recrop",
            data={"crop": '{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}'},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/")

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.processed_source == "manual"
            assert job.processed_path
            assert Path(job.processed_path).exists()

    def test_blank_crop_reverts_to_automatic(self, app, client):
        job_id = self._make_ready_job(app)
        login(client)

        # First apply a manual crop...
        client.post(
            f"/admin/jobs/{job_id}/recrop",
            data={"crop": '{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}'},
        )
        with app.app_context():
            assert db.session.get(Job, job_id).processed_source == "manual"

        # ...then "Use automatic crop" (blank crop field) reverts it.
        resp = client.post(f"/admin/jobs/{job_id}/recrop", data={"crop": ""})
        assert resp.status_code == 302

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.processed_source == "auto"

    def test_malformed_crop_does_not_error_and_falls_back_to_automatic(self, app, client):
        job_id = self._make_ready_job(app)
        login(client)

        resp = client.post(f"/admin/jobs/{job_id}/recrop", data={"crop": "{not valid json"})
        assert resp.status_code == 302

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.processed_source == "auto"

    def test_works_on_a_flagged_job_without_the_flag_blocking_it(self, app, client):
        """needs_attention is a flag, not a status - a flagged job is
        still READY_FOR_REVIEW, so recrop must be reachable for it too
        (matches decision #4 of the original crop-tool plan: the flag
        reflects the SOURCE photo's content, not which crop path was
        used, and staff commonly want to fix the crop before deciding
        whether to approve)."""
        job_id = self._make_ready_job(app)
        with app.app_context():
            job = db.session.get(Job, job_id)
            job.flag_for_attention("2 faces were found in the uploaded photo.")
            db.session.commit()
        login(client)

        resp = client.post(
            f"/admin/jobs/{job_id}/recrop",
            data={"crop": '{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}'},
        )
        assert resp.status_code == 302

        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.processed_source == "manual"

    def test_document_job_is_rejected(self, app, client):
        with app.app_context():
            job = Job(
                ticket_number="P-002",
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
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.post(f"/admin/jobs/{job_id}/recrop", data={"crop": ""})
        assert resp.status_code == 404

    def test_job_not_ready_for_review_is_rejected(self, app, client):
        job_id = self._make_ready_job(app, status=JobStatus.DONE)
        login(client)

        resp = client.post(f"/admin/jobs/{job_id}/recrop", data={"crop": ""})
        assert resp.status_code == 404

    def test_missing_job_is_rejected(self, client):
        login(client)
        resp = client.post("/admin/jobs/999999/recrop", data={"crop": ""})
        assert resp.status_code == 404

    def test_missing_source_file_does_not_500(self, app, client, tmp_path):
        """The 2-day upload-source retention window can outlive a job
        still sitting in the review queue - recrop needs the original
        file, so this must degrade gracefully, not crash."""
        job_id = self._make_ready_job(app, upload_path=str(tmp_path / "long-gone.jpg"))
        login(client)

        resp = client.post(
            f"/admin/jobs/{job_id}/recrop",
            data={"crop": '{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}'},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/")
