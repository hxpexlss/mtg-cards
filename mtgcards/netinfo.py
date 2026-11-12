"""Netzwerk-Infos: lokale Adressen, Tailscale-Erkennung, UDP-Discovery."""

import ipaddress
import json
import shutil
import socket
import subprocess
import threading

from . import APP_NAME, DISCOVERY_MAGIC, DISCOVERY_PORT, __version__

_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def local_addresses():
    """Liste von {"iface", "address", "tailscale"} für alle IPv4-Adressen außer Loopback."""
    out = []
    try:
        res = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True,
                             text=True, timeout=2, check=False)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            iface = parts[1]
            addr = parts[3].split("/")[0]
            if addr.startswith("127."):
                continue
            ts = iface.startswith("tailscale") or ipaddress.ip_address(addr) in _TAILSCALE_NET
            out.append({"iface": iface, "address": addr, "tailscale": ts})
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if not out:
        # Windows / kein "ip": alle IPv4-Adressen des Rechners über den Hostnamen
        try:
            seen = set()
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addr = info[4][0]
                if addr.startswith("127.") or addr in seen:
                    continue
                seen.add(addr)
                ts = ipaddress.ip_address(addr) in _TAILSCALE_NET
                out.append({"iface": "Tailscale" if ts else "LAN", "address": addr, "tailscale": ts})
        except (OSError, ValueError):
            pass
    if not out:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                out.append({"iface": "?", "address": s.getsockname()[0], "tailscale": False})
        except OSError:
            pass
    return out


def tailscale_dns_name():
    """MagicDNS-Name dieses Rechners (falls Tailscale installiert ist)."""
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "status", "--self", "--json"], capture_output=True,
                             text=True, timeout=3, check=False)
        name = json.loads(res.stdout).get("Self", {}).get("DNSName", "")
        return name.rstrip(".") or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class DiscoveryResponder(threading.Thread):
    """Antwortet auf UDP-Broadcasts der App, damit sie den Rechner im WLAN findet.

    (In Tailscale gibt es keine Broadcasts – dort die 100.x-IP oder den MagicDNS-Namen eintragen.)
    """

    def __init__(self, port, kind, tls_fingerprint=None):
        super().__init__(daemon=True, name="discovery")
        self.http_port = port
        self.kind = kind
        self.tls_fingerprint = tls_fingerprint
        self.sock = None

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError as e:
            print(f"[discovery] UDP-Port {DISCOVERY_PORT} nicht verfügbar: {e}")
            return
        reply = json.dumps({
            "app": APP_NAME, "version": __version__, "name": socket.gethostname(),
            "port": self.http_port, "kind": self.kind,
            "tls": bool(self.tls_fingerprint), "fingerprint": self.tls_fingerprint,
        }).encode()
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except OSError:
                return
            if data.strip() == DISCOVERY_MAGIC:
                try:
                    self.sock.sendto(reply, addr)
                except OSError:
                    pass

    def stop(self):
        if self.sock:
            self.sock.close()


def discover(timeout=1.5):
    """Sucht MTG-Cards-Server im lokalen Netz (für Tests/CLI)."""
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(DISCOVERY_MAGIC, ("255.255.255.255", DISCOVERY_PORT))
        try:
            while True:
                data, addr = s.recvfrom(2048)
                info = json.loads(data.decode())
                info["address"] = addr[0]
                found[(addr[0], info.get("port"))] = info
        except (socket.timeout, ValueError):
            pass
    return list(found.values())
