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


class TestPaperBatching:
    """Turn 3a: sheets group by paper type ({finish}-{quality}) by
    default - the shop's real cost is paper changes, not job count."""

    def test_default_view_groups_by_paper_type(self, app, client):
        with app.app_context():
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-001", paper_finish="glossy", quality="high"
                )
            )
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-002", paper_finish="bond", quality="standard"
                )
            )
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/")
        body = resp.data.decode()
        assert "Glossy, High quality" in body
        assert "Bond paper, Standard quality" in body
        assert "Load now" in body
        assert "change paper before this batch" in body

    def test_arrival_view_shows_flat_list_without_grouping(self, app, client):
        with app.app_context():
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-001", paper_finish="glossy", quality="high"
                )
            )
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-002", paper_finish="bond", quality="standard"
                )
            )
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/?view=arrival")
        body = resp.data.decode()
        assert "Load now" not in body
        assert "change paper before this batch" not in body
        # both sheets still show up, just not grouped
        assert "P-001" in body
        assert "P-002" in body

    def test_the_biggest_paper_group_is_load_now(self, app, client):
        """Fewest paper changes for the most output: the batch with the
        most sheets is the one recommended first, regardless of arrival
        order."""
        with app.app_context():
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-001",
                    paper_finish="glossy",
                    quality="high",
                    total_cost=15.0,
                )
            )
            # Each job packs onto its own sheet(s) - never mixed with
            # another job's prints (see the no-cross-job-mixing fix) -
            # so 20 more jobs guarantees the bond group has more sheets
            # than the single glossy one, regardless of quantity.
            for i in range(2, 22):
                db.session.add(
                    make_ready_photo_job(
                        ticket_number=f"P-{i:03d}",
                        paper_finish="bond",
                        quality="standard",
                        total_cost=15.0,
                    )
                )
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/")
        body = resp.data.decode()
        load_now_idx = body.index("Load now")
        bond_idx = body.index("Bond paper, Standard quality")
        glossy_idx = body.index("Glossy, High quality")
        # "Load now" appears right next to whichever group has more sheets
        assert abs(load_now_idx - bond_idx) < abs(load_now_idx - glossy_idx)


class TestPrintConfirmDialogWiring:
    """Turn 3b: printing a sheet now routes through the shared confirm
    dialog (previously the button submitted directly) - the form needs
    the right data-* attributes for print-confirm.js to build the
    "load this paper" note and heading from."""

    def test_sheet_form_carries_job_and_paper_data(self, app, client):
        with app.app_context():
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-777",
                    customer_name="Ramon Villanueva",
                    paper_finish="glossy",
                    quality="high",
                )
            )
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/")
        body = resp.data.decode()
        assert 'data-print-form' in body
        assert 'data-print-kind="sheet"' in body
        assert 'data-ticket="P-777"' in body
        assert 'data-customer-name="Ramon Villanueva"' in body
        assert 'data-paper-finish="glossy"' in body
        assert 'data-paper-quality="high"' in body
        # the button no longer submits directly - it opens the dialog
        assert 'data-print-trigger' in body

    def test_print_button_is_no_longer_a_direct_submit(self, app, client):
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/")
        body = resp.data.decode()
        assert '<button type="button" data-print-trigger' in body

    def test_shared_confirm_dialog_is_present(self, app, client):
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)

        resp = client.get("/admin/photo-sheets/")
        body = resp.data.decode()
        assert 'id="print-confirm-dialog"' in body
        assert "print-confirm.js" in body


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
            resp = client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "Brother DCP-T420W"})

        assert resp.status_code == 302

        follow = client.get(resp.headers["Location"])
        assert b"Print failed" in follow.data
        assert b"Brother DCP-T420W" in follow.data

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
            client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "Brother DCP-T420W"})

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
            resp = client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "Brother DCP-T420W"})

        assert resp.status_code == 302
        with app.app_context():
            job = db.session.get(Job, job_id)
            assert job.status == JobStatus.DONE


class TestPrintSheetBorderless:
    def _sheet_id(self, app, client):
        client.get("/admin/photo-sheets/")
        with app.app_context():
            from printme.models import PhotoSheet

            return PhotoSheet.query.first().id

    def test_checked_and_capable_printer_prints_borderless(self, app, client):
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)
        sheet_id = self._sheet_id(app, client)

        client.post(
            f"/admin/photo-sheets/{sheet_id}/print",
            data={"printer": "Brother DCP-T420W", "borderless": "on"},
        )

        from printme.routes.admin_photo_sheets import _printer_backend

        assert _printer_backend.print_log[-1]["borderless"] is True

    def test_checked_but_non_capable_printer_is_overridden_server_side(self, app, client):
        """The server re-validates against real capability data - a
        checked box for a non-capable printer must never reach the
        backend as borderless=True, even though the client sent it."""
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)
        sheet_id = self._sheet_id(app, client)

        client.post(
            f"/admin/photo-sheets/{sheet_id}/print",
            data={"printer": "Brother DCP-L2540DW series", "borderless": "on"},
        )

        from printme.routes.admin_photo_sheets import _printer_backend

        assert _printer_backend.print_log[-1]["borderless"] is False

    def test_unchecked_box_omitted_from_form_defaults_to_false(self, app, client):
        """Unchecked HTML checkboxes aren't submitted at all - the
        field is simply absent from the form data."""
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.commit()
        login(client)
        sheet_id = self._sheet_id(app, client)

        client.post(f"/admin/photo-sheets/{sheet_id}/print", data={"printer": "Brother DCP-T420W"})

        from printme.routes.admin_photo_sheets import _printer_backend

        assert _printer_backend.print_log[-1]["borderless"] is False
