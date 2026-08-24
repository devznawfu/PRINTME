"""DOCX -> PDF conversion via LibreOffice headless (CLAUDE.md: silent,
no visible intermediate step shown to the customer).

Not installed on this dev machine, so the subprocess call is verified
here only via mocking; confirm for real (install LibreOffice, or on the
target admin PC) before relying on this in production.
"""

import shutil
import subprocess
from pathlib import Path


class ConversionError(Exception):
    """DOCX -> PDF conversion failed."""


def soffice_available():
    return shutil.which("soffice") is not None


def convert_docx_to_pdf(docx_path, out_dir, timeout=60):
    """Convert docx_path to a PDF in out_dir using LibreOffice headless.
    Returns the path to the resulting PDF."""
    if not soffice_available():
        raise ConversionError("LibreOffice (soffice) is not installed or not on PATH")

    docx_path = Path(docx_path)
    out_dir = Path(out_dir)

    result = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ConversionError(
            f"soffice failed (code {result.returncode}): {result.stderr.strip()}"
        )

    expected = out_dir / (docx_path.stem + ".pdf")
    if not expected.exists():
        raise ConversionError(
            f"soffice reported success but {expected} was not created"
        )
    return expected
