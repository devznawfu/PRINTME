from datetime import datetime, timezone

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults
from printme.routes.api import _printer_backend
from printme.services.secret_code import reset_now


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


class TestReprintDisplayOnJobCard:
    """A reprint job (Job.reprint_of set) shows its display_ticket
    -R" suffix on the live queue card, not the reprint's own
    independently-generated ticket_number - same fix as History's
    already-tested display_ticket usage, extended to the dashboard."""

    def test_reprint_card_shows_dash_r_suffix(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            original = make_ready_photo_job(
                ticket_number="P-001", status=JobStatus.DONE
            )
            db.session.add(original)
            db.session.commit()

            reprint = make_ready_photo_job(
                ticket_number="P-020",
                customer_name="Maria",
                reprint_of=original.id,
                reprint_reason="bad_print",
            )
            reprint.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(reprint)
            db.session.commit()

        login(client)
        resp = client.get("/admin/")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "P-001-R" in body
        assert "P-020" not in body


class TestStatusPollingEndpoint:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/status")
        assert resp.status_code == 302

    def test_no_jobs_returns_zero_count_and_null_latest(self, client):
        login(client)
        resp = client.get("/admin/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["latest"] is None

    def test_count_reflects_ready_for_review_jobs_only(self, app, client):
        with app.app_context():
            db.session.add(make_ready_photo_job())
            db.session.add(make_ready_document_job(ticket_number="P-002"))
            db.session.add(
                make_ready_document_job(ticket_number="P-003", status=JobStatus.DONE)
            )
            db.session.commit()
        login(client)

        resp = client.get("/admin/status")
        data = resp.get_json()
        assert data["count"] == 2
        assert data["latest"] is not None

    def test_fingerprint_changes_when_a_new_job_arrives(self, app, client):
        login(client)
        first = client.get("/admin/status").get_json()

        with app.app_context():
            db.session.add(make_ready_document_job())
            db.session.commit()

        second = client.get("/admin/status").get_json()
        assert (first["count"], first["latest"]) != (second["count"], second["latest"])

    def test_fingerprint_changes_when_a_pending_jobs_quantity_changes(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        first = client.get("/admin/status").get_json()

        with app.app_context():
            job = db.session.get(Job, job_id)
            job.copies = (job.copies or 1) + 1
            db.session.commit()

        second = client.get("/admin/status").get_json()
        assert first["latest"] != second["latest"]


class TestQrCodeRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/qr-code.png")
        assert resp.status_code == 302

    def test_returns_a_real_png(self, client):
        login(client)
        resp = client.get("/admin/qr-code.png")
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert resp.data.startswith(b"\x89PNG\r\n\x1a\n")


class TestTodaysCodeResetDisplay:
    """Regression test: the dashboard used to format last_reset_at with
    "%-I:%M %p" (strip the hour's leading zero) - a glibc/macOS-only
    strftime extension. It silently worked in this Linux dev container
    but raised ValueError: Invalid format string on the real Windows
    admin PC (Windows' C runtime strftime doesn't support "%-"), which
    is exactly why it was never caught here before. Fixed with the
    portable "%I:%M %p" plus a plain .lstrip("0") - covered directly
    against a fixed, known timestamp so the exact rendered text is
    pinned, not just "didn't crash"."""

    def test_reset_time_renders_without_a_leading_zero_and_without_crashing(self, app, client):
        with app.app_context():
            code = reset_now(db.session)
            code.last_reset_at = datetime(2026, 1, 1, 9, 5, tzinfo=timezone.utc)
            db.session.commit()
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"Code last reset at 9:05 AM" in resp.data

    def test_no_reset_yet_shows_fallback_text(self, app, client):
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"Code not reset today" in resp.data


class TestCodeUsageCount:
    """Turn 6a: the dashboard's code card counts today's jobs submitted
    under today's code - via Job.code_used, a plain snapshot string."""

    def test_counts_only_jobs_submitted_with_todays_code(self, app, client):
        with app.app_context():
            code = reset_now(db.session)
            db.session.add(make_ready_photo_job(ticket_number="P-001", code_used=code.code))
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-002", customer_name="Ben", code_used=code.code
                )
            )
            # An old job submitted under a since-rotated code shouldn't count.
            db.session.add(
                make_ready_photo_job(
                    ticket_number="P-003", customer_name="Cy", code_used="9999"
                )
            )
            db.session.commit()
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"2 jobs submitted with this code today." in resp.data

    def test_zero_usage_shows_singular_free_text(self, client):
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"0 jobs submitted with this code today." in resp.data


class TestCodeSignRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/code/sign")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_shows_todays_code_and_effective_time(self, app, client):
        with app.app_context():
            code = reset_now(db.session)
            code.rotated_at = datetime(2026, 1, 1, 9, 5, tzinfo=timezone.utc)
            db.session.commit()
            code_value = code.code
        login(client)

        resp = client.get("/admin/code/sign")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert code_value in body
        assert "In effect since 9:05 AM" in body


class TestQrSignRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/qr/sign")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_shows_the_qr_code_image(self, client):
        login(client)

        resp = client.get("/admin/qr/sign")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "admin/qr-code.png" in body
        assert "Print this sign" in body

    def test_omits_wifi_step_when_no_wifi_ssid_configured(self, app, client):
        app.config["CUSTOMER_WIFI_SSID"] = ""
        login(client)

        resp = client.get("/admin/qr/sign")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Connect to our WiFi" not in body
        assert "admin/qr-code-wifi.png" not in body

    def test_shows_wifi_step_when_wifi_ssid_configured(self, app, client):
        app.config["CUSTOMER_WIFI_SSID"] = "PRINTME!"
        login(client)

        resp = client.get("/admin/qr/sign")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Connect to our WiFi" in body
        assert "admin/qr-code-wifi.png" in body
        assert "PRINTME!" in body
        assert "your phone's own Camera app" in body
        assert "Google Lens" in body


class TestQrCodeWifiRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/qr-code-wifi.png")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_404s_when_no_wifi_ssid_configured(self, app, client):
        app.config["CUSTOMER_WIFI_SSID"] = ""
        login(client)

        resp = client.get("/admin/qr-code-wifi.png")

        assert resp.status_code == 404

    def test_returns_a_real_qr_png_when_configured(self, app, client):
        app.config["CUSTOMER_WIFI_SSID"] = "PRINTME!"
        app.config["CUSTOMER_WIFI_PASSWORD"] = "hunter22"
        login(client)

        resp = client.get("/admin/qr-code-wifi.png")

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert resp.data.startswith(b"\x89PNG\r\n\x1a\n")


class TestNewCodeReassurance:
    def test_dashboard_reassures_staff_a_new_code_wont_cancel_jobs(self, client):
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        assert b"Won't cancel jobs already accepted." in resp.data


class TestDashboardNavLinksToEveryAdminPage:
    """Every admin page should be one click from the main queue - not
    just built and routable, but actually reachable. Regression: Failure
    Analysis originally only linked from Close of Day, two clicks deep,
    while every sibling page (History, Pricing, Photo Sheets, Close of
    Day) sat directly in the main nav."""

    def test_nav_links_to_close_of_day_and_failure_analysis(self, client):
        login(client)

        resp = client.get("/admin/")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '/admin/day"' in body
        assert '/admin/failures"' in body


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

    def test_response_includes_refreshed_file_line_and_total_cost(self, app, client):
        """The qty stepper JS only updates the one row's own number
        directly - the card's "N prints total" summary and price have
        to come from this response, or they're stuck showing the value
        from before the click even though the change did save."""
        with app.app_context():
            seed_defaults(db.session)
            job = make_ready_photo_job()
            row = PhotoItemRow(size_name="1x1", quantity=4)
            job.photo_items.append(row)
            db.session.add(job)
            db.session.commit()
            job_id, row_id = job.id, row.id
        login(client)

        resp = client.post(
            f"/admin/jobs/{job_id}/qty",
            json={"direction": "inc", "row_id": row_id},
        )

        body = resp.get_json()
        assert body["file_line"] == "5 prints total"
        assert body["total_cost"] is not None


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

    def test_bw_job_prints_grayscale(self, app, client):
        with app.app_context():
            job = make_ready_document_job(color_mode="bw")
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(f"/admin/jobs/{job_id}/print", data={"printer": "Brother DCP-T430W"})

        assert _printer_backend.print_log[before:][0]["grayscale"] is True

    def test_color_job_does_not_print_grayscale(self, app, client):
        with app.app_context():
            job = make_ready_document_job(color_mode="color")
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(f"/admin/jobs/{job_id}/print", data={"printer": "Brother DCP-T430W"})

        assert _printer_backend.print_log[before:][0]["grayscale"] is False

    def test_no_page_range_given_prints_every_page(self, app, client):
        with app.app_context():
            job = make_ready_document_job(page_count=5)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(f"/admin/jobs/{job_id}/print", data={"printer": "Brother DCP-T430W"})

        assert _printer_backend.print_log[before:][0]["page_range"] is None

    def test_valid_page_range_reaches_the_printer_backend(self, app, client):
        with app.app_context():
            job = make_ready_document_job(page_count=5)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(
            f"/admin/jobs/{job_id}/print",
            data={"printer": "Brother DCP-T430W", "page_range": "1-2,4"},
        )

        assert _printer_backend.print_log[before:][0]["page_range"] == [1, 2, 4]

    def test_out_of_bounds_page_range_is_rejected_server_side(self, app, client):
        """Never trust the popup's own client-side arithmetic - the
        server re-validates against the job's real page_count and
        must refuse to print anything on a bad range."""
        with app.app_context():
            job = make_ready_document_job(page_count=3)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        resp = client.post(
            f"/admin/jobs/{job_id}/print",
            data={"printer": "Brother DCP-T430W", "page_range": "1-9"},
        )

        assert resp.status_code == 302
        assert _printer_backend.print_log[before:] == []
        with app.app_context():
            fetched = db.session.get(Job, job_id)
            assert fetched.status == JobStatus.READY_FOR_REVIEW

        follow = client.get(resp.headers["Location"])
        assert b"Couldn&#39;t print" in follow.data or b"Couldn't print" in follow.data

    def test_malformed_page_range_is_rejected_server_side(self, app, client):
        with app.app_context():
            job = make_ready_document_job(page_count=3)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(
            f"/admin/jobs/{job_id}/print",
            data={"printer": "Brother DCP-T430W", "page_range": "abc"},
        )

        assert _printer_backend.print_log[before:] == []


class TestPrintDocumentNewOptions:
    """The 'view details & print' dialog's paper size/orientation/margin/
    quality/copies/color fields - all optional overrides, falling back
    to the job's stored values (or a sane default) when missing/invalid,
    and persisted back onto the job either way."""

    def test_paper_size_orientation_margin_quality_reach_the_backend(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(
            f"/admin/jobs/{job_id}/print",
            data={
                "printer": "Brother DCP-T430W",
                "paper_size": "Folio",
                "orientation": "landscape",
                "margin": "wide",
                "print_quality": "best",
            },
        )

        entry = _printer_backend.print_log[before:][0]
        assert entry["paper_size"] == "Folio"
        assert entry["orientation"] == "landscape"
        assert entry["margin"] == 0.14
        assert entry["dpi"] == 600

    def test_copies_override_reaches_the_backend_and_is_persisted(self, app, client):
        with app.app_context():
            job = make_ready_document_job(copies=1)
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(
            f"/admin/jobs/{job_id}/print",
            data={"printer": "Brother DCP-T430W", "copies": "4"},
        )

        assert _printer_backend.print_log[before:][0]["copies"] == 4
        with app.app_context():
            assert db.session.get(Job, job_id).copies == 4

    def test_invalid_paper_size_falls_back_to_jobs_stored_value(self, app, client):
        with app.app_context():
            job = make_ready_document_job()
            job.paper_size = "Letter"
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(
            f"/admin/jobs/{job_id}/print",
            data={"printer": "Brother DCP-T430W", "paper_size": "NotARealSize"},
        )

        assert _printer_backend.print_log[before:][0]["paper_size"] == "Letter"

    def test_missing_new_fields_default_to_a4_portrait_normal_normal(self, app, client):
        """A job created before these fields existed (all NULL) must
        still print with sane defaults, not None reaching the backend."""
        with app.app_context():
            job = make_ready_document_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id
        login(client)

        before = len(_printer_backend.print_log)
        client.post(f"/admin/jobs/{job_id}/print", data={"printer": "Brother DCP-T430W"})

        entry = _printer_backend.print_log[before:][0]
        assert entry["paper_size"] == "A4"
        assert entry["orientation"] == "portrait"
        assert entry["margin"] == 0.06
        assert entry["dpi"] == 300
