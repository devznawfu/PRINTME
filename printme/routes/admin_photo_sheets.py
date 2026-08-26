"""Photo Sheets: pack every ready-for-review, unflagged photo job onto
A4 sheets and preview/print them as a batch - the confirmed design for
how the Smart Layout Engine surfaces in the admin UI (photo jobs have
no individual per-job print button; only Document jobs do)."""

from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, send_file, url_for

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.models.photo_sheet import PhotoSheet
from printme.routes.admin_auth import admin_required
from printme.services import job_state
from printme.services.photo_sheet import pack_pending_photo_jobs
from printme.services.photo_sheet_renderer import render_photo_sheet
from printme.services.printing import get_printer_backend
from printme.services.printing.printer_registry import available_printers, is_valid_printer

bp = Blueprint("admin_photo_sheets", __name__, url_prefix="/admin/photo-sheets")

_printer_backend = get_printer_backend()


@bp.route("/", methods=["GET"])
@admin_required
def photo_sheets():
    batch_id = pack_pending_photo_jobs(db.session)
    sheets = (
        PhotoSheet.query.filter_by(batch_id=batch_id).order_by(PhotoSheet.sheet_number).all()
        if batch_id
        else []
    )

    rendered_dir = Path(current_app.config["PROCESSED_DIR"]) / "sheets"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    for sheet in sheets:
        out_path = rendered_dir / f"{sheet.batch_id}-{sheet.sheet_number}.png"
        if not out_path.exists():
            render_photo_sheet(db.session, sheet, out_path)
        sheet.rendered_path = str(out_path)
    db.session.commit()

    return render_template(
        "admin/photo_sheets.html",
        sheets=sheets,
        printers=available_printers(),
    )


@bp.route("/preview/<int:sheet_id>", methods=["GET"])
@admin_required
def preview_image(sheet_id):
    sheet = db.session.get(PhotoSheet, sheet_id)
    if sheet is None or not sheet.rendered_path or not Path(sheet.rendered_path).exists():
        return "", 404
    return send_file(sheet.rendered_path, mimetype="image/png")


@bp.route("/<int:sheet_id>/print", methods=["POST"])
@admin_required
def print_sheet(sheet_id):
    from flask import request

    sheet = db.session.get(PhotoSheet, sheet_id)
    if sheet is None or not sheet.rendered_path:
        return redirect(url_for("admin_photo_sheets.photo_sheets"))

    printer_name = request.form.get("printer") or available_printers()[0]
    if not is_valid_printer(printer_name):
        return redirect(url_for("admin_photo_sheets.photo_sheets"))

    _printer_backend.print_file(sheet.rendered_path, printer_name, copies=1)

    job_ids = {item.job_id for item in sheet.items}
    for job_id in job_ids:
        job = db.session.get(Job, job_id)
        if job is not None and job.status == JobStatus.READY_FOR_REVIEW:
            job_state.mark_printing(db.session, job)
            job_state.mark_done(db.session, job)

    return redirect(url_for("admin_photo_sheets.photo_sheets"))
