"""Pricing engine: computes cost only - no payment tracking/processing
(CLAUDE.md). Payment stays physical/cash, handled at the counter."""

from printme.models.job import Job, JobStatus
from printme.models.pricing import rate_map


def compute_cost(job, rates):
    """Total cost for a job given a {rate_key: price} map (see
    printme.models.pricing.rate_map). Does not touch the DB or the job
    row - pure computation over what's already loaded."""
    if job.service_type == "photo":
        finish = job.paper_finish or "bond"
        quality = job.quality or "standard"
        total = 0.0
        for row in job.photo_items:
            key = f"{row.size_name}-{finish}-{quality}"
            if key not in rates:
                raise ValueError(f"missing rate for {key!r}")
            total += rates[key] * row.quantity
        return total

    if job.service_type == "document":
        if job.page_count is None:
            raise ValueError(
                "cannot price a document job before page_count is known"
            )
        rate_key = "color_page" if job.color_mode == "color" else "bw_page"
        copies = job.copies or 1
        return rates[rate_key] * job.page_count * copies

    raise ValueError(f"unknown service_type: {job.service_type!r}")


def price_job(session, job):
    """Compute job's total cost from the current rate table and persist
    it to job.total_cost (the "auto-total ... shown on the job card")."""
    job.total_cost = compute_cost(job, rate_map(session))
    session.commit()
    return job.total_cost


def reprice_active_jobs(session):
    """Recompute total_cost for every active job - e.g. after an admin
    edits a rate. Document jobs whose page_count isn't known yet are
    skipped (priced once conversion fills it in) rather than failing the
    whole batch."""
    rates = rate_map(session)
    active_jobs = session.query(Job).filter(Job.status.in_(JobStatus.ACTIVE)).all()

    repriced = []
    for job in active_jobs:
        try:
            job.total_cost = compute_cost(job, rates)
            repriced.append(job)
        except ValueError:
            continue
    session.commit()
    return repriced
