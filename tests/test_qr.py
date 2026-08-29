import cv2
import numpy as np

from printme.services.qr import generate_upload_qr_png, generate_wifi_qr_png


def _decode(png_bytes):
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    data, _points, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return data


class TestGenerateUploadQrPng:
    def test_returns_real_png_bytes(self):
        png_bytes = generate_upload_qr_png("http://192.168.1.13:5000/")
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    def test_different_urls_produce_different_codes(self):
        a = generate_upload_qr_png("http://192.168.1.13:5000/")
        b = generate_upload_qr_png("http://10.0.0.5:5000/")
        assert a != b


class TestGenerateWifiQrPng:
    def test_returns_real_png_bytes(self):
        png_bytes = generate_wifi_qr_png("PRINTME!", "hunter22")
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    def test_decodes_to_a_scannable_wifi_payload(self):
        png_bytes = generate_wifi_qr_png("PRINTME!", "hunter22")
        assert _decode(png_bytes) == "WIFI:T:WPA;S:PRINTME!;P:hunter22;;"

    def test_escapes_special_characters_in_ssid_and_password(self):
        png_bytes = generate_wifi_qr_png('shop;wifi,"main"', 'ab\\c;d,e"f')
        assert _decode(png_bytes) == 'WIFI:T:WPA;S:shop\\;wifi\\,\\"main\\";P:ab\\\\c\\;d\\,e\\"f;;'
