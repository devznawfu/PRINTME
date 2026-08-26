"""Small state-mutating admin actions: daily code reset, per-job
quantity adjustment, and single-document printing. Kept separate from
admin_dashboard.py (which only renders) and admin_review.py (which
owns the flagged-job review actions)."""

from flask import Blueprint, jsonify, redirect, request, url_for

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.routes.admin_auth import admin_required
from printme.services import job_state
from printme.services.pricing import price_job
from printme.services.printing import get_printer_backend
from printme.services.printing.printer_registry import available_printers, is_valid_printer
from printme.services.retention import DEFAULT_RETENTION_DAYS, sweep_old_uploads
from printme.services.secret_code import reset_now

bp = Blueprint("api", __name__, url_prefix="/admin")

# One process-lifetime backend instance - the real win32 backend on
# Windows, the mock (with an inspectable print_log) everywhere else.
# Everything here only depends on the PrinterBackend interface.
_printer_backend = get_printer_backend()


@bp.route("/code/reset", methods=["POST"])
@admin_required
def reset_code():
    reset_now(db.session)
    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/jobs/cleanup", methods=["POST"])
@admin_required
def cleanup_old_jobs():
    sweep_old_uploads(db.session, days=DEFAULT_RETENTION_DAYS)
    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/jobs/<int:job_id>/qty", methods=["POST"])
@admin_required
def adjust_qty(job_id):
    job = db.session.get(Job, job_id)
    if job is None:
        return jsonify(error="job not found"), 404

    payload = request.json if request.is_json else request.form
    direction = payload.get("direction")
    delta = 1 if direction == "inc" else -1 if direction == "dec" else 0

    if job.service_type == "photo" and job.photo_items:
        row_id_raw = payload.get("row_id")
        row = None
        if row_id_raw is not None:
            try:
                row_id = int(row_id_raw)
            except (TypeError, ValueError):
                row_id = None
            if row_id is not None:
                row = next((r for r in job.photo_items if r.id == row_id), None)
        if row is None:
            row = job.photo_items[0]
        row.quantity = max(1, min(99, row.quantity + delta))
        new_qty = row.quantity
    else:
        job.copies = max(1, min(99, (job.copies or 1) + delta))
        new_qty = job.copies

    db.session.commit()
    try:
        price_job(db.session, job)
    except ValueError:
        pass  # e.g. a document job whose page_count isn't known yet

    if request.is_json:
        return jsonify(qty=new_qty, total_cost=job.total_cost)
    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@admin_required
def cancel_job(job_id):
    """Staff-initiated cancel from the Ready to Print / Needs Attention
    queues - only legal from ready_for_review (job_state's transition
    graph), which is the only status admins actually act on. For a
    photo job whose items are on an already-packed, unprinted sheet,
    cancelling it here is the whole fix: it drops out of
    pack_pending_photo_jobs()'s READY_FOR_REVIEW query, so the next
    Photo Sheets page load repacks the sheet without it automatically -
    no separate "remove from sheet" logic needed."""
    job = db.session.get(Job, job_id)
    if job is None:
        return redirect(url_for("admin_dashboard.dashboard"))

    reason = (request.form.get("reason") or "").strip() or "Cancelled by staff"
    try:
        job_state.mark_cancelled(db.session, job, reason)
    except job_state.IllegalTransition:
        pass  # already past the point where cancelling makes sense

    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/jobs/<int:job_id>/print", methods=["POST"])
@admin_required
def print_document(job_id):
    """Individual print action for DOCUMENT jobs only - photo jobs
    print in batches via the Photo Sheets page (admin_photo_sheets.py),
    per the confirmed design: the layout engine packs multiple
    customers' photos onto shared sheets, so there is no meaningful
    "print this one photo job" action."""
    job = db.session.get(Job, job_id)
    if job is None or job.service_type != "document":
        return redirect(url_for("admin_dashboard.dashboard"))

    printer_name = request.form.get("printer") or (available_printers()[0])
    if not is_valid_printer(printer_name):
        return redirect(url_for("admin_dashboard.dashboard"))

    try:
        job_state.mark_printing(db.session, job)
        _printer_backend.print_file(
            job.processed_path,
            printer_name,
            copies=job.copies or 1,
            grayscale=job.color_mode == "bw",
        )
        job_state.mark_done(db.session, job)
    except Exception as exc:
        job_state.mark_failed(db.session, job, f"Printing failed: {exc}")

    return redirect(url_for("admin_dashboard.dashboard"))
