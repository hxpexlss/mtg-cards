"""HTTPS: selbstsignierte Zertifikate, Fingerabdrücke und Zertifikats-Pinning für Clients.

Selbstsignierte Zertifikate sind nicht von einer Zertifizierungsstelle bestätigt. Clients (App, Desktop)
merken sich deshalb beim ersten Verbinden den SHA-256-Fingerabdruck und prüfen ihn danach bei jeder
Verbindung ("Trust on first use"). Alternativ kann ein echtes Zertifikat verwendet werden, z.B. von
`tailscale cert <name>.ts.net` – dann ist kein Pinning nötig.
"""

import hashlib
import http.client
import os
import socket
import ssl
import subprocess
import urllib.request


class TlsError(Exception):
    pass


def fingerprint_der(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def fingerprint_file(cert_path):
    with open(cert_path, encoding="ascii") as f:
        pem = f.read()
    start = pem.index("-----BEGIN CERTIFICATE-----")
    end = pem.index("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")
    return fingerprint_der(ssl.PEM_cert_to_DER_cert(pem[start:end]))


def normalize_fp(fp):
    return (fp or "").replace(":", "").replace(" ", "").upper()


def ensure_self_signed(cert_path, key_path, extra_names=()):
    """Erzeugt ein selbstsigniertes Zertifikat (10 Jahre gültig), falls noch keins existiert."""
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(cert_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
    host = socket.gethostname()
    sans = [f"DNS:{host}", "DNS:localhost", "IP:127.0.0.1"] + [
        (f"IP:{n}" if n.replace(".", "").isdigit() else f"DNS:{n}") for n in extra_names if n]
    cmd = ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
           "-nodes", "-days", "3650", "-subj", f"/CN={host}/O=MTG Cards",
           "-addext", "subjectAltName=" + ",".join(dict.fromkeys(sans)),
           "-keyout", key_path, "-out", cert_path]
    old_umask = os.umask(0o077)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise TlsError("openssl ist nicht installiert (sudo apt install openssl)") from None
    finally:
        os.umask(old_umask)
    if res.returncode != 0:
        raise TlsError(f"Zertifikat konnte nicht erzeugt werden: {res.stderr.strip()}")
    os.chmod(cert_path, 0o644)
    return True


def server_context(cert_path, key_path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


def wrap_server_socket(httpd, cert_path, key_path):
    """Verschlüsselt einen (Threading)HTTPServer. Der Handshake läuft im Handler-Thread."""
    httpd.socket = server_context(cert_path, key_path).wrap_socket(
        httpd.socket, server_side=True, do_handshake_on_connect=False)


# ---------------------------------------------------------------------------
# Client mit Fingerabdruck-Pinning (für den Desktop im Server-Modus)
# ---------------------------------------------------------------------------

class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, fingerprint=None, **kwargs):
        self._fingerprint = normalize_fp(fingerprint)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE   # Prüfung erfolgt unten über den Fingerabdruck
        kwargs["context"] = ctx
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()
        got = fingerprint_der(self.sock.getpeercert(binary_form=True))
        if normalize_fp(got) != self._fingerprint:
            self.sock.close()
            raise ssl.SSLError(f"Zertifikats-Fingerabdruck stimmt nicht überein (Server sendet {got})")


class _PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, fingerprint):
        super().__init__()
        self._fp = fingerprint

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTPSConnection(host, fingerprint=self._fp, **kw), req)


def urlopen(req, timeout=30, fingerprint=None):
    """Wie urllib.request.urlopen; mit fingerprint wird ein selbstsigniertes Zertifikat per Pinning akzeptiert."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if fingerprint and url.startswith("https://"):
        opener = urllib.request.build_opener(_PinnedHandler(fingerprint))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_fingerprint(host, port, timeout=5):
    """Liest den Fingerabdruck des Server-Zertifikats (ohne Prüfung) – für den ersten Verbindungsaufbau."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            return fingerprint_der(s.getpeercert(binary_form=True))


def is_cert_verify_error(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)
