"""QR code generation for the admin dashboard - lets staff print codes
customers scan to join the WiFi and reach the upload portal, without
needing to generate them externally (which would go stale the moment
the router hands out a different LAN IP, or the WiFi password rotates)."""

import io

import qrcode

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


def generate_upload_qr_png(url):
    """PNG bytes of a QR code encoding `url`."""
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_wifi_qr_png(ssid, password):
    """PNG bytes of a QR code that a phone's camera app recognizes as a
    WiFi network to join directly (the WIFI: URI scheme most Android
    and iOS camera apps support natively). Always WPA - the router's
    own security type (WPA2-PSK[AES]) falls under this."""
    payload = f"WIFI:T:WPA;S:{_escape_wifi_field(ssid)};P:{_escape_wifi_field(password)};;"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
