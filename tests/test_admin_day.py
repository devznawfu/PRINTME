import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.models.photo_sheet import PhotoSheet
from printme.models.pricing import PricingRate, seed_defaults

FIXTURES = Path(__file__).parent / "fixtures"


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


def make_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
    )
    defaults.update(overrides)
    return Job(**defaults)


def _naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TestDaySummaryRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/day")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_counts_only_todays_done_jobs(self, app, client):
        with app.app_context():
            today_done = make_job(
                ticket_number="P-001", status=JobStatus.DONE, total_cost=15.0
            )
            yesterday_done = make_job(
                ticket_number="P-002",
                status=JobStatus.DONE,
                total_cost=100.0,
                customer_name="Ben",
            )
            db.session.add_all([today_done, yesterday_done])
            db.session.commit()

            # updated_at has onupdate=now(), so push yesterday_done's
            # stamp back in the DB directly (bypassing the ORM's auto
            # update-on-commit behavior) to simulate a job finished
            # before today's cutoff.
            db.session.execute(
                Job.__table__.update()
                .where(Job.id == yesterday_done.id)
                .values(updated_at=_naive_utc_now() - timedelta(days=1))
            )
            db.session.commit()

        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        done_count = re.search(r"Done today</span>\s*<span[^>]*>(\d+)</span>", body).group(1)
        assert done_count == "1"
        assert "&#8369;15.00" in body

    def test_uncollected_sums_todays_printing_jobs(self, app, client):
        with app.app_context():
            printing = make_job(
                ticket_number="P-001", status=JobStatus.PRINTING, total_cost=35.0
            )
            db.session.add(printing)
            db.session.commit()

        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "&#8369;35.00" in body
        assert "1 job still printing" in body

    def test_sheets_used_counts_todays_sheets(self, app, client):
        with app.app_context():
            sheet = PhotoSheet(
                batch_id="batch1",
                sheet_number=0,
                width_px=2480,
                height_px=3508,
                margin_px=30,
            )
            db.session.add(sheet)
            db.session.commit()

        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        with app.app_context():
            assert PhotoSheet.query.count() == 1

    def test_busiest_hours_reflects_todays_job_creation_times(self, app, client):
        with app.app_context():
            job = make_job(ticket_number="P-001")
            db.session.add(job)
            db.session.commit()

        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Busiest hours" in body
        assert "No jobs submitted yet today." not in body

    def test_no_jobs_today_shows_empty_state(self, client):
        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        assert b"No jobs submitted yet today." in resp.data
        assert b"0 jobs submitted today" in resp.data

    def test_average_job_value_ignores_unpriced_jobs(self, app, client):
        with app.app_context():
            priced = make_job(ticket_number="P-001", status=JobStatus.DONE, total_cost=20.0)
            unpriced = make_job(
                ticket_number="P-002",
                status=JobStatus.DONE,
                total_cost=None,
                customer_name="Ben",
            )
            db.session.add_all([priced, unpriced])
            db.session.commit()

        login(client)
        resp = client.get("/admin/day")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "2 job" in body  # both count toward "done today"
        assert "&#8369;20.00" in body  # average of just the priced one


class TestFailuresRoute:
    def test_requires_admin_login(self, client):
        resp = client.get("/admin/failures")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]

    def test_empty_state_with_no_reprints(self, client):
        login(client)
        resp = client.get("/admin/failures")

        assert resp.status_code == 200
        assert b"No reprints in the last 30 days." in resp.data

    def test_ranks_reasons_by_count_and_sums_charged_reprints(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            original = make_job(ticket_number="P-001", status=JobStatus.DONE)
            db.session.add(original)
            db.session.commit()

            # Two "bad_print" (one charged, one shop-fault $0) outrank one
            # "paper_jam" (charged) - the ranking is by count, not cost.
            charged = make_job(
                ticket_number="P-002",
                reprint_of=original.id,
                reprint_reason="bad_print",
                total_cost=15.0,
            )
            uncharged = make_job(
                ticket_number="P-003",
                reprint_of=original.id,
                reprint_reason="bad_print",
                total_cost=0.0,
            )
            jam = make_job(
                ticket_number="P-004",
                reprint_of=original.id,
                reprint_reason="paper_jam",
                total_cost=15.0,
            )
            db.session.add_all([charged, uncharged, jam])
            db.session.commit()

            cost_per_sheet = PricingRate.query.filter_by(key="cost_per_sheet").one().price

        login(client)
        resp = client.get("/admin/failures")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Bad print" in body
        assert "Paper jam" in body
        assert "2 reprints" in body  # bad_print count
        assert "1 reprint" in body  # paper_jam count

        bad_print_pos = body.find("Bad print")
        paper_jam_pos = body.find("Paper jam")
        assert bad_print_pos < paper_jam_pos  # bad_print (2) ranked above paper_jam (1)

        # bad_print total: 15.00 (charged) + cost_per_sheet (uncharged estimate)
        expected_bad_print_total = 15.0 + cost_per_sheet
        assert f"&#8369;{expected_bad_print_total:.2f}" in body

    def test_reprints_outside_the_30_day_window_are_excluded(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            original = make_job(ticket_number="P-001", status=JobStatus.DONE)
            old_reprint = make_job(
                ticket_number="P-002",
                reprint_of=None,  # set after commit, avoids the validator
            )
            db.session.add_all([original, old_reprint])
            db.session.commit()

            old_reprint.reprint_of = original.id
            old_reprint.reprint_reason = "bad_print"
            db.session.commit()

            db.session.execute(
                Job.__table__.update()
                .where(Job.id == old_reprint.id)
                .values(created_at=_naive_utc_now() - timedelta(days=31))
            )
            db.session.commit()

        login(client)
        resp = client.get("/admin/failures")

        assert resp.status_code == 200
        assert b"No reprints in the last 30 days." in resp.data
