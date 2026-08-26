from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults
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


def make_ready_photo_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path="/uploads/photo.jpg",
        status=JobStatus.READY_FOR_REVIEW,
        total_cost=0.0,
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
        assert b"Brother DCP-L2540DW series" in resp.data
        assert b"Brother DCP-T420W" in resp.data
        assert b"Brother DCP-T430W" in resp.data


class TestPhotoJobCardShowsAllSizes:
    def test_card_lists_every_size_row_independently(self, app, client):
        with app.app_context():
            job = make_ready_photo_job()
            job.photo_items.append(PhotoItemRow(size_name="1x1", quantity=4))
            job.photo_items.append(PhotoItemRow(size_name="Passport", quantity=2))
            db.session.add(job)
            db.session.commit()
            job_id, row_ids = job.id, [row.id for row in job.photo_items]
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert resp.data.count(b"data-qty-stepper") == 2
        for row_id in row_ids:
            assert f'data-job-id="{job_id}" data-row-id="{row_id}"'.encode() in resp.data
        assert b"1x1" in resp.data
        assert b"Passport" in resp.data


class TestAdjustPhotoRowQuantity:
    def test_adjust_only_targets_the_given_row(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            job = make_ready_photo_job()
            row_1x1 = PhotoItemRow(size_name="1x1", quantity=4)
            row_passport = PhotoItemRow(size_name="Passport", quantity=2)
            job.photo_items.extend([row_1x1, row_passport])
            db.session.add(job)
            db.session.commit()
            job_id = job.id
            oneone_row_id, passport_row_id = row_1x1.id, row_passport.id
        login(client)

        resp = client.post(
            f"/admin/jobs/{job_id}/qty",
            json={"direction": "inc", "row_id": passport_row_id},
        )

        assert resp.status_code == 200
        assert resp.get_json()["qty"] == 3

        with app.app_context():
            rows = {r.id: r.quantity for r in db.session.get(Job, job_id).photo_items}
            assert rows[passport_row_id] == 3
            assert rows[oneone_row_id] == 4


class TestPrintDocumentHonorsSelectedPrinter:
    def test_explicit_non_default_printer_is_used(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        resp = client.post(f"/admin/jobs/{job_id}/print", data={"printer": "Brother DCP-T430W"})

        assert resp.status_code == 302
        new_entries = _printer_backend.print_log[before:]
        assert len(new_entries) == 1
        assert new_entries[0]["printer_name"] == "Brother DCP-T430W"
