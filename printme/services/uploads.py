"""Upload validation and storage. CLAUDE.md: max 15 MB, allowed
extensions .pdf/.jpg/.png/.docx."""

import uuid
from pathlib import Path

from config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_SIZE_BYTES


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
    """validate_upload() for a Werkzeug FileStorage directly - lets a
    caller check a whole batch of files up front, before saving any of
    them, e.g. so one bad file can reject the submission atomically
    instead of silently dropping just that file."""
    validate_upload(file_storage.filename or "", file_storage_size(file_storage))


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
    return filename, dest
