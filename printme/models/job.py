"""Core job models: Job and PhotoItem.

A Job is one customer submission. Photo jobs carry PhotoItem rows (size +
quantity) that expand into layout_engine.types.PhotoItem at pack time.
Document jobs carry their print options directly on the Job row.
"""

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from printme.extensions import db
from printme.layout_engine.types import PhotoItem as LayoutPhotoItem


class JobStatus:
    """String constants for the status flow in CLAUDE.md."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    PRINTING = "printing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = (UPLOADED, PROCESSING, READY_FOR_REVIEW, PRINTING, DONE, FAILED, CANCELLED)
    ACTIVE = (UPLOADED, PROCESSING, READY_FOR_REVIEW, PRINTING)
    # Terminal, non-active statuses shown on the admin History page.
    TERMINAL = (DONE, FAILED, CANCELLED)


_ACTIVE_STATUSES_SQL = ", ".join(f"'{s}'" for s in JobStatus.ACTIVE)
MAX_TICKET_ALLOCATION_ATTEMPTS = 5


SERVICE_TYPES = ("photo", "document")
COLOR_MODES = ("color", "bw")
PAPER_SIZES = ("Letter", "A4", "Legal")
# Photo printing only. Both are priced (see models/pricing.py's
# composite {size}-{finish}-{quality} rate keys) - defaulted to
# "bond"/"standard" wherever unset (e.g. document jobs, or a job
# created before these fields existed).
PAPER_FINISHES = ("glossy", "bond")
QUALITY_LEVELS = ("standard", "high")
# Photo printing only. NULL for a job created before this field
# existed, or a document job - not "auto" by default, since we
# genuinely don't know for those.
PROCESSED_SOURCE = ("auto", "manual")
# Turn 3c: why a reprint was needed - only set on a job that IS a
# reprint (reprint_of is not None). Not DB-enforced, same pattern as
# every other "enum-like" column in this model - validated at the
# route layer.
REPRINT_REASONS = ("bad_print", "paper_jam", "wrong_crop", "wants_more")
REPRINT_REASON_LABELS = {
    "bad_print": "Bad print",
    "paper_jam": "Paper jam",
    "wrong_crop": "Wrong crop",
    "wants_more": "Customer wants more",
}


def generate_ticket_number():
    """Next free ticket number among active jobs, e.g. ``P-001``.

    Numbers of done/failed jobs are reusable - CLAUDE.md only requires
    never colliding with an *active* job.
    """
    active = Job.query.filter(Job.status.in_(JobStatus.ACTIVE)).all()
    used = set()
    for job in active:
        try:
            used.add(int(job.ticket_number.split("-")[1]))
        except (IndexError, ValueError):
            continue

    n = 1
    while n in used:
        n += 1
    return f"P-{n:03d}"


def create_job_with_ticket(session, **job_fields):
    """Create and commit a Job with a freshly-allocated ticket number,
    safe against two callers racing to allocate the same number.

    generate_ticket_number() only *reads* active jobs - it doesn't reserve
    anything - so two concurrent uploads can compute the same "next free"
    ticket before either commits. The partial unique index on
    (ticket_number) among active statuses turns that race into an
    IntegrityError instead of a silent duplicate; this retries with a
    freshly recomputed number when that happens.
    """
    for attempt in range(MAX_TICKET_ALLOCATION_ATTEMPTS):
        job = Job(ticket_number=generate_ticket_number(), **job_fields)
        session.add(job)
        try:
            session.commit()
            return job
        except IntegrityError:
            session.rollback()
    raise RuntimeError(
        f"could not allocate a free ticket number after {MAX_TICKET_ALLOCATION_ATTEMPTS} attempts"
    )


class Job(db.Model):
    __tablename__ = "jobs"

    __table_args__ = (
        db.Index(
            "ix_jobs_active_ticket_unique",
            "ticket_number",
            unique=True,
            sqlite_where=db.text(f"status IN ({_ACTIVE_STATUSES_SQL})"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(8), nullable=False, index=True)
    customer_name = db.Column(db.String(120), nullable=False)

    service_type = db.Column(db.String(16), nullable=False)  # photo|document
    status = db.Column(
        db.String(24), nullable=False, default=JobStatus.UPLOADED, index=True
    )

    # A flag, NOT a status (CLAUDE.md). When set, attention_reason must say
    # the SPECIFIC reason so staff know what to check.
    needs_attention = db.Column(db.Boolean, nullable=False, default=False)
    attention_reason = db.Column(db.Text)

    original_filename = db.Column(db.String(255), nullable=False)
    upload_path = db.Column(db.String(500), nullable=False)
    processed_path = db.Column(db.String(500))  # filled after processing

    # Document options (null for photo jobs). page_count is unknown at
    # upload; it is filled after PDF conversion/inspection.
    color_mode = db.Column(db.String(8))  # color|bw
    duplex = db.Column(db.Boolean)
    paper_size = db.Column(db.String(8))  # Letter|A4|Legal
    copies = db.Column(db.Integer, default=1)
    page_count = db.Column(db.Integer)

    # Photo options (null for document jobs).
    paper_finish = db.Column(db.String(8))  # glossy|bond
    quality = db.Column(db.String(8))  # standard|high
    processed_source = db.Column(db.String(8))  # auto|manual

    # Turn 3c: a reprint is a brand-new Job row pointing at the original
    # it replaces, NOT a mutation of the original - the original's own
    # history (what actually happened to it) stays intact. reprint_of
    # is NULL for every normal job.
    reprint_of = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=True, index=True)
    reprint_reason = db.Column(db.String(24))  # REPRINT_REASONS, see above

    # Cost snapshot written by the pricing engine when it computes a total.
    total_cost = db.Column(db.Float)

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    photo_items = db.relationship(
        "PhotoItemRow",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    # Self-referential: original_job navigates a reprint back to what it
    # replaces; reprints (the backref) navigates the original forward to
    # every reprint made of it, in creation order via display_ticket's
    # own sort - needed there since a 2nd/3rd reprint of the same
    # original displays as "-R2"/"-R3", not stored anywhere directly.
    original_job = db.relationship("Job", remote_side=[id], backref="reprints")

    def flag_for_attention(self, reason):
        """Mark this job as needing staff review, with the specific reason."""
        if not reason or not str(reason).strip():
            raise ValueError("needs_attention requires a specific reason")
        self.needs_attention = True
        self.attention_reason = str(reason).strip()

    def clear_attention(self):
        self.needs_attention = False
        self.attention_reason = None

    @property
    def display_ticket(self):
        """Ticket number as shown to staff/customers. Unchanged for a
        normal job. A reprint displays with a "-R" ("-R2", "-R3", ... for
        a 2nd/3rd reprint of the same original) suffix appended to the
        ORIGINAL's ticket number - computed here at display time, never
        stored in ticket_number itself (Decision #4: keeps generate_
        ticket_number()'s parsing/active-uniqueness logic untouched, and
        a reprint still gets its own independently-generated ticket_
        number under the hood, just not the one shown)."""
        if self.reprint_of is None:
            return self.ticket_number
        siblings = sorted(self.original_job.reprints, key=lambda j: j.created_at)
        index = siblings.index(self) + 1
        suffix = "R" if index == 1 else f"R{index}"
        return f"{self.original_job.ticket_number}-{suffix}"


def _require_reason_when_flagged(mapper, connection, target):
    """Enforce flag+reason pairing on both insert and update - e.g. bulk
    inserts, or a job flagged after the fact (the normal case: jobs are
    flagged once processing finds a problem, not at upload time)."""
    if target.needs_attention and not (
        target.attention_reason and target.attention_reason.strip()
    ):
        raise ValueError("needs_attention requires a specific reason")


def _require_reprint_of_when_reason_set(mapper, connection, target):
    """Mirrors the flag+reason pairing above: reprint_reason only makes
    sense on a job that IS a reprint."""
    if target.reprint_reason and target.reprint_of is None:
        raise ValueError("reprint_reason requires reprint_of to be set")
    if target.reprint_reason and target.reprint_reason not in REPRINT_REASONS:
        raise ValueError(f"invalid reprint_reason: {target.reprint_reason!r}")


event.listens_for(Job, "before_insert")(_require_reason_when_flagged)
event.listens_for(Job, "before_update")(_require_reason_when_flagged)
event.listens_for(Job, "before_insert")(_require_reprint_of_when_reason_set)
event.listens_for(Job, "before_update")(_require_reprint_of_when_reason_set)


class PhotoItemRow(db.Model):
    """One requested photo print (size + quantity) belonging to a Job."""

    __tablename__ = "photo_items"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True
    )
    size_name = db.Column(db.String(16), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    job = db.relationship("Job", back_populates="photo_items")

    def to_layout_items(self, item_id_prefix=None):
        """Expand into layout_engine.types.PhotoItem, one per copy.

        IDs are unique within a pack() call and encode the owning row so a
        PlacedItem traces back to this job's print.
        """
        prefix = (
            item_id_prefix
            if item_id_prefix is not None
            else f"job{self.job_id}-row{self.id}"
        )
        return [
            LayoutPhotoItem(item_id=f"{prefix}-{i}", size_name=self.size_name)
            for i in range(1, self.quantity + 1)
        ]
