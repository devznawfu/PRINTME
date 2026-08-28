"""Tests for the Job / PhotoItemRow / PricingRate schema."""

import pytest
from sqlalchemy.exc import IntegrityError

import printme.models.job as job_module
from printme.extensions import db
from printme.models import (
    Job,
    JobStatus,
    PhotoItemRow,
    PricingRate,
    create_job_with_ticket,
    generate_ticket_number,
    rate_map,
    seed_defaults,
)


def make_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path="/uploads/photo.jpg",
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestJobDefaults:
    def test_new_job_defaults(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            assert job.id is not None
            assert job.status == JobStatus.UPLOADED
            assert job.needs_attention is False
            assert job.attention_reason is None
            assert job.copies == 1
            assert job.total_cost is None
            assert job.created_at is not None

    def test_round_trip_all_columns(self, app):
        with app.app_context():
            job = make_job(
                service_type="document",
                color_mode="bw",
                duplex=True,
                paper_size="A4",
                copies=3,
            )
            db.session.add(job)
            db.session.commit()

            fetched = db.session.get(Job, job.id)
            assert fetched.service_type == "document"
            assert fetched.color_mode == "bw"
            assert fetched.duplex is True
            assert fetched.paper_size == "A4"
            assert fetched.copies == 3

    def test_paper_finish_and_quality_round_trip(self, app):
        with app.app_context():
            job = make_job(paper_finish="glossy", quality="high")
            db.session.add(job)
            db.session.commit()

            fetched = db.session.get(Job, job.id)
            assert fetched.paper_finish == "glossy"
            assert fetched.quality == "high"

    def test_paper_finish_and_quality_default_to_none(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            fetched = db.session.get(Job, job.id)
            assert fetched.paper_finish is None
            assert fetched.quality is None


class TestStatusFlow:
    def test_happy_path_transitions(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            for status in (
                JobStatus.PROCESSING,
                JobStatus.READY_FOR_REVIEW,
                JobStatus.PRINTING,
                JobStatus.DONE,
            ):
                job.status = status
                db.session.commit()
                assert job.status == status

    def test_failed_is_reachable(self, app):
        with app.app_context():
            job = make_job(status=JobStatus.FAILED)
            db.session.add(job)
            db.session.commit()
            assert job.status == JobStatus.FAILED


class TestNeedsAttention:
    def test_flag_requires_reason(self, app):
        with app.app_context():
            job = make_job()
            with pytest.raises(ValueError):
                job.flag_for_attention("   ")

    def test_flag_with_reason_round_trips(self, app):
        with app.app_context():
            job = make_job()
            job.flag_for_attention("Two faces found in a passport photo.")
            db.session.add(job)
            db.session.commit()

            fetched = db.session.get(Job, job.id)
            assert fetched.needs_attention is True
            assert "Two faces" in fetched.attention_reason

            fetched.clear_attention()
            db.session.commit()
            assert fetched.needs_attention is False
            assert fetched.attention_reason is None

    def test_bulk_insert_flag_without_reason_rejected(self, app):
        with app.app_context():
            job = make_job(needs_attention=True)
            with pytest.raises(ValueError):
                db.session.add(job)
                db.session.commit()

    def test_flagging_an_already_saved_job_without_reason_is_rejected(self, app):
        """Regression: the normal case is flagging a job *after* it's
        already saved (processing found a problem), not at insert time -
        the guard must fire on update too, not just insert."""
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            job.needs_attention = True  # bypassing flag_for_attention() on purpose
            with pytest.raises(ValueError):
                db.session.commit()


class TestTicketNumbers:
    def test_first_ticket_is_p001(self, app):
        with app.app_context():
            assert generate_ticket_number() == "P-001"

    def test_increments_sequentially(self, app):
        with app.app_context():
            for name in ("Ann", "Ben", "Cy"):
                db.session.add(
                    make_job(
                        ticket_number=generate_ticket_number(),
                        customer_name=name,
                    )
                )
            db.session.commit()
            assert generate_ticket_number() == "P-004"

    def test_completed_jobs_free_their_numbers(self, app):
        with app.app_context():
            done = make_job(ticket_number="P-001", status=JobStatus.DONE)
            active = make_job(ticket_number="P-005", customer_name="Ben")
            db.session.add_all([done, active])
            db.session.commit()

            # P-001 belongs to a finished job so it may be reused;
            # P-006..P-009 must be skipped to avoid colliding with P-005.
            next_num = int(generate_ticket_number().split("-")[1])
            assert next_num < 5  # reused a freed number
            active_tickets = {
                j.ticket_number
                for j in Job.query.filter(
                    Job.status.in_(JobStatus.ACTIVE)
                ).all()
            }
            assert f"P-{next_num:03d}" not in active_tickets

    def test_duplicate_active_ticket_number_is_rejected_at_the_db_level(self, app):
        """Regression: without a unique constraint, two jobs could get the
        same active ticket number (e.g. two concurrent uploads both
        computing "next free" before either commits)."""
        with app.app_context():
            db.session.add(make_job(ticket_number="P-001"))
            db.session.commit()

            db.session.add(make_job(ticket_number="P-001", customer_name="Ben"))
            with pytest.raises(IntegrityError):
                db.session.commit()

    def test_reused_ticket_number_is_allowed_once_the_original_is_done(self, app):
        with app.app_context():
            done = make_job(ticket_number="P-001", status=JobStatus.DONE)
            db.session.add(done)
            db.session.commit()

            db.session.add(make_job(ticket_number="P-001", customer_name="Ben"))
            db.session.commit()  # should not raise - P-001's prior job is done

    def test_create_job_with_ticket_retries_when_racing_a_stale_number(
        self, app, monkeypatch
    ):
        """Regression: generate_ticket_number() only reads, it doesn't
        reserve, so two callers can compute the same candidate. This
        forces that exact race and checks create_job_with_ticket()
        recovers by retrying instead of crashing or duplicating."""
        with app.app_context():
            db.session.add(make_job(ticket_number="P-001"))
            db.session.commit()

            calls = {"n": 0}
            real_generate = job_module.generate_ticket_number

            def racy_generate():
                calls["n"] += 1
                # First call pretends the race won and hands back the
                # number that's actually already taken (P-001).
                return "P-001" if calls["n"] == 1 else real_generate()

            monkeypatch.setattr(job_module, "generate_ticket_number", racy_generate)

            new_job = create_job_with_ticket(
                db.session,
                customer_name="Ben",
                service_type="photo",
                original_filename="b.jpg",
                upload_path="/uploads/b.jpg",
            )

            assert new_job.ticket_number != "P-001"
            assert calls["n"] >= 2, "expected a retry after the collision"


class TestPhotoItemRows:
    def test_expansion_to_layout_items(self, app):
        with app.app_context():
            job = make_job(ticket_number="P-007")
            row = PhotoItemRow(size_name="2x2", quantity=4)
            job.photo_items.append(row)
            db.session.add(job)
            db.session.commit()

            items = row.to_layout_items()
            assert len(items) == 4
            assert {i.item_id for i in items} == {
                f"job{job.id}-row{row.id}-1",
                f"job{job.id}-row{row.id}-2",
                f"job{job.id}-row{row.id}-3",
                f"job{job.id}-row{row.id}-4",
            }
            assert all(i.size_name == "2x2" for i in items)

    def test_cascade_delete_with_job(self, app):
        with app.app_context():
            job = make_job()
            job.photo_items.append(PhotoItemRow(size_name="Visa", quantity=2))
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            db.session.delete(job)
            db.session.commit()

            assert (
                PhotoItemRow.query.filter_by(job_id=job_id).count() == 0
            )


class TestPricing:
    def test_seed_defaults_idempotent(self, app):
        with app.app_context():
            seed_defaults(db.session)
            seed_defaults(db.session)

            rates = rate_map(db.session)
            assert rates["bw_page"] == 5.0
            assert rates["color_page"] == 10.0
            assert rates["1x1-bond-standard"] == 15.0
            assert rates["Passport-glossy-high"] == 20.0

    def test_seed_does_not_overwrite_edited_rates(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rate = PricingRate.query.filter_by(key="Passport-bond-standard").one()
            rate.price = 25.0
            db.session.commit()

            seed_defaults(db.session)
            assert rate_map(db.session)["Passport-bond-standard"] == 25.0
