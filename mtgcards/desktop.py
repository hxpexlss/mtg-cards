"""Desktop-Anwendung: `mtg-cards`.

Startet den eingebetteten Server (lokale Datenbank oder Proxy zum Headless-Server)
und zeigt die Oberfläche in einem nativen GTK/WebKit-Fenster an.
Fallback: Standardbrowser.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.request import urlopen

from . import APP_NAME, __version__, config, tls
from .netinfo import local_addresses, tailscale_dns_name
from .server import Server, test_remote


class DesktopSettings:
    """Einstellungen, die über die Oberfläche geändert werden können."""

    def __init__(self, path, cfg):
        self.path = path
        self.cfg = cfg
        for k in ("tls_cert", "tls_key"):
            if not cfg.get(k):
                cfg[k] = os.path.join(os.path.dirname(os.path.abspath(path)), "tls", os.path.basename(
                    config.DESKTOP_DEFAULTS[k]))
        self.server = None
        self._lock = threading.Lock()

    def public(self):
        port = self.server.port if self.server else self.cfg["port"]
        return {
            "mode": self.cfg.get("mode", "local"),
            "remote_url": self.cfg.get("remote_url", ""),
            "remote_token_set": bool(self.cfg.get("remote_token")),
            "local_token": self.cfg["token"],
            "port": port,
            "db_path": self.cfg["db_path"],
            "addresses": local_addresses(),
            "tailscale_name": tailscale_dns_name(),
            "config_path": self.path,
            "version": __version__,
            "tls": bool(self.cfg.get("tls")),
            "tls_active": bool(self.server and self.server.ctx.tls_fingerprint),
            "tls_fingerprint": self._fingerprint(),
            "remote_fingerprint": self.cfg.get("remote_fingerprint") or "",
            "restart_required": bool(self.server) and bool(self.cfg.get("tls")) != bool(
                self.server.ctx.tls_fingerprint),
        }

    def _fingerprint(self):
        if self.server and self.server.ctx.tls_fingerprint:
            return self.server.ctx.tls_fingerprint
        if self.cfg.get("tls") and os.path.exists(self.cfg.get("tls_cert", "")):
            try:
                return tls.fingerprint_file(self.cfg["tls_cert"])
            except (OSError, ValueError):
                return None
        return None

    def update(self, data):
        with self._lock:
            if "mode" in data:
                if data["mode"] not in ("local", "remote"):
                    return {"ok": False, "error": "Ungültiger Modus"}
                if data["mode"] == "remote":
                    url = data.get("remote_url", self.cfg.get("remote_url", ""))
                    token = data.get("remote_token") or self.cfg.get("remote_token", "")
                    fp = data.get("remote_fingerprint")
                    if fp is None and url.rstrip("/") == self.cfg.get("remote_url", "").rstrip("/"):
                        fp = self.cfg.get("remote_fingerprint") or None
                    res = test_remote(url, token, fp or None)
                    if not res["ok"]:
                        return res
                    self.cfg["remote_url"] = res["url"]
                    self.cfg["remote_token"] = token
                    self.cfg["remote_fingerprint"] = fp or ""
                self.cfg["mode"] = data["mode"]
            if "tls" in data:
                if data["tls"]:
                    from .netinfo import local_addresses as _addrs
                    names = [a["address"] for a in _addrs()] + [tailscale_dns_name()]
                    try:
                        tls.ensure_self_signed(self.cfg["tls_cert"], self.cfg["tls_key"], names)
                    except tls.TlsError as e:
                        return {"ok": False, "error": str(e)}
                self.cfg["tls"] = bool(data["tls"])
            if data.get("regenerate_token"):
                self.cfg["token"] = config.generate_token()
                if self.server:
                    self.server.ctx.token = self.cfg["token"]
            config.save(self.path, self.cfg)
            return {"ok": True, **self.public()}


RUNFILE = os.path.join(config.DESKTOP_DATA_DIR, "running-ui-port")


def _already_running():
    """Lokaler UI-Port einer bereits laufenden Instanz (oder None)."""
    try:
        with open(RUNFILE, encoding="utf-8") as f:
            port = int(f.read().strip())
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
            if json.loads(r.read().decode()).get("app") == APP_NAME:
                return port
    except Exception:  # noqa: BLE001
        pass
    return None


def _open_external(uri):
    try:
        subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        webbrowser.open(uri)


def run_gtk_window(url, local_prefix):
    """Natives Fenster mit WebKitGTK. Gibt False zurück, wenn GTK/WebKit fehlt."""
    try:
        import gi
        for ver in ("4.1", "4.0"):
            try:
                gi.require_version("WebKit2", ver)
                break
            except ValueError:
                continue
        else:
            return False
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk, WebKit2
    except (ImportError, ValueError) as e:
        print(f"[desktop] GTK/WebKit nicht verfügbar ({e}) – nutze Browser", file=sys.stderr)
        return False

    win = Gtk.Window(title="MTG Cards")
    win.set_default_size(1320, 880)
    icon = "/usr/share/icons/hicolor/scalable/apps/mtg-cards.svg"
    if os.path.exists(icon):
        try:
            win.set_icon_from_file(icon)
        except Exception:  # noqa: BLE001
            pass
    view = WebKit2.WebView()
    settings = view.get_settings()
    settings.set_property("enable-developer-extras", True)
    settings.set_property("javascript-can-access-clipboard", True)

    def on_policy(_view, decision, decision_type):
        types = WebKit2.PolicyDecisionType
        if decision_type in (types.NAVIGATION_ACTION, types.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            is_local = uri.startswith(local_prefix)
            if not is_local and not uri.startswith(("about:", "blob:", "data:")):
                _open_external(uri)          # z.B. Scryfall-Links im Browser öffnen
                decision.ignore()
                return True
            if decision_type == types.NEW_WINDOW_ACTION:
                view.load_uri(uri)
                decision.ignore()
                return True
        elif decision_type == types.RESPONSE:
            headers = decision.get_response().get_http_headers()
            disposition = headers.get_one("Content-Disposition") if headers else None
            if (disposition and "attachment" in disposition) or not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def on_download(_ctx, download):
        def decide(dl, suggested):
            dialog = Gtk.FileChooserDialog(title="Export speichern", parent=win,
                                           action=Gtk.FileChooserAction.SAVE)
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                               Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT)
            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name(suggested or "mtg-cards-export.json")
            dialog.set_current_folder(os.path.expanduser("~"))
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                dl.set_destination(GLib.filename_to_uri(dialog.get_filename(), None))
            else:
                dl.cancel()
            dialog.destroy()
            return True
        download.connect("decide-destination", decide)

    view.connect("decide-policy", on_policy)
    view.get_context().connect("download-started", on_download)
    view.load_uri(url)
    scroller = Gtk.ScrolledWindow()
    scroller.add(view)
    win.add(scroller)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return True


def main(argv=None):
    p = argparse.ArgumentParser(prog="mtg-cards", description="MTG Cards Desktop")
    p.add_argument("--config", default=config.DESKTOP_CONFIG_PATH)
    p.add_argument("--port", type=int, help="Port des eingebetteten Servers")
    p.add_argument("--browser", action="store_true", help="Im Standardbrowser statt eigenem Fenster öffnen")
    p.add_argument("--server-only", action="store_true", help="Nur Server starten (kein Fenster)")
    p.add_argument("--local", action="store_true", help="Lokale Datenbank verwenden (Modus dauerhaft setzen)")
    p.add_argument("--remote", metavar="URL", help="Mit Headless-Server verbinden (Modus dauerhaft setzen)")
    p.add_argument("--remote-token", metavar="TOKEN", help="Token des Headless-Servers")
    p.add_argument("--remote-fingerprint", metavar="FP", help="Zertifikats-Fingerabdruck des Servers (HTTPS)")
    p.add_argument("--show-token", action="store_true", help="Token für die Handy-App anzeigen")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    cfg = config.load(args.config, config.DESKTOP_DEFAULTS)
    if args.show_token:
        print(cfg["token"])
        return 0
    if args.local:
        cfg["mode"] = "local"
        config.save(args.config, cfg)
    if args.remote:
        res = test_remote(args.remote, args.remote_token or cfg.get("remote_token", ""), args.remote_fingerprint)
        if not res["ok"]:
            print(f"Fehler: {res['error']}", file=sys.stderr)
            if res.get("needs_trust"):
                print(f"Fingerabdruck des Servers: {res['fingerprint']}\n"
                      f"Mit 'sudo mtg-cards-server --show-fingerprint' vergleichen und mit "
                      f"--remote-fingerprint angeben.", file=sys.stderr)
            return 1
        cfg.update(mode="remote", remote_url=res["url"],
                   remote_token=args.remote_token or cfg.get("remote_token", ""),
                   remote_fingerprint=args.remote_fingerprint or "")
        config.save(args.config, cfg)
    port = args.port or int(cfg["port"])

    server = None
    running = _already_running()
    if running:
        print(f"[desktop] MTG Cards läuft bereits – öffne Fenster.")
        ui_port = running
    else:
        settings = DesktopSettings(args.config, cfg)
        use_tls = bool(cfg.get("tls"))
        if use_tls:
            try:
                tls.ensure_self_signed(cfg["tls_cert"], cfg["tls_key"])
            except tls.TlsError as e:
                print(f"[desktop] {e} – starte ohne HTTPS", file=sys.stderr)
                use_tls = False
        try:
            server = Server(cfg["db_path"], cfg["token"], bind=cfg.get("bind", "0.0.0.0"), port=port,
                            kind="desktop", discovery=cfg.get("discovery", True), desktop=settings,
                            tls_cert=cfg["tls_cert"] if use_tls else None,
                            tls_key=cfg["tls_key"] if use_tls else None, local_http=use_tls,
                            auto_refresh_hours=float(cfg.get("auto_refresh_hours", 24)))
        except OSError as e:
            print(f"[desktop] Port {port} belegt ({e}). Läuft bereits ein MTG-Cards-Server? "
                  f"Anderen Port mit --port wählen.", file=sys.stderr)
            return 1
        settings.server = server
        server.start()
        port = server.port
        ui_port = server.local_port or port
        try:
            os.makedirs(os.path.dirname(RUNFILE), exist_ok=True)
            with open(RUNFILE, "w", encoding="utf-8") as f:
                f.write(str(ui_port))
        except OSError:
            pass
        print(f"[desktop] Server läuft auf {server.scheme}://0.0.0.0:{port} (Modus: {cfg['mode']})")
        if server.ctx.tls_fingerprint:
            print(f"[desktop] Zertifikats-Fingerabdruck: {server.ctx.tls_fingerprint}")

    local_prefix = f"http://127.0.0.1:{ui_port}"
    url = f"{local_prefix}/#token={cfg['token']}"

    try:
        if args.server_only:
            print(f"Token für die App: {cfg['token']}")
            while True:
                time.sleep(3600)
        elif args.browser or not run_gtk_window(url, local_prefix):
            webbrowser.open(url)
            if server:
                print("Server läuft. Beenden mit Strg+C.")
                while True:
                    time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.stop()
            try:
                os.remove(RUNFILE)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
