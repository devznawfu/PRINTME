"""Document job processing (CLAUDE.md): DOCX is silently converted to
PDF; PDF/JPG/PNG print as close to as-is as possible. Determines
page_count (needed by the pricing engine) and moves the job to
ready_for_review.
"""

import shutil
from pathlib import Path

from pypdf import PdfReader

from printme.models.job import JobStatus
from printme.services.docx_convert import convert_docx_to_pdf
from printme.services.pricing import price_job

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")


def _copy_into_processed_dir(source, processed_dir, job_id):
    """A copy of `source`, distinct from the original upload. Without
    this, a non-DOCX document's processed_path is literally the same
    file as its upload_path - retention.py's 2-day sweep deletes
    upload_path directly, which would silently destroy the "processed"
    copy CLAUDE.md says should survive until manual cleanup too, since
    they're the same file. Mirrors how DOCX->PDF conversion and the
    photo pipeline already produce a distinct processed_dir file."""
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    dest = processed_dir / f"job{job_id}{source.suffix}"
    shutil.copy2(source, dest)
    return dest


def count_pages(file_path):
    """Page count for pricing/printing. PDFs are counted properly;
    single-page image formats always count as 1 page."""
    path = Path(file_path)
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        return len(PdfReader(str(path)).pages)
    if ext in IMAGE_EXTENSIONS:
        return 1
    raise ValueError(f"unsupported document extension: {ext!r}")


def process_document_job(session, job, processed_dir):
    """Prepare a document Job for printing. DOCX is converted to PDF
    here - silently, the customer never sees this step. On error, the
    job is marked failed and flagged with the reason, then re-raised -
    same contract as process_photo_job."""
    try:
        source = Path(job.upload_path)
        ext = source.suffix.lower().lstrip(".")

        printable_path = (
            convert_docx_to_pdf(source, processed_dir)
            if ext == "docx"
            else _copy_into_processed_dir(source, processed_dir, job.id)
        )

        job.processed_path = str(printable_path)
        job.page_count = count_pages(printable_path)
        job.status = JobStatus.READY_FOR_REVIEW
        price_job(session, job)
        return job
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.flag_for_attention(f"Document processing failed: {exc}. Try re-uploading.")
        session.commit()
        raise
