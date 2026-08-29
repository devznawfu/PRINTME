"""Public customer upload flow (design-reference/upload-screen.html).

Processing is dispatched synchronously, right in the request: this is a
single-shop kiosk with low concurrent load, not a high-traffic service,
and a few seconds' wait with a real result beats a mysterious
"processing" state with no feedback. A processing failure doesn't fail
the request - the pipelines already mark the job failed+flagged
internally, so the customer still gets their ticket and staff see the
problem in the Needs Attention queue.
"""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MORE_PHOTO_SIZES,
    PHOTO_ALLOWED_EXTENSIONS,
    PHOTO_SIZES,
    PRIMARY_PHOTO_SIZES,
)
from printme.extensions import db
from printme.models.availability import availability_map, size_key
from printme.models.job import (
    COLOR_MODES,
    PAPER_FINISHES,
    QUALITY_LEVELS,
    Job,
    JobStatus,
    PhotoItemRow,
    create_job_with_ticket,
)
from printme.models.pricing import rate_map
from printme.services import job_state
from printme.services.document_pipeline import process_document_job
from printme.services.manual_crop import parse_crop_fractions
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


def _enabled_sizes(availability):
    """PHOTO_SIZES filtered down to whatever's currently enabled - a
    size missing from `availability` (shouldn't happen once seeded, but
    a customer request always outlives an admin's future schema
    changes) defaults to enabled, same permissive-default posture as
    every other "field missing" case in this route."""
    return [s for s in PHOTO_SIZES if availability.get(size_key(s), True)]


def _process(job, manual_crop_fractions=None):
    """Dispatch a freshly-created job to its pipeline. Errors are
    swallowed here - the pipelines already mark the job failed+flagged
    and commit that themselves before re-raising."""
    try:
        job_state.start_processing(db.session, job)
        if job.service_type == "photo":
            process_photo_job(
                db.session,
                job,
                job.upload_path,
                current_app.config["PROCESSED_DIR"],
                manual_crop_fractions=manual_crop_fractions,
            )
        else:
            process_document_job(db.session, job, current_app.config["PROCESSED_DIR"])
    except Exception:
        current_app.logger.exception("processing failed for job %s", job.id)


@bp.route("/", methods=["GET"])
def form():
    availability = availability_map(db.session)
    enabled_sizes = set(_enabled_sizes(availability))
    return render_template(
        "upload/index.html",
        photo_sizes=PHOTO_SIZES,
        primary_photo_sizes=[s for s in PRIMARY_PHOTO_SIZES if s in enabled_sizes],
        more_photo_sizes=[s for s in MORE_PHOTO_SIZES if s in enabled_sizes],
        rates=rate_map(db.session),
        photo_service_enabled=availability.get("service:photo", True),
        document_service_enabled=availability.get("service:document", True),
    )


