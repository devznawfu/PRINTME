"""Document job processing (CLAUDE.md): DOCX is silently converted to
PDF; PDF/JPG/PNG print as close to as-is as possible. Determines
page_count (needed by the pricing engine) and moves the job to
ready_for_review.
"""

from pathlib import Path

from pypdf import PdfReader

from printme.models.job import JobStatus
from printme.services.docx_convert import convert_docx_to_pdf
from printme.services.pricing import price_job

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")


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
            convert_docx_to_pdf(source, processed_dir) if ext == "docx" else source
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
