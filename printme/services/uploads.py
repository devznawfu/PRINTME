"""Upload validation and storage. CLAUDE.md: max 15 MB, allowed
extensions .pdf/.jpg/.png/.docx."""

import os
import uuid
import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_SIZE_BYTES

# Files are readable/writable by the owner only - never executable.
# The meaningful property on POSIX (Windows' NTFS has no equivalent
# execute bit; extension/association decides that there instead), but
# harmless to set unconditionally.
_STORED_FILE_MODE = 0o600


class UploadRejected(Exception):
    """A file failed validation (bad extension, empty, or too large)."""


def extension_of(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def is_allowed_extension(filename):
    return extension_of(filename) in ALLOWED_UPLOAD_EXTENSIONS


def is_within_size_limit(size_bytes):
    return 0 < size_bytes <= MAX_UPLOAD_SIZE_BYTES


def validate_upload(filename, size_bytes):
    """Raise UploadRejected with a customer-facing reason, or return
    None if the file is acceptable."""
    if not filename:
        raise UploadRejected("No file selected.")
    if not is_allowed_extension(filename):
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise UploadRejected(f"'{filename}' isn't a supported file type ({allowed}).")
    if size_bytes <= 0:
        raise UploadRejected(f"'{filename}' is empty.")
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise UploadRejected(f"'{filename}' is larger than the {max_mb} MB limit.")


def _looks_like_image(stream, expected_format):
    """True if `stream` decodes as a real image in `expected_format`
    (e.g. "JPEG"/"PNG") - not just named like one."""
    stream.seek(0)
    try:
        with Image.open(stream) as img:
            fmt = img.format
            img.verify()  # raises on structurally invalid image data
        return fmt == expected_format
    except Exception:
        return False
    finally:
        stream.seek(0)


def _looks_like_pdf(stream):
    stream.seek(0)
    try:
        reader = PdfReader(stream)
        len(reader.pages)  # forces enough parsing to catch garbage
        return True
    except Exception:
        return False
    finally:
        stream.seek(0)


def _looks_like_docx(stream):
    """DOCX is a zip with a specific internal shape - not full
    schema validation, just enough to catch "this isn't actually a
    docx" (e.g. a renamed .exe or plain text file)."""
    stream.seek(0)
    try:
        with zipfile.ZipFile(stream) as z:
            names = z.namelist()
            return "[Content_Types].xml" in names and any(
                n.startswith("word/") for n in names
            )
    except Exception:
        return False
    finally:
        stream.seek(0)


_CONTENT_CHECKS = {
    "jpg": lambda fs: _looks_like_image(fs.stream, "JPEG"),
    "png": lambda fs: _looks_like_image(fs.stream, "PNG"),
    "pdf": lambda fs: _looks_like_pdf(fs.stream),
    "docx": lambda fs: _looks_like_docx(fs.stream),
}


def build_storage_filename(original_filename):
    """A collision-safe, path-safe name to store the upload under. The
    original filename is kept only as DB metadata (Job.original_filename),
    never used to build a filesystem path."""
    ext = extension_of(original_filename)
    return f"{uuid.uuid4().hex}.{ext}"


def file_storage_size(file_storage):
    """Determine a Werkzeug FileStorage's size without trusting
    Content-Length (can be spoofed or absent)."""
    stream = file_storage.stream
    pos = stream.tell()
    stream.seek(0, 2)  # SEEK_END
    size = stream.tell()
    stream.seek(pos)
    return size


def validate_file_storage(file_storage):
    """validate_upload() for a Werkzeug FileStorage directly, plus a
    real content check the metadata-only validate_upload() can't do
    (it doesn't have the bytes) - the claimed extension has to match
    what the file actually is, not just its name. Lets a caller check
    a whole batch of files up front, before saving any of them, e.g.
    so one bad file can reject the submission atomically instead of
    silently dropping just that file."""
    filename = file_storage.filename or ""
    validate_upload(filename, file_storage_size(file_storage))

    ext = extension_of(filename)
    check = _CONTENT_CHECKS.get(ext)
    if check is not None and not check(file_storage):
        raise UploadRejected(f"'{filename}' doesn't look like a real {ext.upper()} file.")


def save_upload(file_storage, upload_dir):
    """Validate and save a Flask/Werkzeug FileStorage to upload_dir.

    Returns (original_filename, saved_path). Raises UploadRejected
    without writing anything if validation fails.
    """
    filename = file_storage.filename or ""
    validate_file_storage(file_storage)

    upload_dir = Path(upload_dir)
    dest = upload_dir / build_storage_filename(filename)
    file_storage.save(dest)
    os.chmod(dest, _STORED_FILE_MODE)
    return filename, dest
