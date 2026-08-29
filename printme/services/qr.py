"""QR code generation for the admin dashboard - lets staff print codes
customers scan to join the WiFi and reach the upload portal, without
needing to generate them externally (which would go stale the moment
the router hands out a different LAN IP, or the WiFi password rotates)."""

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_H

# Characters the WIFI: QR payload format treats as field separators -
# each must be backslash-escaped if it appears literally inside the
# SSID or password. Order matters: escape backslashes themselves first,
# so a genuine backslash a caller included doesn't get double-escaped
# by one of the later substitutions.
_WIFI_ESCAPE_CHARS = ("\\", ";", ",", ":", '"')


def _escape_wifi_field(value):
    for char in _WIFI_ESCAPE_CHARS:
        value = value.replace(char, "\\" + char)
    return value


def _make_qr_png(payload):
    """High error-correction level (~30% of the code can be damaged or
    obscured and still scan) - this is printed on paper at a shop
    counter, not shown on a screen, so it needs to survive creases,
    smudges, and a phone camera at an angle."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_upload_qr_png(url):
    """PNG bytes of a QR code encoding `url`."""
    return _make_qr_png(url)


def generate_wifi_qr_png(ssid, password):
    """PNG bytes of a QR code that a phone's camera app recognizes as a
    WiFi network to join directly (the WIFI: URI scheme iOS's and
    Android's own built-in camera apps support natively - most
    third-party "QR scanner" apps from the Play Store don't implement
    this and will just show the raw text instead, which is a real
    limitation of those apps, not something fixable from this payload).
    H:false is included explicitly (not just omitted) since some
    stricter parsers expect every field present rather than assuming a
    default. Always WPA - the router's own security type
    (WPA2-PSK[AES]) falls under this."""
    payload = f"WIFI:T:WPA;S:{_escape_wifi_field(ssid)};P:{_escape_wifi_field(password)};H:false;;"
    return _make_qr_png(payload)
