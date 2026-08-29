"""History page (job-lifecycle plan, Part D): the 30 most recent
DONE/CANCELLED/FAILED jobs, with a Restore action that resubmits a
past job's already-processed file as a brand-new job - skipping face
detection/rembg/DOCX conversion entirely, since that work is already
done and sitting in processed_path. Restore always issues a fresh
ticket number rather than reusing the old one, since ticket numbers
are recycled once a job leaves the active set (CLAUDE.md) and the old
number may since have been handed to an unrelated job.

Reprint (turn 3c) is a close variant of Restore for the specific case
of a customer complaint (bad print, paper jam, wrong crop, wants
more) - it links the new job back to the original via reprint_of/
reprint_reason and defaults to a $0 total (shop-fault assumption)
unless staff opt to charge normally. Kept as its own independent
route rather than refactored to share code with restore(), so
restore's already-tested behavior can't be destabilized by this.
"""

import shutil
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from printme.models.job import (
    REPRINT_REASON_LABELS,
    REPRINT_REASONS,
    Job,
    JobStatus,
    PhotoItemRow,
    create_job_with_ticket,
)
from printme.extensions import db
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
    return render_template(
        "admin/history.html",
        rows=[_row(j) for j in jobs],
        reprint_reason_labels=REPRINT_REASON_LABELS,
    )


@bp.route("/jobs/<int:job_id>/restore", methods=["POST"])
@admin_required
def restore(job_id):
    old = db.session.get(Job, job_id)
    if old is None:
        return redirect(url_for("admin_history.history"))

    if not old.processed_path or not Path(old.processed_path).exists():
        flash(f"Can't restore {old.ticket_number} - its file is no longer on disk.", "error")
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

    # The original job correctly stays right here in History, untouched -
    # this is a real historical record, not something Restore/Reprint
    # should ever remove. A real link to where the new job actually
    # landed (rather than just naming it in text) is what makes that
    # distinction legible: nothing here vanished, something new showed
    # up on the dashboard.
    dashboard_url = url_for("admin_dashboard.dashboard")
    flash(
        Markup(
            f"Restored {escape(old.display_ticket)} as "
            f'<a href="{dashboard_url}" class="underline">{escape(new_job.display_ticket)}</a>'
            " - now in the print queue."
        ),
        "success",
    )
    return redirect(url_for("admin_history.history"))


@bp.route("/jobs/<int:job_id>/reprint", methods=["POST"])
@admin_required
def reprint(job_id):
    """Reprint an already-done job under a NEW ticket (Job row), linked
    back to the original via reprint_of - the original's own status/
    history is never touched. Defaults to $0 (a shop-fault assumption:
    most reprints are the shop's mistake, not the customer's) unless
    staff explicitly check "charge normally"."""
    old = db.session.get(Job, job_id)
    if old is None:
        return redirect(url_for("admin_history.history"))

    if not old.processed_path or not Path(old.processed_path).exists():
        flash(f"Can't reprint {old.display_ticket} - its file is no longer on disk.", "error")
        return redirect(url_for("admin_history.history"))

    reason = request.form.get("reprint_reason")
    if reason not in REPRINT_REASONS:
        flash("Pick a reason for the reprint.", "error")
        return redirect(url_for("admin_history.history"))

    charge_normally = request.form.get("charge_normally") == "on"

    fields = dict(
        customer_name=old.customer_name,
        service_type=old.service_type,
        original_filename=old.original_filename,
        upload_path=old.processed_path,
        processed_path=old.processed_path,
        status=JobStatus.READY_FOR_REVIEW,
        needs_attention=False,
        reprint_of=old.id,
        reprint_reason=reason,
    )
    if old.service_type == "document":
        fields.update(
            color_mode=old.color_mode,
            duplex=old.duplex,
            paper_size=old.paper_size,
            copies=old.copies,
            page_count=old.page_count,
        )
    elif old.service_type == "photo":
        # restore() doesn't copy these (a pre-existing gap left untouched
        # there to avoid changing its tested behavior) - reprint is a new
        # route, so it can just do this right from the start.
        fields.update(
            paper_finish=old.paper_finish,
            quality=old.quality,
        )

    new_job = create_job_with_ticket(db.session, **fields)

    # Same aliasing fix as restore(): give the reprint its own disposable
    # upload_path copy so the 2-day retention sweep can't take out the
    # processed_path file both this job's and the original's rows point to.
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

    if charge_normally:
        db.session.commit()
        price_job(db.session, new_job)
    else:
        new_job.total_cost = 0.0
        db.session.commit()

    dashboard_url = url_for("admin_dashboard.dashboard")
    flash(
        Markup(
            f'Reprint <a href="{dashboard_url}" class="underline">{escape(new_job.display_ticket)}</a>'
            f" created ({escape(REPRINT_REASON_LABELS[reason])}) - now in the print queue."
        ),
        "success",
    )
    return redirect(url_for("admin_history.history"))
