from datetime import datetime, timedelta, timezone

from printme.extensions import db
from printme.models import Job
from printme.services.retention import free_space_bytes, sweep_old_uploads


def days_ago(n):
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=n)


def make_job(upload_path, created_at, **overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(upload_path) if upload_path else None,
        created_at=created_at,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestSweepOldUploads:
    def test_deletes_file_for_old_job(self, app, tmp_path):
        with app.app_context():
            upload = tmp_path / "old.jpg"
            upload.write_bytes(b"fake photo bytes")
            job = make_job(upload, created_at=days_ago(3))
            db.session.add(job)
            db.session.commit()

            deleted = sweep_old_uploads(db.session)

            assert deleted == 1
            assert not upload.exists()
            # upload_path is NOT NULL - the string stays as a historical
            # record even though the file itself is gone.
            fetched = db.session.get(Job, job.id)
            assert fetched.upload_path == str(upload)

    def test_recent_job_is_left_untouched(self, app, tmp_path):
        with app.app_context():
            upload = tmp_path / "fresh.jpg"
            upload.write_bytes(b"fake photo bytes")
            job = make_job(upload, created_at=days_ago(1))
            db.session.add(job)
            db.session.commit()

            deleted = sweep_old_uploads(db.session)

            assert deleted == 0
            assert upload.exists()

    def test_already_missing_file_is_not_counted_or_an_error(self, app, tmp_path):
        """The file is already gone (previous sweep, or removed by hand)
        - not counted as a fresh deletion, and no error either."""
        with app.app_context():
            ghost_path = tmp_path / "gone_already.jpg"  # never created
            job = make_job(ghost_path, created_at=days_ago(10))
            db.session.add(job)
            db.session.commit()

            deleted = sweep_old_uploads(db.session)

            assert deleted == 0

    def test_processed_path_is_never_touched(self, app, tmp_path):
        """Processed photos are kept until manual admin cleanup -
        retention only ever touches the source upload."""
        with app.app_context():
            upload = tmp_path / "old.jpg"
            upload.write_bytes(b"x")
            processed = tmp_path / "processed.png"
            processed.write_bytes(b"y")

            job = make_job(upload, created_at=days_ago(3), processed_path=str(processed))
            db.session.add(job)
            db.session.commit()

            sweep_old_uploads(db.session)

            assert processed.exists()
            fetched = db.session.get(Job, job.id)
            assert fetched.processed_path == str(processed)

    def test_custom_retention_window(self, app, tmp_path):
        with app.app_context():
            upload = tmp_path / "half_day_old.jpg"
            upload.write_bytes(b"x")
            job = make_job(upload, created_at=days_ago(0))  # created "now"
            db.session.add(job)
            db.session.commit()

            # With a 0-day window, even a brand-new job counts as stale.
            deleted = sweep_old_uploads(db.session, days=0)
            assert deleted == 1


class TestFreeSpaceBytes:
    def test_returns_a_positive_integer_for_a_real_path(self, tmp_path):
        free = free_space_bytes(tmp_path)
        assert isinstance(free, int)
        assert free > 0


class TestCleanupOldJobsRoute:
    def test_admin_button_sweeps_old_uploads(self, app, client, tmp_path):
        with app.app_context():
            upload = tmp_path / "old.jpg"
            upload.write_bytes(b"fake photo bytes")
            job = make_job(upload, created_at=days_ago(3))
            db.session.add(job)
            db.session.commit()

        with client.session_transaction() as sess:
            sess["admin_authed"] = True

        resp = client.post("/admin/jobs/cleanup")

        assert resp.status_code == 302
        assert not upload.exists()

    def test_requires_admin_login(self, client):
        resp = client.post("/admin/jobs/cleanup")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
