from printme.services.qr import generate_upload_qr_png


class TestGenerateUploadQrPng:
    def test_returns_real_png_bytes(self):
        png_bytes = generate_upload_qr_png("http://192.168.1.13:5000/")
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    def test_different_urls_produce_different_codes(self):
        a = generate_upload_qr_png("http://192.168.1.13:5000/")
        b = generate_upload_qr_png("http://10.0.0.5:5000/")
        assert a != b