@bp.route("/upload", methods=["POST"])
def submit():
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip()
    service = request.form.get("service") if request.form.get("service") in ("photo", "document") else "photo"
    availability = availability_map(db.session)
    enabled_sizes = set(_enabled_sizes(availability))
    # Never trust that a disabled size/service wasn't selected by a stale
    # page still open in someone's browser (or a crafted request) - same
    # server-side-is-the-real-authority posture as page_range's
    # revalidation in api.py. A disabled size just can't contribute a
    # quantity, silently, same as any other "ignore this field" case in
    # this route; a disabled service becomes a real, visible error below.
    qty_by_size = {
        s: (_clamp_qty(request.form.get(f"qty_{s}"), default=0, minimum=0) if s in enabled_sizes else 0)
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
    # Indexed BEFORE the filename-truthiness filter, so a crop_<i> field
    # from the browser (positionally correlated to the original <input
    # multiple> selection) can't silently drift if a stray empty file
    # entry gets dropped here.
    raw_files = request.files.getlist("files")
    indexed_files = [(i, f) for i, f in enumerate(raw_files) if f and f.filename]
    files = [f for _, f in indexed_files]
    allowed_extensions = PHOTO_ALLOWED_EXTENSIONS if service == "photo" else ALLOWED_UPLOAD_EXTENSIONS

    errors = []
    if not availability.get(f"service:{service}", True):
        errors.append("Sorry, that isn't available right now - ask staff.")
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
        # The review step's final submit goes through fetch() (turn 2a),
        # not a native form POST, specifically so a validation failure
        # never navigates the page away - state.files/state.crops are
        # pure in-memory JS state that a real navigation would silently
        # wipe (a browser can't repopulate a file input's files from a
        # server response either way). A fetch request identifies itself
        # with this header; give it JSON to redisplay in place instead
        # of a full page it's never going to render as a document.
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(errors=errors), status
        return render_template(
            "upload/index.html",
            photo_sizes=PHOTO_SIZES,
            primary_photo_sizes=[s for s in PRIMARY_PHOTO_SIZES if s in enabled_sizes],
            more_photo_sizes=[s for s in MORE_PHOTO_SIZES if s in enabled_sizes],
            errors=errors,
            name=name,
            service=service,
            qty_by_size=qty_by_size,
            qty=qty,
            color_mode=color_mode,
            paper_finish=paper_finish,
            quality=quality,
            rates=rate_map(db.session),
            photo_service_enabled=availability.get("service:photo", True),
            document_service_enabled=availability.get("service:document", True),
        ), status

    if errors:
        return _rerender()

    upload_dir = current_app.config["UPLOAD_DIR"]
    tickets = []
    created_jobs = []
    for original_index, f in indexed_files:
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
            code_used=code,
        )
        # Document jobs never carry a manual crop - photo-only feature.
        crop_fractions = None
        if service == "document":
            # Sides/paper size are no longer customer choices - every
            # document prints single-sided on A4 (CLAUDE.md).
            job_fields.update(color_mode=color_mode, duplex=False, paper_size="A4", copies=qty)
        else:
            job_fields.update(paper_finish=paper_finish, quality=quality)
            crop_fractions = parse_crop_fractions(request.form.get(f"crop_{original_index}"))

        job = create_job_with_ticket(db.session, **job_fields)

        if service == "photo":
            for s in PHOTO_SIZES:
                n = qty_by_size[s]
                if n > 0:
                    job.photo_items.append(PhotoItemRow(size_name=s, quantity=n))
            db.session.commit()

        _process(job, manual_crop_fractions=crop_fractions)
        created_jobs.append(job)
        # failed: this specific file's own processing/pricing didn't
        # succeed (a bad image, a corrupt PDF, etc.) - the OTHER files in
        # the same submission are unaffected, so this is tracked per
        # ticket, not as one all-or-nothing flag for the whole batch.
        failed = job.status == JobStatus.FAILED or job.total_cost is None
        tickets.append(
            {"ticket": job.ticket_number, "filename": original_filename, "failed": failed}
        )

    if not tickets:
        if not errors:
            errors.append("Something went wrong - please try again.")
        return _rerender()

    # Sum of only the tickets that actually succeeded - "you won't be
    # charged for anything that didn't print" needs to be true even when
    # SOME (not all) files in a multi-file submission failed, not just
    # blank the whole total the moment any one of them does. Only goes
    # to None if literally nothing in the batch was priced.
    succeeded_costs = [job.total_cost for job in created_jobs if job.total_cost is not None]
    total_cost = sum(succeeded_costs) if succeeded_costs else None
    failed_tickets = [t["ticket"] for t in tickets if t["failed"]]

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
        "failed_tickets": failed_tickets,
        "total_cost": total_cost,
    }
    return redirect(url_for("upload.confirmation"))


@bp.route("/confirmation", methods=["GET"])
def confirmation():
    data = session.pop("pending_confirmation", None)
    if not data:
        return redirect(url_for("upload.form"))
    return render_template("upload/confirmation.html", **data)


# Statuses "ahead" counts against - anything still working through the
# pipeline before it's physically being printed. A job's own status only
# means "ahead" while IT is itself in this set too.
_QUEUED_STATUSES = (JobStatus.UPLOADED, JobStatus.PROCESSING, JobStatus.READY_FOR_REVIEW)


@bp.route("/status/<ticket>.json", methods=["GET"])
def status(ticket):
    """Turn 2b: replaces "we'll call your name" with a real queue
    position. Unauthenticated by design, same as /confirmation itself -
    a ticket number is already called aloud in the shop and carries no
    customer PII in this response (no name, just status/position/price).

    Ticket numbers are reused once a job goes terminal (CLAUDE.md - the
    active-only uniqueness index allows it), so this always resolves to
    the MOST RECENTLY created job with this ticket, never a stale one
    from a previous day/cycle.
    """
    job = (
        Job.query.filter_by(ticket_number=ticket).order_by(Job.created_at.desc()).first()
    )
    if job is None:
        return jsonify(error="not found"), 404

    if job.status == JobStatus.PRINTING:
        customer_status, ahead = "printing", 0
    elif job.status == JobStatus.DONE:
        customer_status, ahead = "ready", 0
    elif job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
        customer_status, ahead = "issue", 0
    else:
        customer_status = "queued"
        ahead = Job.query.filter(
            Job.status.in_(_QUEUED_STATUSES), Job.created_at < job.created_at
        ).count()

    return jsonify(status=customer_status, ahead=ahead, total_cost=job.total_cost)
