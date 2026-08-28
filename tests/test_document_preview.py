from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from printme.extensions import db
from printme.models import Job, JobStatus
from printme.services.document_preview import render_page_thumbnail

FIXTURES = Path(__file__).parent / "fixtures"


def _multi_page_pdf(path, n_pages):
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=200, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True


class TestRenderPageThumbnail:
    def test_pdf_page_renders_and_is_capped_at_max_dim(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
        out = tmp_path / "thumb.png"

        render_page_thumbnail(pdf, 2, out, max_dim=100)

        assert out.exists()
        with Image.open(out) as img:
            assert img.format == "PNG"
            assert max(img.size) <= 100

    def test_single_image_document_is_resized(self, tmp_path):
        src = tmp_path / "scan.jpg"
        Image.new("RGB", (800, 600), "white").save(src)
        out = tmp_path / "thumb.png"

        render_page_thumbnail(src, 1, out, max_dim=100)

        with Image.open(out) as img:
            assert max(img.size) <= 100

    def test_creates_missing_parent_directories(self, tmp_path):
        src = tmp_path / "scan.jpg"
        Image.new("RGB", (40, 40), "white").save(src)
        out = tmp_path / "nested" / "dir" / "thumb.png"

        render_page_thumbnail(src, 1, out)

        assert out.exists()


def make_document_job(app, **overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Ben",
        service_type="document",
        original_filename="form.pdf",
        upload_path="/uploads/form.pdf",
        status=JobStatus.READY_FOR_REVIEW,
        color_mode="bw",
        copies=1,
        page_count=3,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestDocumentPagePreviewRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/jobs/1/preview/1.png")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_serves_the_correct_page_thumbnail(self, app, client, tmp_path):
        with app.app_context():
            pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
            job = make_document_job(app, processed_path=str(pdf))
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/preview/2.png")

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"

    def test_404_for_missing_job(self, client):
        login(client)
        resp = client.get("/admin/jobs/999999/preview/1.png")
        assert resp.status_code == 404

    def test_404_for_photo_job(self, app, client, tmp_path):
        with app.app_context():
            pdf = _multi_page_pdf(tmp_path / "doc.pdf", 1)
            job = make_document_job(
                app, service_type="photo", processed_path=str(pdf), page_count=None
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/preview/1.png")
        assert resp.status_code == 404

    def test_404_for_page_number_beyond_page_count(self, app, client, tmp_path):
        with app.app_context():
            pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
            job = make_document_job(app, processed_path=str(pdf), page_count=3)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/preview/4.png")
        assert resp.status_code == 404

    def test_404_for_page_number_zero(self, app, client, tmp_path):
        with app.app_context():
            pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
            job = make_document_job(app, processed_path=str(pdf), page_count=3)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        resp = client.get(f"/admin/jobs/{job_id}/preview/0.png")
        assert resp.status_code == 404

    def test_second_request_reuses_the_cached_file(self, app, client, tmp_path, monkeypatch):
        with app.app_context():
            pdf = _multi_page_pdf(tmp_path / "doc.pdf", 2)
            job = make_document_job(app, processed_path=str(pdf), page_count=2)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        first = client.get(f"/admin/jobs/{job_id}/preview/1.png")
        assert first.status_code == 200

        calls = []
        import printme.routes.api as api_module

        monkeypatch.setattr(
            api_module,
            "render_page_thumbnail",
            lambda *a, **kw: calls.append(1),
        )

        second = client.get(f"/admin/jobs/{job_id}/preview/1.png")
        assert second.status_code == 200
        assert calls == []
