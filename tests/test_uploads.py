import io
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from config import MAX_UPLOAD_SIZE_BYTES, PHOTO_ALLOWED_EXTENSIONS
from printme.services.uploads import (
    UploadRejected,
    build_storage_filename,
    extension_of,
    is_allowed_extension,
    is_within_size_limit,
    save_upload,
    validate_file_storage,
    validate_upload,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_JPEG_BYTES = (FIXTURES / "face_one.jpg").read_bytes()


def fake_file(filename, content=b"hello", content_type="application/octet-stream"):
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )


class TestExtensionChecks:
    @pytest.mark.parametrize(
        "filename", ["photo.jpg", "photo.JPG", "scan.PDF", "form.docx", "id.png"]
    )
    def test_allowed_extensions_accepted(self, filename):
        assert is_allowed_extension(filename) is True

    @pytest.mark.parametrize(
        "filename", ["virus.exe", "archive.zip", "noextension", "resume.docx.exe"]
    )
    def test_disallowed_extensions_rejected(self, filename):
        assert is_allowed_extension(filename) is False

    def test_extension_of_is_case_insensitive_and_takes_last_segment(self):
        assert extension_of("a.b.PDF") == "pdf"

    @pytest.mark.parametrize("filename", ["photo.jpg", "id.png"])
    def test_photo_allowlist_accepts_images(self, filename):
        assert is_allowed_extension(filename, PHOTO_ALLOWED_EXTENSIONS) is True

    @pytest.mark.parametrize("filename", ["scan.pdf", "form.docx"])
    def test_photo_allowlist_rejects_documents(self, filename):
        assert is_allowed_extension(filename, PHOTO_ALLOWED_EXTENSIONS) is False
        assert extension_of("noext") == ""


class TestSizeChecks:
    def test_zero_bytes_rejected(self):
        assert is_within_size_limit(0) is False

    def test_at_limit_accepted(self):
        assert is_within_size_limit(MAX_UPLOAD_SIZE_BYTES) is True

    def test_over_limit_rejected(self):
        assert is_within_size_limit(MAX_UPLOAD_SIZE_BYTES + 1) is False


class TestValidateUpload:
    def test_valid_file_does_not_raise(self):
        validate_upload("photo.jpg", 1024)

    def test_no_filename_rejected(self):
        with pytest.raises(UploadRejected, match="No file selected"):
            validate_upload("", 1024)

    def test_bad_extension_rejected(self):
        with pytest.raises(UploadRejected, match="supported file type"):
            validate_upload("malware.exe", 1024)

    def test_pdf_rejected_under_photo_allowlist(self):
        with pytest.raises(UploadRejected, match="supported file type"):
            validate_upload("scan.pdf", 1024, PHOTO_ALLOWED_EXTENSIONS)

    def test_jpg_accepted_under_photo_allowlist(self):
        validate_upload("photo.jpg", 1024, PHOTO_ALLOWED_EXTENSIONS)

    def test_empty_file_rejected(self):
        with pytest.raises(UploadRejected, match="empty"):
            validate_upload("photo.jpg", 0)

    def test_oversized_file_rejected(self):
        with pytest.raises(UploadRejected, match="limit"):
            validate_upload("scan.pdf", MAX_UPLOAD_SIZE_BYTES + 1)


class TestBuildStorageFilename:
    def test_preserves_extension_lowercased(self):
        name = build_storage_filename("Photo.JPG")
        assert name.endswith(".jpg")

    def test_two_calls_never_collide(self):
        assert build_storage_filename("a.pdf") != build_storage_filename("a.pdf")

    def test_path_traversal_in_original_name_does_not_leak_into_storage_name(self):
        name = build_storage_filename("../../etc/passwd.jpg")
        assert "/" not in name and ".." not in name


class TestContentValidation:
    def test_real_jpeg_passes(self):
        f = fake_file("photo.jpg", REAL_JPEG_BYTES)
        validate_file_storage(f)  # does not raise

    def test_text_renamed_to_jpg_is_rejected(self):
        f = fake_file("photo.jpg", b"just some plain text, not an image")
        with pytest.raises(UploadRejected, match="doesn't look like a real JPG"):
            validate_file_storage(f)

    def test_jpeg_bytes_renamed_to_png_is_rejected(self):
        """Real image data, but the wrong format for its extension -
        content has to match the claimed type, not just decode as
        *some* image."""
        f = fake_file("photo.png", REAL_JPEG_BYTES)
        with pytest.raises(UploadRejected, match="doesn't look like a real PNG"):
            validate_file_storage(f)

    def test_text_renamed_to_pdf_is_rejected(self):
        f = fake_file("scan.pdf", b"not actually a pdf")
        with pytest.raises(UploadRejected, match="doesn't look like a real PDF"):
            validate_file_storage(f)

    def test_text_renamed_to_docx_is_rejected(self):
        f = fake_file("form.docx", b"not actually a docx")
        with pytest.raises(UploadRejected, match="doesn't look like a real DOCX"):
            validate_file_storage(f)


class TestSaveUpload:
    def test_saves_file_and_returns_original_name_and_path(self, tmp_path):
        f = fake_file("photo.jpg", REAL_JPEG_BYTES)
        original_name, saved_path = save_upload(f, tmp_path)

        assert original_name == "photo.jpg"
        assert saved_path.parent == tmp_path
        assert saved_path.exists()
        assert saved_path.read_bytes() == REAL_JPEG_BYTES

    def test_saved_file_is_not_executable(self, tmp_path):
        f = fake_file("photo.jpg", REAL_JPEG_BYTES)
        _, saved_path = save_upload(f, tmp_path)
        assert not (saved_path.stat().st_mode & 0o111)

    def test_rejects_bad_extension_without_writing_anything(self, tmp_path):
        f = fake_file("virus.exe", b"x")
        with pytest.raises(UploadRejected):
            save_upload(f, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_rejects_empty_file_without_writing_anything(self, tmp_path):
        f = fake_file("photo.jpg", b"")
        with pytest.raises(UploadRejected):
            save_upload(f, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_size_check_ignores_spoofed_content_length_header(self, tmp_path):
        # Real body is empty, but a malicious/broken client claims 999 bytes.
        f = FileStorage(
            stream=io.BytesIO(b""),
            filename="photo.jpg",
            content_length=999,
        )
        with pytest.raises(UploadRejected, match="empty"):
            save_upload(f, tmp_path)
