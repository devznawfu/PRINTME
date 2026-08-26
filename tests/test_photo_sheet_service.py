from pathlib import Path

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, PhotoSheet, PhotoSheetItem
from printme.services import job_state
from printme.services.photo_sheet import pack_pending_photo_jobs

FIXTURES = Path(__file__).parent / "fixtures"


def make_ready_photo_job(ticket, size_name="2x2", quantity=1, needs_attention=False):
    job = Job(
        ticket_number=ticket,
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
        status=JobStatus.READY_FOR_REVIEW,
    )
    job.photo_items.append(PhotoItemRow(size_name=size_name, quantity=quantity))
    if needs_attention:
        job.flag_for_attention("Two faces were found in the uploaded photo.")
    return job


class TestPackPendingPhotoJobs:
    def test_no_eligible_jobs_returns_none(self, app):
        with app.app_context():
            assert pack_pending_photo_jobs(db.session) is None
            assert PhotoSheet.query.count() == 0

    def test_packs_ready_unflagged_photo_jobs(self, app):
        with app.app_context():
            job = make_ready_photo_job("P-001", size_name="2x2", quantity=3)
            db.session.add(job)
            db.session.commit()

            batch_id = pack_pending_photo_jobs(db.session)

            assert batch_id is not None
            items = PhotoSheetItem.query.join(PhotoSheet).filter(
                PhotoSheet.batch_id == batch_id
            ).all()
            assert len(items) == 3
            assert all(i.job_id == job.id for i in items)

    def test_flagged_jobs_are_excluded(self, app):
        with app.app_context():
            flagged = make_ready_photo_job("P-001", needs_attention=True)
            db.session.add(flagged)
            db.session.commit()

            assert pack_pending_photo_jobs(db.session) is None
            assert PhotoSheet.query.count() == 0

    def test_document_jobs_are_excluded(self, app):
        with app.app_context():
            doc = Job(
                ticket_number="P-001",
                customer_name="Ben",
                service_type="document",
                original_filename="doc.pdf",
                upload_path="/uploads/doc.pdf",
                status=JobStatus.READY_FOR_REVIEW,
                page_count=1,
            )
            db.session.add(doc)
            db.session.commit()

            assert pack_pending_photo_jobs(db.session) is None

    def test_jobs_not_ready_for_review_are_excluded(self, app):
        with app.app_context():
            for status in (
                JobStatus.UPLOADED,
                JobStatus.PROCESSING,
                JobStatus.PRINTING,
                JobStatus.DONE,
                JobStatus.FAILED,
            ):
                job = make_ready_photo_job(f"P-{status}")
                job.status = status
                if status == JobStatus.FAILED:
                    job.flag_for_attention("failed")
                db.session.add(job)
            db.session.commit()

            assert pack_pending_photo_jobs(db.session) is None

    def test_repeated_call_with_no_change_reuses_batch(self, app):
        with app.app_context():
            job = make_ready_photo_job("P-001", size_name="2x2", quantity=1)
            db.session.add(job)
            db.session.commit()

            first_batch_id = pack_pending_photo_jobs(db.session)
            second_batch_id = pack_pending_photo_jobs(db.session)

            assert second_batch_id == first_batch_id
            assert PhotoSheet.query.filter_by(batch_id=first_batch_id).count() == 1

    def test_new_pending_job_triggers_fresh_batch(self, app):
        with app.app_context():
            job = make_ready_photo_job("P-001", size_name="2x2", quantity=1)
            db.session.add(job)
            db.session.commit()

            first_batch_id = pack_pending_photo_jobs(db.session)

            job2 = make_ready_photo_job("P-002", size_name="2x2", quantity=1)
            db.session.add(job2)
            db.session.commit()

            second_batch_id = pack_pending_photo_jobs(db.session)

            assert second_batch_id != first_batch_id
            job_ids = {
                i.job_id
                for i in PhotoSheetItem.query.join(PhotoSheet).filter(
                    PhotoSheet.batch_id == second_batch_id
                )
            }
            assert job_ids == {job.id, job2.id}

    def test_cancelling_one_job_repacks_without_it(self, app):
        """Part B of the job-lifecycle plan: cancelling a job that's on
        an already-packed, unprinted sheet needs no special "remove
        from sheet" code of its own - it drops out of this query's
        READY_FOR_REVIEW filter, which the existing idempotent-repack
        check above already treats as a changed pending set."""
        with app.app_context():
            j1 = make_ready_photo_job("P-001", size_name="2x2", quantity=1)
            j2 = make_ready_photo_job("P-002", size_name="2x2", quantity=1)
            j3 = make_ready_photo_job("P-003", size_name="2x2", quantity=1)
            db.session.add_all([j1, j2, j3])
            db.session.commit()

            first_batch_id = pack_pending_photo_jobs(db.session)
            first_job_ids = {
                i.job_id
                for i in PhotoSheetItem.query.join(PhotoSheet).filter(
                    PhotoSheet.batch_id == first_batch_id
                )
            }
            assert first_job_ids == {j1.id, j2.id, j3.id}

            job_state.mark_cancelled(db.session, j2)

            second_batch_id = pack_pending_photo_jobs(db.session)
            second_job_ids = {
                i.job_id
                for i in PhotoSheetItem.query.join(PhotoSheet).filter(
                    PhotoSheet.batch_id == second_batch_id
                )
            }
            assert second_batch_id != first_batch_id
            assert second_job_ids == {j1.id, j3.id}

    def test_mixes_multiple_jobs_onto_shared_sheets(self, app):
        with app.app_context():
            j1 = make_ready_photo_job("P-001", size_name="1x1", quantity=2)
            j2 = make_ready_photo_job("P-002", size_name="Visa", quantity=2)
            db.session.add_all([j1, j2])
            db.session.commit()

            batch_id = pack_pending_photo_jobs(db.session)

            job_ids_on_sheets = {
                i.job_id
                for i in PhotoSheetItem.query.join(PhotoSheet).filter(
                    PhotoSheet.batch_id == batch_id
                )
            }
            assert job_ids_on_sheets == {j1.id, j2.id}
