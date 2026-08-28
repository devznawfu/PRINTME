import io
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from printme.extensions import db
from printme.models import Job, seed_defaults
from printme.models.pricing import rate_map
from printme.services.secret_code import reset_now

FIXTURES = Path(__file__).parent / "fixtures"
REAL_JPEG_BYTES = (FIXTURES / "face_one.jpg").read_bytes()


def _minimal_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


REAL_PDF_BYTES = _minimal_pdf_bytes()


def todays_code(app):
    with app.app_context():
        return reset_now(db.session).code


def submit_form(client, code, headers=None, **overrides):
    data = {
        "name": "Maria Alvarez",
        "code": code,
        "service": "photo",
        "qty_2x2": "1",
        "files": (io.BytesIO(REAL_JPEG_BYTES), "photo.jpg"),
    }
    data.update(overrides)
    return client.post(
        "/upload", data=data, content_type="multipart/form-data", headers=headers
    )


def _step_classes(html, div_id):
    import re

    m = re.search(rf'<div id="{div_id}" class="([^"]+)"', html)
    return set(m.group(1).split()) if m else set()


class TestUploadForm:
    def test_get_renders_the_form(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"What are we printing?" in resp.data

    def test_fresh_load_shows_service_step_and_hides_the_rest(self, client):
        """Turn 4a: service choice is its own step 0, shown before the
        rest of the form - a fresh page load must never show both (or
        neither) of step-0/step-form at once."""
        resp = client.get("/")
        body = resp.data.decode()
        step0 = _step_classes(body, "step-0")
        step_form = _step_classes(body, "step-form")
        assert "hidden" not in step0 and "flex" in step0
        assert "hidden" in step_form and "flex" not in step_form
        assert "Step 1 of 3" in body

    def test_validation_failure_skips_straight_to_step_form(self, app, client):
        """A customer who already answered "what are we printing?" and
        then fails validation (e.g. wrong code) shouldn't be asked that
        question again - step 0 must be skipped on any error re-render."""
        resp = submit_form(client, "0000")
        assert resp.status_code == 400
        body = resp.data.decode()
        step0 = _step_classes(body, "step-0")
        step_form = _step_classes(body, "step-form")
        assert "hidden" in step0
        assert "hidden" not in step_form and "flex" in step_form


class TestFetchBasedSubmitErrorContract:
    """Turn 2a: the review step's final submit goes through fetch(), not
    a native form POST, so a validation failure (most realistically a
    wrong/expired code) never navigates the page away and wipes
    state.files/state.crops - a browser can't repopulate a file input's
    files from a server response either way, so keeping the page in
    place is the only real fix. A fetch request identifies itself with
    X-Requested-With: fetch and gets JSON back instead of a full page."""

    def test_ajax_validation_failure_returns_json_not_html(self, app, client):
        resp = submit_form(
            client, "0000", headers={"X-Requested-With": "fetch"}
        )
        assert resp.status_code == 400
        assert resp.mimetype == "application/json"
        data = resp.get_json()
        assert isinstance(data["errors"], list)
        assert any("doesn" in e for e in data["errors"])  # "doesn't look right"

    def test_non_ajax_validation_failure_still_returns_the_full_page(self, app, client):
        """Plain browser form submission (no JS, or JS failed to load)
        must still work exactly as before - the JSON branch is opt-in
        via the header, never the default."""
        resp = submit_form(client, "0000")
        assert resp.status_code == 400
        assert resp.mimetype == "text/html"
        assert b"doesn" in resp.data

    def test_ajax_success_still_redirects_normally(self, app, client):
        """The success path is unaffected either way - fetch() on the
        client uses redirect: "manual" specifically so it never follows
        this redirect itself (see upload-form.js) - the server's own
        behavior here doesn't need to know or care that the request came
        from fetch."""
        with patch("printme.routes.upload.process_photo_job"):
            resp = submit_form(
                client, todays_code(app), headers={"X-Requested-With": "fetch"}
            )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/confirmation")


class TestUploadSubmitValidation:
    def test_missing_name_rerenders_with_error(self, app, client):
        resp = submit_form(client, todays_code(app), name="")
        assert resp.status_code == 400
        assert b"enter your name" in resp.data

    def test_pdf_rejected_for_photo_service(self, app, client):
        resp = submit_form(
            client,
            todays_code(app),
            files=(io.BytesIO(REAL_PDF_BYTES), "scan.pdf"),
        )
        assert resp.status_code == 400
        assert b"supported file type" in resp.data

    def test_wrong_code_rerenders_with_error(self, app, client):
        submit_form(client, todays_code(app))  # establish a code exists
        resp = submit_form(client, "0000")
        assert resp.status_code == 400
        assert b"doesn" in resp.data  # "doesn't look right"

    def test_photo_without_any_quantity_rerenders_with_error(self, app, client):
        resp = submit_form(client, todays_code(app), qty_2x2="0")
        assert resp.status_code == 400
        assert b"Please pick at least one size and quantity" in resp.data

    def test_no_files_rerenders_with_error(self, app, client):
        resp = client.post(
            "/upload",
            data={
                "name": "Maria",
                "code": todays_code(app),
                "service": "photo",
                "qty_2x2": "1",
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


class TestCodeLockout:
    def _wrong_code(self, correct):
        return "0000" if correct != "0000" else "1111"

    def test_sixth_attempt_after_five_failures_is_locked_out_even_with_correct_code(self, app, client):
        correct = todays_code(app)
        wrong = self._wrong_code(correct)
        for _ in range(5):
            submit_form(client, wrong)

        resp = submit_form(client, correct)
        assert resp.status_code == 400
        assert b"Too many incorrect codes" in resp.data

    def test_fewer_than_five_failures_does_not_lock_out(self, app, client):
        correct = todays_code(app)
        wrong = self._wrong_code(correct)
        for _ in range(4):
            submit_form(client, wrong)

        with patch("printme.routes.upload.process_photo_job"):
            resp = submit_form(client, correct)
        assert resp.status_code == 302

    def test_successful_code_clears_the_failure_counter(self, app, client):
        correct = todays_code(app)
        wrong = self._wrong_code(correct)
        for _ in range(4):
            submit_form(client, wrong)

        with patch("printme.routes.upload.process_photo_job"):
            resp = submit_form(client, correct)
        assert resp.status_code == 302

        resp2 = submit_form(client, wrong)
        assert resp2.status_code == 400
        assert b"Too many incorrect codes" not in resp2.data


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
            submit_form(client, todays_code(app), qty_2x2="0", qty_Passport="3")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.ticket_number.startswith("P-")
            assert job.service_type == "photo"
            assert len(job.photo_items) == 1
            assert job.photo_items[0].size_name == "Passport"
            assert job.photo_items[0].quantity == 3

    def test_creates_a_job_using_a_more_size(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app), qty_2x2="0", qty_4x6="2")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert len(job.photo_items) == 1
            assert job.photo_items[0].size_name == "4x6"
            assert job.photo_items[0].quantity == 2

    def test_creates_multiple_photo_item_rows_for_mixed_sizes(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app), qty_2x2="0", qty_Passport="2", qty_1x1="4")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            rows = {(row.size_name, row.quantity) for row in job.photo_items}
            assert rows == {("1x1", 4), ("Passport", 2)}

    def test_photo_job_defaults_paper_finish_and_quality_when_unspecified(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app))

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.paper_finish == "bond"
            assert job.quality == "standard"

    def test_photo_job_honors_customer_chosen_finish_and_quality(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app), paper_finish="glossy", quality="high")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.paper_finish == "glossy"
            assert job.quality == "high"

    def test_photo_job_rejects_invalid_finish_and_quality_with_defaults(self, app, client):
        with patch("printme.routes.upload.process_photo_job"):
            submit_form(client, todays_code(app), paper_finish="satin", quality="ultra")

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.paper_finish == "bond"
            assert job.quality == "standard"

    def test_document_job_has_no_paper_finish_or_quality(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "paper_finish": "glossy",
                    "quality": "high",
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.paper_finish is None
            assert job.quality is None

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
                        (io.BytesIO(REAL_PDF_BYTES), "a.pdf"),
                        (io.BytesIO(REAL_PDF_BYTES), "b.pdf"),
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
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "bw"
            assert job.duplex is False
            assert job.paper_size == "A4"
            assert job.copies == 2

    def test_document_job_honors_customer_chosen_color_mode(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "2",
                    "color_mode": "color",
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "color"

    def test_document_sides_and_paper_size_are_always_fixed(self, app, client):
        """Sides/paper size are no longer customer choices - single-sided
        A4 always, even if a stale/crafted client still posts these
        fields (the route doesn't read them at all anymore)."""
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "duplex": "1",
                    "paper_size": "Legal",
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.duplex is False
            assert job.paper_size == "A4"

    def test_document_job_rejects_invalid_color_mode_with_default(self, app, client):
        with patch("printme.routes.upload.process_document_job"):
            client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "color_mode": "sepia",
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )

        with app.app_context():
            job = Job.query.filter_by(customer_name="Ben").one()
            assert job.color_mode == "bw"

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

    def test_a_corrupt_image_is_rejected_before_a_job_is_created(self, app, client):
        """Content validation now catches this at upload time - a job
        never gets created for it in the first place, rather than being
        created and then failing inside the pipeline. Pipeline-level
        resilience to an unreadable image (for anything that somehow
        gets past this layer) is covered directly at the unit level in
        test_photo_pipeline.py::test_unreadable_image_marks_job_failed_and_reraises."""
        with app.app_context():
            before = Job.query.count()

        resp = submit_form(
            client,
            todays_code(app),
            files=(io.BytesIO(b"not a real jpeg"), "photo.jpg"),
        )
        assert resp.status_code == 400
        assert b"doesn&#39;t look like a real JPG" in resp.data

        with app.app_context():
            assert Job.query.count() == before


class TestUploadWithManualCrop:
    def test_valid_crop_sets_processed_source_manual(self, app, client):
        """No mocking - proves the crop_0 field actually reaches the
        real photo pipeline end to end, not just that the route parses
        it. face_one.jpg is 512x512; (0.1,0.1,0.5,0.5) implies a
        256px-side box, comfortably above MIN_MANUAL_CROP_SIDE_PX."""
        with app.app_context():
            seed_defaults(db.session)
        resp = submit_form(
            client,
            todays_code(app),
            crop_0='{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}',
        )
        assert resp.status_code == 302

        with app.app_context():
            job = Job.query.filter_by(customer_name="Maria Alvarez").one()
            assert job.processed_source == "manual"

    def test_two_file_batch_correlates_crop_by_position(self, app, client):
        """The single highest-risk part of the whole feature: crop_<i>
        fields are correlated to files POSITIONALLY, by the original
        <input multiple> selection order. Two files, only the first
        (a.jpg) carries a crop - it must land on the job made from
        a.jpg, and b.jpg's job must see no manual crop at all, not a
        crop misattributed from the wrong file."""
        with patch("printme.routes.upload.process_photo_job") as mock_process:
            resp = client.post(
                "/upload",
                data={
                    "name": "Maria",
                    "code": todays_code(app),
                    "service": "photo",
                    "qty_2x2": "1",
                    "files": [
                        (io.BytesIO(REAL_JPEG_BYTES), "a.jpg"),
                        (io.BytesIO(REAL_JPEG_BYTES), "b.jpg"),
                    ],
                    "crop_0": '{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}',
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302
        assert mock_process.call_count == 2

        crops_by_filename = {
            call.args[1].original_filename: call.kwargs["manual_crop_fractions"]
            for call in mock_process.call_args_list
        }
        assert crops_by_filename["a.jpg"] == (0.1, 0.1, 0.5, 0.5)
        assert crops_by_filename["b.jpg"] is None

    def test_malformed_crop_does_not_error_and_falls_back_to_auto(self, app, client):
        with patch("printme.routes.upload.process_photo_job") as mock_process:
            resp = submit_form(client, todays_code(app), crop_0="{not valid json")
        assert resp.status_code == 302
        assert mock_process.call_args.kwargs["manual_crop_fractions"] is None

    def test_document_service_ignores_crop_fields(self, app, client):
        with patch("printme.routes.upload.process_document_job"), patch(
            "printme.routes.upload.process_photo_job"
        ) as mock_photo:
            resp = client.post(
                "/upload",
                data={
                    "name": "Ben",
                    "code": todays_code(app),
                    "service": "document",
                    "qty": "1",
                    "crop_0": '{"x": 0, "y": 0, "w": 1, "h": 1}',
                    "files": (io.BytesIO(REAL_PDF_BYTES), "form.pdf"),
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302
        mock_photo.assert_not_called()


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
                    "qty_2x2": "1",
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

    def test_pending_confirmation_carries_the_real_priced_total(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            expected = rates["2x2-bond-standard"] * 2
        with open(FIXTURES / "face_one.jpg", "rb") as fh:
            resp = client.post(
                "/upload",
                data={
                    "name": "Maria",
                    "code": todays_code(app),
                    "service": "photo",
                    "qty_2x2": "2",
                    "files": (fh, "face_one.jpg"),
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            assert sess["pending_confirmation"]["total_cost"] == expected

    def test_pending_confirmation_sums_total_across_multiple_files(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            expected = rates["2x2-bond-standard"] * 2  # one "2x2" per file
        with open(FIXTURES / "face_one.jpg", "rb") as fh1, open(
            FIXTURES / "face_one.jpg", "rb"
        ) as fh2:
            resp = client.post(
                "/upload",
                data={
                    "name": "Maria",
                    "code": todays_code(app),
                    "service": "photo",
                    "qty_2x2": "1",
                    "files": [(fh1, "a.jpg"), (fh2, "b.jpg")],
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            assert sess["pending_confirmation"]["total_cost"] == expected


class TestConfirmationPriceDisplay:
    def test_priced_job_shows_the_total(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            expected = rates["2x2-bond-standard"] * 4
        with open(FIXTURES / "face_one.jpg", "rb") as fh:
            client.post(
                "/upload",
                data={
                    "name": "Maria",
                    "code": todays_code(app),
                    "service": "photo",
                    "qty_2x2": "4",
                    "files": (fh, "face_one.jpg"),
                },
                content_type="multipart/form-data",
            )

        resp = client.get("/confirmation")
        assert resp.status_code == 200
        assert f"{expected:.2f}".encode() in resp.data
        assert b"Staff will total this at the counter" not in resp.data

    def test_unpriced_job_shows_the_staff_will_total_fallback(self, app, client):
        def fake_process_photo_job(session, job, *args, **kwargs):
            job.status = "ready_for_review"  # no price_job() call

        with patch(
            "printme.routes.upload.process_photo_job", side_effect=fake_process_photo_job
        ):
            submit_form(client, todays_code(app))

        resp = client.get("/confirmation")
        assert resp.status_code == 200
        assert b"Staff will total this at the counter" in resp.data


class TestPendingConfirmationTotalCostFallback:
    """Turn 2a: total_cost is the sum of only the tickets that actually
    got priced - "you won't be charged for anything that didn't print"
    has to hold even when only SOME files in a multi-file submission
    fail, not blank the whole total the moment any single one does. It
    only falls back to None when literally nothing in the batch priced
    (the single-file case collapses to that automatically)."""

    def test_none_when_a_job_never_gets_priced(self, app, client):
        def fake_process_photo_job(session, job, *args, **kwargs):
            # No price_job() call - simulates a job that failed before pricing.
            job.status = "ready_for_review"

        with patch(
            "printme.routes.upload.process_photo_job", side_effect=fake_process_photo_job
        ):
            resp = submit_form(client, todays_code(app))
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            assert sess["pending_confirmation"]["total_cost"] is None
            assert sess["pending_confirmation"]["failed_tickets"] == [
                sess["pending_confirmation"]["tickets"][0]["ticket"]
            ]

    def test_partial_failure_sums_only_the_succeeded_tickets(self, app, client):
        """Two files, one fails processing/pricing, one succeeds - the
        total must reflect only the one that actually printed, and the
        failed one must be named specifically."""
        calls = {"n": 0}

        def fake_process_photo_job(session, job, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                job.status = "ready_for_review"  # first file: fails, never priced
            else:
                job.status = "ready_for_review"
                job.total_cost = 15.0  # second file: succeeds

        with patch(
            "printme.routes.upload.process_photo_job", side_effect=fake_process_photo_job
        ):
            resp = client.post(
                "/upload",
                data={
                    "name": "Maria Alvarez",
                    "code": todays_code(app),
                    "service": "photo",
                    "qty_2x2": "1",
                    "files": [
                        (io.BytesIO(REAL_JPEG_BYTES), "a.jpg"),
                        (io.BytesIO(REAL_JPEG_BYTES), "b.jpg"),
                    ],
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            data = sess["pending_confirmation"]
            assert data["total_cost"] == 15.0
            assert len(data["failed_tickets"]) == 1
            failed_ticket = data["failed_tickets"][0]
            succeeded = [t for t in data["tickets"] if t["ticket"] != failed_ticket]
            assert len(succeeded) == 1
            assert not succeeded[0]["failed"]

    def test_confirmation_page_names_the_failed_ticket(self, app, client):
        def fake_process_photo_job(session, job, *args, **kwargs):
            job.status = "ready_for_review"

        with patch(
            "printme.routes.upload.process_photo_job", side_effect=fake_process_photo_job
        ):
            submit_form(client, todays_code(app))

        resp = client.get("/confirmation")
        assert resp.status_code == 200
        assert b"didn&#39;t print: P-001" in resp.data
        assert b"won't be charged" in resp.data
