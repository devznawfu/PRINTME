from printme.extensions import db
from printme.models import Job, JobStatus
from printme.routes.api import _printer_backend


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


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


class TestDashboardPrinterDropdown:
    def test_document_job_card_lists_every_printer(self, app, client):
        with app.app_context():
            db.session.add(make_ready_document_job())
            db.session.commit()
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"DCP-L2540DW" in resp.data
        assert b"DCP-T420W" in resp.data
        assert b"DCP-T430W" in resp.data


class TestPrintDocumentHonorsSelectedPrinter:
    def test_explicit_non_default_printer_is_used(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        resp = client.post(f"/admin/jobs/{job_id}/print", data={"printer": "DCP-T430W"})

        assert resp.status_code == 302
        new_entries = _printer_backend.print_log[before:]
        assert len(new_entries) == 1
        assert new_entries[0]["printer_name"] == "DCP-T430W"
