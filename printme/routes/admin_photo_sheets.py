"""Photo Sheets: pack every ready-for-review, unflagged photo job onto
A4 sheets and preview/print them as a batch - the confirmed design for
how the Smart Layout Engine surfaces in the admin UI (photo jobs have
no individual per-job print button; only Document jobs do)."""

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.models.photo_sheet import PhotoSheet
from printme.routes.admin_auth import admin_required
from printme.services import job_state
from printme.services.photo_sheet import pack_pending_photo_jobs
from printme.services.photo_sheet_renderer import render_photo_sheet
from printme.services.printing import get_printer_backend
from printme.services.printing.base import PrintError
from printme.services.printing.printer_registry import (
    available_printers,
    borderless_capable,
    is_valid_printer,
)

bp = Blueprint("admin_photo_sheets", __name__, url_prefix="/admin/photo-sheets")

_printer_backend = get_printer_backend()

FINISH_LABELS = {"glossy": "Glossy", "bond": "Bond paper"}
QUALITY_LABELS = {"standard": "Standard", "high": "High"}


def _paper_key(sheet):
    """(finish, quality) - what physical paper this sheet needs. Every
    sheet belongs to exactly one job (see the no-cross-job-mixing note
    below), so the owning job's own settings decide it unambiguously."""
    finish = (sheet.job.paper_finish or "bond") if sheet.job else "bond"
    quality = (sheet.job.quality or "standard") if sheet.job else "standard"
    return finish, quality


def _paper_label(key):
    finish, quality = key
    finish_label = FINISH_LABELS.get(finish, finish.title())
    quality_label = QUALITY_LABELS.get(quality, quality.title())
    return f"{finish_label}, {quality_label} quality"


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
        # Every sheet belongs to exactly one job - pack_pending_photo_jobs
        # never mixes different jobs' prints onto the same physical sheet
        # (a shop-owner decision, see CLAUDE.md's Smart Layout Engine
        # section) - so any item's job_id identifies the whole sheet's
        # owner. Attached dynamically, same pattern as rendered_path
        # above, so the template can show whose sheet this is and what
        # paper it needs (finish/quality live on the Job, not the sheet).
        sheet.job = db.session.get(Job, sheet.items[0].job_id) if sheet.items else None
    db.session.commit()

    # Grouped by paper type is the default - the shop's real cost is
    # paper changes, not job count. "By arrival" (today's plain
    # sheet_number order) is a toggle for when a customer is physically
    # standing at the counter and staff need to see arrival order, not
    # batching efficiency. Flagged jobs never reach pack_pending_photo_
    # jobs at all (excluded via needs_attention.is_(False)) - they're
    # already handled entirely separately in the Needs Attention queue,
    # not merely dimmed here.
    view = "arrival" if request.args.get("view") == "arrival" else "paper"
    groups = []
    if view == "paper":
        grouped = {}
        order = []
        for sheet in sheets:
            key = _paper_key(sheet)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(sheet)
        # "Load now": the batch with the most sheets - fewest paper
        # changes for the most output, printed first.
        order.sort(key=lambda k: -len(grouped[k]))
        groups = [
            {"label": _paper_label(key), "sheets": grouped[key], "load_now": i == 0}
            for i, key in enumerate(order)
        ]

    printers = available_printers()
    return render_template(
        "admin/photo_sheets.html",
        sheets=sheets,
        groups=groups,
        view=view,
        printers=printers,
        borderless_map={p: borderless_capable(p) is True for p in printers},
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
    sheet = db.session.get(PhotoSheet, sheet_id)
    if sheet is None or not sheet.rendered_path:
        return redirect(url_for("admin_photo_sheets.photo_sheets"))

    printer_name = request.form.get("printer") or available_printers()[0]
    if not is_valid_printer(printer_name):
        return redirect(url_for("admin_photo_sheets.photo_sheets"))

    # Never trust the client's checkbox alone - a stale page (printer
    # capability changed) or a spoofed submission shouldn't be able to
    # force borderless mode on a printer that doesn't support it.
    wants_borderless = request.form.get("borderless") == "on"
    use_borderless = wants_borderless and borderless_capable(printer_name) is True

    try:
        _printer_backend.print_file(
            sheet.rendered_path, printer_name, copies=1, borderless=use_borderless
        )
    except PrintError as exc:
        current_app.logger.warning("print_sheet %s failed: %s", sheet_id, exc)
        flash(f"Print failed: {printer_name} didn't respond. Check the printer and try again.")
        return redirect(url_for("admin_photo_sheets.photo_sheets"))

    job_ids = {item.job_id for item in sheet.items}
    for job_id in job_ids:
        job = db.session.get(Job, job_id)
        if job is not None and job.status == JobStatus.READY_FOR_REVIEW:
            job_state.mark_printing(db.session, job)
            job_state.mark_done(db.session, job)

    return redirect(url_for("admin_photo_sheets.photo_sheets"))
