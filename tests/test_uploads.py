import io

import pytest
from werkzeug.datastructures import FileStorage

from config import MAX_UPLOAD_SIZE_BYTES
from printme.services.uploads import (
    UploadRejected,
    build_storage_filename,
    extension_of,
    is_allowed_extension,
    is_within_size_limit,
    save_upload,
    validate_upload,
)


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


class TestSaveUpload:
    def test_saves_file_and_returns_original_name_and_path(self, tmp_path):
        f = fake_file("photo.jpg", b"fake-jpeg-bytes")
        original_name, saved_path = save_upload(f, tmp_path)

        assert original_name == "photo.jpg"
        assert saved_path.parent == tmp_path
        assert saved_path.exists()
        assert saved_path.read_bytes() == b"fake-jpeg-bytes"

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
