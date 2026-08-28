"""Public customer upload flow (design-reference/upload-screen.html).

Processing is dispatched synchronously, right in the request: this is a
single-shop kiosk with low concurrent load, not a high-traffic service,
and a few seconds' wait with a real result beats a mysterious
"processing" state with no feedback. A processing failure doesn't fail
the request - the pipelines already mark the job failed+flagged
internally, so the customer still gets their ticket and staff see the
problem in the Needs Attention queue.
"""

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MORE_PHOTO_SIZES,
    PHOTO_ALLOWED_EXTENSIONS,
    PHOTO_SIZES,
    PRIMARY_PHOTO_SIZES,
)
from printme.extensions import db
from printme.models.job import (
    COLOR_MODES,
    PAPER_FINISHES,
    QUALITY_LEVELS,
    PhotoItemRow,
    create_job_with_ticket,
)
from printme.services import job_state
from printme.services.document_pipeline import process_document_job
from printme.services.photo_pipeline import process_photo_job
from printme.services.secret_code import clear_code_attempts, is_locked_out, record_failed_attempt
from printme.services.secret_code import validate as validate_code
from printme.services.uploads import UploadRejected, save_upload, validate_file_storage

bp = Blueprint("upload", __name__)


def _clamp_qty(raw, default=1, minimum=1, maximum=99):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, n))


def _process(job):
    """Dispatch a freshly-created job to its pipeline. Errors are
    swallowed here - the pipelines already mark the job failed+flagged
    and commit that themselves before re-raising."""
    try:
        job_state.start_processing(db.session, job)
        if job.service_type == "photo":
            process_photo_job(db.session, job, job.upload_path, current_app.config["PROCESSED_DIR"])
        else:
            process_document_job(db.session, job, current_app.config["PROCESSED_DIR"])
    except Exception:
        current_app.logger.exception("processing failed for job %s", job.id)


@bp.route("/", methods=["GET"])
def form():
    return render_template(
        "upload/index.html",
        photo_sizes=PHOTO_SIZES,
        primary_photo_sizes=PRIMARY_PHOTO_SIZES,
        more_photo_sizes=MORE_PHOTO_SIZES,
    )


@bp.route("/upload", methods=["POST"])
def submit():
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip()
    service = request.form.get("service") if request.form.get("service") in ("photo", "document") else "photo"
    qty_by_size = {
        s: _clamp_qty(request.form.get(f"qty_{s}"), default=0, minimum=0)
        for s in PHOTO_SIZES
    }
    qty = _clamp_qty(request.form.get("qty"))
    color_mode = request.form.get("color_mode") if request.form.get("color_mode") in COLOR_MODES else "bw"
    paper_finish = (
        request.form.get("paper_finish") if request.form.get("paper_finish") in PAPER_FINISHES else "bond"
    )
    quality = (
        request.form.get("quality") if request.form.get("quality") in QUALITY_LEVELS else "standard"
    )
    files = [f for f in request.files.getlist("files") if f and f.filename]
    allowed_extensions = PHOTO_ALLOWED_EXTENSIONS if service == "photo" else ALLOWED_UPLOAD_EXTENSIONS

    errors = []
    if not name:
        errors.append("Please enter your name.")
    if is_locked_out(session):
        errors.append("Too many incorrect codes. Please wait about 10 minutes and try again, or ask staff for help.")
    elif not validate_code(code, db.session):
        record_failed_attempt(session)
        errors.append("That code doesn't look right. Ask staff for today's code.")
    else:
        clear_code_attempts(session)
    if service == "photo" and sum(qty_by_size.values()) == 0:
        errors.append("Please pick at least one size and quantity.")
    if not files:
        errors.append("Please add at least one file.")

    # Validate every file up front, before saving any of them - a
    # single bad file rejects the whole submission atomically instead
    # of silently dropping just that file (which would otherwise ship
    # fewer tickets than files the customer attached, with no visible
    # error, since we redirect past the point where errors render).
    for f in files:
        try:
            validate_file_storage(f, allowed_extensions)
        except UploadRejected as exc:
            errors.append(str(exc))

    def _rerender(status=400):
        return render_template(
            "upload/index.html",
            photo_sizes=PHOTO_SIZES,
            primary_photo_sizes=PRIMARY_PHOTO_SIZES,
            more_photo_sizes=MORE_PHOTO_SIZES,
            errors=errors,
            name=name,
            service=service,
            qty_by_size=qty_by_size,
            qty=qty,
            color_mode=color_mode,
            paper_finish=paper_finish,
            quality=quality,
        ), status

    if errors:
        return _rerender()

    upload_dir = current_app.config["UPLOAD_DIR"]
    tickets = []
    for f in files:
        try:
            original_filename, saved_path = save_upload(f, upload_dir, allowed_extensions)
        except UploadRejected as exc:
            errors.append(str(exc))
            continue

        job_fields = dict(
            customer_name=name,
            service_type=service,
            original_filename=original_filename,
            upload_path=str(saved_path),
        )
        if service == "document":
            # Sides/paper size are no longer customer choices - every
            # document prints single-sided on A4 (CLAUDE.md).
            job_fields.update(color_mode=color_mode, duplex=False, paper_size="A4", copies=qty)
        else:
            job_fields.update(paper_finish=paper_finish, quality=quality)

        job = create_job_with_ticket(db.session, **job_fields)

        if service == "photo":
            for s in PHOTO_SIZES:
                n = qty_by_size[s]
                if n > 0:
                    job.photo_items.append(PhotoItemRow(size_name=s, quantity=n))
            db.session.commit()

        _process(job)
        tickets.append({"ticket": job.ticket_number, "filename": original_filename})

    if not tickets:
        if not errors:
            errors.append("Something went wrong - please try again.")
        return _rerender()

    session["pending_confirmation"] = {
        "name": name,
        "service": service,
        "qty": qty,
        "photo_items": (
            [{"size_name": s, "quantity": n} for s, n in qty_by_size.items() if n > 0]
            if service == "photo"
            else []
        ),
        "tickets": tickets,
    }
    return redirect(url_for("upload.confirmation"))


@bp.route("/confirmation", methods=["GET"])
def confirmation():
    data = session.pop("pending_confirmation", None)
    if not data:
        return redirect(url_for("upload.form"))
    return render_template("upload/confirmation.html", **data)
