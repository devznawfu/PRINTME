"""Job status transitions (CLAUDE.md's flow): uploaded -> processing ->
ready_for_review -> printing -> done / failed.

process_photo_job/process_document_job already own the processing ->
ready_for_review/failed leg internally (they need to set that status
atomically with processed_path/needs_attention in the same commit).
This module owns the rest of the flow: starting processing, and the
print action's ready_for_review -> printing -> done - plus the
transition graph itself, so an illegal jump (e.g. uploaded straight to
done) fails loudly instead of corrupting a job's state.
"""

from printme.models.job import JobStatus

_ALLOWED_TRANSITIONS = {
    JobStatus.UPLOADED: {JobStatus.PROCESSING, JobStatus.FAILED},
    JobStatus.PROCESSING: {JobStatus.READY_FOR_REVIEW, JobStatus.FAILED},
    JobStatus.READY_FOR_REVIEW: {JobStatus.PRINTING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PRINTING: {JobStatus.DONE, JobStatus.FAILED},
    JobStatus.DONE: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class IllegalTransition(Exception):
    """The requested status change isn't a legal step in CLAUDE.md's
    job status flow."""


def transition(session, job, new_status):
    allowed = _ALLOWED_TRANSITIONS.get(job.status, set())
    if new_status not in allowed:
        raise IllegalTransition(
            f"cannot move job {job.id} from {job.status!r} to {new_status!r}"
        )
    job.status = new_status
    session.commit()
    return job


def start_processing(session, job):
    return transition(session, job, JobStatus.PROCESSING)


def mark_printing(session, job):
    return transition(session, job, JobStatus.PRINTING)


def mark_done(session, job):
    return transition(session, job, JobStatus.DONE)


def mark_failed(session, job, reason):
    """Fail a job outside the processing pipelines (e.g. a print attempt
    that fails) - flags it with the specific reason so it isn't lost."""
    job.flag_for_attention(reason)
    return transition(session, job, JobStatus.FAILED)


def mark_cancelled(session, job, reason="Cancelled by staff"):
    """Staff-initiated cancel from the Ready to Print / Needs Attention
    queues. Records `reason` as a plain note (not via flag_for_attention -
    a cancelled job isn't "needing attention", it's already been dealt
    with) so it's visible on the History page."""
    job.attention_reason = reason
    return transition(session, job, JobStatus.CANCELLED)
