"""Small state-mutating admin actions: daily code reset, per-job
quantity adjustment, and single-document printing. Kept separate from
admin_dashboard.py (which only renders) and admin_review.py (which
owns the flagged-job review actions)."""

from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, request, send_file, url_for

from printme.extensions import db
from printme.models.job import (
    COLOR_MODES,
    MARGIN_INSETS,
    MARGINS,
    ORIENTATIONS,
    PAPER_SIZES,
    PRINT_QUALITIES,
    PRINT_QUALITY_DPI,
    Job,
    JobStatus,
)
from printme.routes.admin_auth import admin_required
from printme.routes.admin_dashboard import file_line_for
from printme.services import job_state
from printme.services.document_preview import render_page_thumbnail
from printme.services.page_range import PageRangeError, parse_page_range
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
        return jsonify(qty=new_qty, total_cost=job.total_cost, file_line=file_line_for(job))
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


@bp.route("/jobs/<int:job_id>/preview/<int:page_number>.png", methods=["GET"])
@admin_required
def document_page_preview(job_id, page_number):
    """A small thumbnail of one page of a document job, for the print-
    confirmation popup's "preview of what will be printed." Renders
    once and caches to disk - same render-once-cache-forever pattern
    as admin_photo_sheets.py's sheet preview."""
    job = db.session.get(Job, job_id)
    if job is None or job.service_type != "document" or not job.processed_path:
        return "", 404

    max_pages = job.page_count or 1
    if page_number < 1 or page_number > max_pages:
        return "", 404

    preview_dir = Path(current_app.config["PROCESSED_DIR"]) / "previews"
    out_path = preview_dir / f"job{job_id}-p{page_number}.png"
    if not out_path.exists():
        render_page_thumbnail(job.processed_path, page_number, out_path)

    return send_file(out_path, mimetype="image/png")


@bp.route("/jobs/<int:job_id>/preview/<int:page_number>/full.png", methods=["GET"])
@admin_required
def document_page_preview_full(job_id, page_number):
    """The real full-resolution render of one page - what "tap to view
    full size" in the review dialog actually opens. Cached separately
    from the small 220px thumbnail above (different filename) so
    neither one downgrades the other; this is the same 300 DPI render
    the printer itself gets, so it's genuinely large enough to zoom
    into on a phone or a monitor, not just the same small thumbnail
    reopened in a new tab."""
    job = db.session.get(Job, job_id)
    if job is None or job.service_type != "document" or not job.processed_path:
        return "", 404

    max_pages = job.page_count or 1
    if page_number < 1 or page_number > max_pages:
        return "", 404

    preview_dir = Path(current_app.config["PROCESSED_DIR"]) / "previews"
    out_path = preview_dir / f"job{job_id}-p{page_number}-full.png"
    if not out_path.exists():
        render_page_thumbnail(job.processed_path, page_number, out_path, max_dim=None)

    return send_file(out_path, mimetype="image/png")


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

    raw_range = (request.form.get("page_range") or "").strip()
    try:
        pages = parse_page_range(raw_range, job.page_count or 1)
    except PageRangeError as exc:
        flash(f"Couldn't print: {exc}")
        return redirect(url_for("admin_dashboard.dashboard"))

    # Everything below is the admin's final tweak at print time (the
    # "view details & print" dialog) - falls back to whatever the job
    # already had (or a sane default) if a field is missing/invalid,
    # same permissive style as the printer fallback above, then persists
    # the admin's choice back onto the job so a later reprint remembers it.
    copies = job.copies or 1
    try:
        copies = max(1, min(99, int(request.form.get("copies", copies))))
    except (TypeError, ValueError):
        pass
    color_mode = request.form.get("color_mode")
    if color_mode not in COLOR_MODES:
        color_mode = job.color_mode or "bw"
    paper_size = request.form.get("paper_size")
    if paper_size not in PAPER_SIZES:
        paper_size = job.paper_size or "A4"
    orientation = request.form.get("orientation")
    if orientation not in ORIENTATIONS:
        orientation = job.orientation or "portrait"
    margin = request.form.get("margin")
    if margin not in MARGINS:
        margin = job.margin or "normal"
    print_quality = request.form.get("print_quality")
    if print_quality not in PRINT_QUALITIES:
        print_quality = job.print_quality or "normal"

    job.copies = copies
    job.color_mode = color_mode
    job.paper_size = paper_size
    job.orientation = orientation
    job.margin = margin
    job.print_quality = print_quality

    try:
        job_state.mark_printing(db.session, job)
        _printer_backend.print_file(
            job.processed_path,
            printer_name,
            copies=copies,
            grayscale=color_mode == "bw",
            page_range=pages if raw_range else None,
            paper_size=paper_size,
            orientation=orientation,
            margin=MARGIN_INSETS[margin],
            dpi=PRINT_QUALITY_DPI[print_quality],
        )
        job_state.mark_done(db.session, job)
    except Exception as exc:
        job_state.mark_failed(db.session, job, f"Printing failed: {exc}")

    return redirect(url_for("admin_dashboard.dashboard"))
