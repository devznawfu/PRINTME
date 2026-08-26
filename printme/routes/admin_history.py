"""History page (job-lifecycle plan, Part D): the 30 most recent
DONE/CANCELLED/FAILED jobs, with a Restore action that resubmits a
past job's already-processed file as a brand-new job - skipping face
detection/rembg/DOCX conversion entirely, since that work is already
done and sitting in processed_path. Restore always issues a fresh
ticket number rather than reusing the old one, since ticket numbers
are recycled once a job leaves the active set (CLAUDE.md) and the old
number may since have been handed to an unrelated job.
"""

import shutil
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from printme.extensions import db
from printme.models.job import Job, JobStatus, PhotoItemRow, create_job_with_ticket
from printme.routes.admin_auth import admin_required
from printme.services.pricing import price_job

bp = Blueprint("admin_history", __name__, url_prefix="/admin")

RECENT_LIMIT = 30


def _row(job):
    return {
        "job": job,
        "file_available": bool(job.processed_path) and Path(job.processed_path).exists(),
    }


@bp.route("/history/", methods=["GET"])
@admin_required
def history():
    jobs = (
        Job.query.filter(Job.status.in_(JobStatus.TERMINAL))
        .order_by(Job.updated_at.desc())
        .limit(RECENT_LIMIT)
        .all()
    )
    return render_template("admin/history.html", rows=[_row(j) for j in jobs])


@bp.route("/jobs/<int:job_id>/restore", methods=["POST"])
@admin_required
def restore(job_id):
    old = db.session.get(Job, job_id)
    if old is None:
        return redirect(url_for("admin_history.history"))

    if not old.processed_path or not Path(old.processed_path).exists():
        flash(f"Can't restore {old.ticket_number} - its file is no longer on disk.")
        return redirect(url_for("admin_history.history"))

    fields = dict(
        customer_name=old.customer_name,
        service_type=old.service_type,
        original_filename=old.original_filename,
        upload_path=old.processed_path,
        processed_path=old.processed_path,
        status=JobStatus.READY_FOR_REVIEW,
        needs_attention=False,
    )
    if old.service_type == "document":
        fields.update(
            color_mode=old.color_mode,
            duplex=old.duplex,
            paper_size=old.paper_size,
            copies=old.copies,
            page_count=old.page_count,
        )

    new_job = create_job_with_ticket(db.session, **fields)

    # upload_path is what the 2-day retention sweep deletes. Give the
    # restored job its own disposable copy for that field so the
    # sweep can never take out the one processed_path file both this
    # job's and the original job's rows now point to - same aliasing
    # bug as document_pipeline.py's processed_path fix, just one hop
    # removed.
    processed_source = Path(old.processed_path)
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_copy = upload_dir / f"job{new_job.id}{processed_source.suffix}"
    shutil.copy2(processed_source, upload_copy)
    new_job.upload_path = str(upload_copy)

    if old.service_type == "photo":
        for row in old.photo_items:
            new_job.photo_items.append(
                PhotoItemRow(size_name=row.size_name, quantity=row.quantity)
            )

    db.session.commit()
    price_job(db.session, new_job)

    return redirect(url_for("admin_history.history"))
