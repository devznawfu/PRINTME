import subprocess
from unittest.mock import patch

import pytest

from printme.services.docx_convert import ConversionError, convert_docx_to_pdf


def test_soffice_not_available_on_this_dev_machine():
    """Documents the real state of this environment - LibreOffice isn't
    installed, so DOCX conversion must be verified separately (mocking
    below, and manually on a machine with LibreOffice/on the admin PC)."""
    from printme.services.docx_convert import soffice_available

    assert soffice_available() is False


def test_raises_clear_error_when_soffice_is_unavailable(tmp_path):
    docx = tmp_path / "form.docx"
    docx.write_bytes(b"not a real docx, doesn't matter for this test")

    with pytest.raises(ConversionError, match="not installed"):
        convert_docx_to_pdf(docx, tmp_path)


class TestConvertDocxToPdfMocked:
    """soffice isn't installed here, so the subprocess call itself is
    mocked - these prove convert_docx_to_pdf's own logic (return path,
    error handling) is correct given what soffice *would* report."""

    def test_successful_conversion_returns_expected_pdf_path(self, tmp_path):
        docx = tmp_path / "form.docx"
        docx.write_bytes(b"fake docx content")
        expected_pdf = tmp_path / "form.pdf"

        def fake_run(*args, **kwargs):
            expected_pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        with patch("printme.services.docx_convert.soffice_available", return_value=True), \
             patch("printme.services.docx_convert.subprocess.run", side_effect=fake_run):
            result = convert_docx_to_pdf(docx, tmp_path)

        assert result == expected_pdf
        assert result.exists()

    def test_nonzero_return_code_raises_with_stderr(self, tmp_path):
        docx = tmp_path / "form.docx"
        docx.write_bytes(b"fake docx content")

        fake_result = subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="soffice: unrecoverable error"
        )
        with patch("printme.services.docx_convert.soffice_available", return_value=True), \
             patch("printme.services.docx_convert.subprocess.run", return_value=fake_result):
            with pytest.raises(ConversionError, match="unrecoverable error"):
                convert_docx_to_pdf(docx, tmp_path)

    def test_reported_success_but_missing_output_file_raises(self, tmp_path):
        docx = tmp_path / "form.docx"
        docx.write_bytes(b"fake docx content")

        fake_result = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
        with patch("printme.services.docx_convert.soffice_available", return_value=True), \
             patch("printme.services.docx_convert.subprocess.run", return_value=fake_result):
            with pytest.raises(ConversionError, match="was not created"):
                convert_docx_to_pdf(docx, tmp_path)
