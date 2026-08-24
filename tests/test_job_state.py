import pytest

from printme.extensions import db
from printme.models import Job, JobStatus
from printme.services.job_state import (
    IllegalTransition,
    mark_done,
    mark_failed,
    mark_printing,
    start_processing,
    transition,
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


class TestHappyPathFlow:
    def test_full_sequence_uploaded_to_done(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()
            assert job.status == JobStatus.UPLOADED

            start_processing(db.session, job)
            assert job.status == JobStatus.PROCESSING

            transition(db.session, job, JobStatus.READY_FOR_REVIEW)
            assert job.status == JobStatus.READY_FOR_REVIEW

            mark_printing(db.session, job)
            assert job.status == JobStatus.PRINTING

            mark_done(db.session, job)
            assert job.status == JobStatus.DONE

            fetched = db.session.get(Job, job.id)
            assert fetched.status == JobStatus.DONE


class TestIllegalTransitions:
    def test_cannot_skip_straight_to_done(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            with pytest.raises(IllegalTransition):
                mark_done(db.session, job)
            assert job.status == JobStatus.UPLOADED  # unchanged

    def test_cannot_skip_printing(self, app):
        with app.app_context():
            job = make_job(status=JobStatus.READY_FOR_REVIEW)
            db.session.add(job)
            db.session.commit()

            with pytest.raises(IllegalTransition):
                mark_done(db.session, job)
            assert job.status == JobStatus.READY_FOR_REVIEW

    def test_done_is_terminal(self, app):
        with app.app_context():
            job = make_job(status=JobStatus.DONE)
            db.session.add(job)
            db.session.commit()

            with pytest.raises(IllegalTransition):
                start_processing(db.session, job)
            with pytest.raises(IllegalTransition):
                mark_printing(db.session, job)

    def test_failed_is_terminal(self, app):
        with app.app_context():
            job = make_job(status=JobStatus.FAILED)
            db.session.add(job)
            db.session.commit()

            with pytest.raises(IllegalTransition):
                start_processing(db.session, job)


class TestFailedIsReachableFromEveryActiveState:
    @pytest.mark.parametrize(
        "status",
        [
            JobStatus.UPLOADED,
            JobStatus.PROCESSING,
            JobStatus.READY_FOR_REVIEW,
            JobStatus.PRINTING,
        ],
    )
    def test_can_fail_from(self, app, status):
        with app.app_context():
            job = make_job(status=status)
            db.session.add(job)
            db.session.commit()

            mark_failed(db.session, job, "Printer ran out of paper mid-job.")

            assert job.status == JobStatus.FAILED
            assert job.needs_attention is True
            assert job.attention_reason == "Printer ran out of paper mid-job."

    def test_mark_failed_requires_a_reason(self, app):
        with app.app_context():
            job = make_job()
            db.session.add(job)
            db.session.commit()

            with pytest.raises(ValueError):
                mark_failed(db.session, job, "")
            assert job.status == JobStatus.UPLOADED  # unchanged
