from unittest.mock import patch

import pytest
from pypdf import PdfWriter

from printme.extensions import db
from printme.models import Job, JobStatus, seed_defaults
from printme.services.document_pipeline import count_pages, process_document_job


def make_pdf(path, n_pages=1):
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def make_document_job(upload_path, **overrides):
    defaults = dict(
        ticket_number="P-002",
        customer_name="Ben",
        service_type="document",
        original_filename=upload_path.name,
        upload_path=str(upload_path),
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestCountPages:
    def test_pdf_page_count(self, tmp_path):
        pdf = make_pdf(tmp_path / "doc.pdf", n_pages=4)
        assert count_pages(pdf) == 4

    @pytest.mark.parametrize("ext", ["jpg", "jpeg", "png"])
    def test_image_formats_count_as_one_page(self, tmp_path, ext):
        img = tmp_path / f"scan.{ext}"
        img.write_bytes(b"not a real image, extension is all that matters here")
        assert count_pages(img) == 1

    def test_unsupported_extension_raises(self, tmp_path):
        bad = tmp_path / "notes.txt"
        bad.write_text("hello")
        with pytest.raises(ValueError, match="unsupported"):
            count_pages(bad)


class TestProcessDocumentJobPassthrough:
    def test_pdf_passes_through_with_page_count_and_ready_status(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            pdf = make_pdf(tmp_path / "doc.pdf", n_pages=2)
            job = make_document_job(pdf)
            db.session.add(job)
            db.session.commit()

            process_document_job(db.session, job, tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.page_count == 2
            assert fetched.processed_path == str(pdf)
            assert fetched.status == JobStatus.READY_FOR_REVIEW
            assert fetched.needs_attention is False
            assert fetched.total_cost is not None

    def test_image_passes_through_as_one_page(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            img = tmp_path / "scan.jpg"
            img.write_bytes(b"fake jpeg bytes")
            job = make_document_job(img)
            db.session.add(job)
            db.session.commit()

            process_document_job(db.session, job, tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.page_count == 1
            assert fetched.processed_path == str(img)


class TestProcessDocumentJobDocxConversion:
    def test_docx_is_converted_and_priced_from_the_resulting_pdf(self, app, tmp_path):
        """soffice isn't installed here, so convert_docx_to_pdf itself is
        mocked to simulate a successful conversion - proves
        process_document_job wires page counting to the CONVERTED PDF,
        not the original docx, and never exposes the intermediate step
        beyond storing the converted path."""
        with app.app_context():
            seed_defaults(db.session)
            docx = tmp_path / "form.docx"
            docx.write_bytes(b"fake docx bytes")
            converted_pdf = make_pdf(tmp_path / "form.pdf", n_pages=3)

            job = make_document_job(docx)
            db.session.add(job)
            db.session.commit()

            with patch(
                "printme.services.document_pipeline.convert_docx_to_pdf",
                return_value=converted_pdf,
            ) as mock_convert:
                process_document_job(db.session, job, tmp_path)

            mock_convert.assert_called_once()
            fetched = db.session.get(Job, job.id)
            assert fetched.page_count == 3
            assert fetched.processed_path == str(converted_pdf)
            assert fetched.status == JobStatus.READY_FOR_REVIEW

    def test_real_docx_conversion_fails_without_libreoffice_and_marks_job_failed(
        self, app, tmp_path
    ):
        """No mocking - this is the real, current state of this dev
        machine (no LibreOffice installed), proving the failure path
        behaves correctly rather than crashing uncaught."""
        with app.app_context():
            docx = tmp_path / "form.docx"
            docx.write_bytes(b"fake docx bytes")
            job = make_document_job(docx)
            db.session.add(job)
            db.session.commit()

            with pytest.raises(Exception):
                process_document_job(db.session, job, tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.status == JobStatus.FAILED
            assert fetched.needs_attention is True
            assert "Document processing failed" in fetched.attention_reason


class TestProcessDocumentJobFailure:
    def test_corrupt_pdf_marks_job_failed_and_reraises(self, app, tmp_path):
        with app.app_context():
            bad_pdf = tmp_path / "broken.pdf"
            bad_pdf.write_bytes(b"this is not a real pdf")
            job = make_document_job(bad_pdf)
            db.session.add(job)
            db.session.commit()

            with pytest.raises(Exception):
                process_document_job(db.session, job, tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.status == JobStatus.FAILED
            assert fetched.needs_attention is True
            assert "Document processing failed" in fetched.attention_reason
