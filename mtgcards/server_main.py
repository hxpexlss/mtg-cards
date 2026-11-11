"""Headless-Server: `mtg-cards-server`."""

import argparse
import os
import signal
import sys

from . import __version__, config, tls
from .server import Server


def main(argv=None):
    p = argparse.ArgumentParser(prog="mtg-cards-server", description="MTG Cards Headless-Server")
    p.add_argument("--config", default=os.environ.get("MTGCARDS_CONFIG", config.SERVER_CONFIG_PATH))
    p.add_argument("--bind", help="Adresse (Standard 0.0.0.0)")
    p.add_argument("--port", type=int)
    p.add_argument("--db", help="Pfad zur SQLite-Datenbank")
    p.add_argument("--no-discovery", action="store_true", help="UDP-Erkennung im LAN deaktivieren")
    p.add_argument("--show-token", action="store_true", help="Zugangs-Token anzeigen und beenden")
    p.add_argument("--new-token", action="store_true", help="Neuen Token erzeugen und beenden")
    p.add_argument("--enable-tls", action="store_true",
                   help="HTTPS aktivieren (erzeugt selbstsigniertes Zertifikat, oder --cert/--key angeben)")
    p.add_argument("--disable-tls", action="store_true", help="HTTPS deaktivieren")
    p.add_argument("--cert", help="Zertifikat (PEM), z.B. von 'tailscale cert'")
    p.add_argument("--key", help="Privater Schlüssel (PEM) zum Zertifikat")
    p.add_argument("--show-fingerprint", action="store_true", help="Zertifikats-Fingerabdruck anzeigen")
    p.add_argument("--export", metavar="DATEI", help="Sammlung exportieren (.json oder .csv; '-' = stdout)")
    p.add_argument("--import", dest="import_file", metavar="DATEI", help="Sammlung importieren (JSON/CSV)")
    p.add_argument("--replace", action="store_true", help="Beim Import Sammlung ersetzen statt ergänzen")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    try:
        cfg = config.load(args.config, config.SERVER_DEFAULTS)
    except PermissionError:
        print(f"Keine Berechtigung für {args.config} – bitte mit sudo ausführen.", file=sys.stderr)
        return 1
    if args.new_token:
        cfg["token"] = config.generate_token()
        config.save(args.config, cfg)
        print(cfg["token"])
        print("Hinweis: Dienst neu starten: sudo systemctl restart mtg-cards-server", file=sys.stderr)
        return 0
    if args.show_token:
        print(cfg["token"])
        return 0
    if args.enable_tls or args.disable_tls:
        return configure_tls(args, cfg)
    if args.show_fingerprint:
        if not cfg.get("tls"):
            print("HTTPS ist nicht aktiviert (mtg-cards-server --enable-tls)", file=sys.stderr)
            return 1
        print(tls.fingerprint_file(cfg["tls_cert"]))
        return 0

    if args.export or args.import_file:
        return offline_io(args, args.db or cfg["db_path"])

    bind = args.bind or cfg["bind"]
    port = args.port or int(cfg["port"])
    db_path = args.db or cfg["db_path"]
    use_tls = bool(cfg.get("tls"))
    srv = Server(db_path, cfg["token"], bind=bind, port=port, kind="server",
                 discovery=cfg.get("discovery", True) and not args.no_discovery,
                 tls_cert=cfg["tls_cert"] if use_tls else None, tls_key=cfg["tls_key"] if use_tls else None,
                 auto_refresh_hours=float(cfg.get("auto_refresh_hours", 24)))

    def _stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    print(f"MTG Cards Server {__version__} läuft auf {srv.scheme}://{bind}:{srv.port}", flush=True)
    if use_tls:
        print(f"Zertifikats-Fingerabdruck: {srv.ctx.tls_fingerprint}", flush=True)
    print(f"Datenbank: {db_path}", flush=True)
    print(f"Token anzeigen: mtg-cards-server --show-token (Config: {args.config})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def configure_tls(args, cfg):
    if args.disable_tls:
        cfg["tls"] = False
        config.save(args.config, cfg)
        print("HTTPS deaktiviert. Neustart: sudo systemctl restart mtg-cards-server")
        return 0
    if args.cert or args.key:
        if not (args.cert and args.key):
            print("--cert und --key bitte zusammen angeben", file=sys.stderr)
            return 1
        cfg["tls_cert"], cfg["tls_key"] = os.path.abspath(args.cert), os.path.abspath(args.key)
    else:
        from .netinfo import local_addresses, tailscale_dns_name
        names = [a["address"] for a in local_addresses()] + [tailscale_dns_name()]
        try:
            created = tls.ensure_self_signed(cfg["tls_cert"], cfg["tls_key"], names)
        except tls.TlsError as e:
            print(str(e), file=sys.stderr)
            return 1
        if created:
            _share_with_service(cfg["tls_cert"], cfg["tls_key"])
    tls.server_context(cfg["tls_cert"], cfg["tls_key"])  # prüft, ob Zertifikat + Schlüssel passen
    cfg["tls"] = True
    config.save(args.config, cfg)
    print("HTTPS aktiviert.")
    print(f"Fingerabdruck: {tls.fingerprint_file(cfg['tls_cert'])}")
    print("Neustart: sudo systemctl restart mtg-cards-server")
    print("In App und Desktop die Adresse mit https:// eintragen und den Fingerabdruck vergleichen.")
    return 0


def _share_with_service(cert, key):
    """Schlüssel für den Dienst-Benutzer lesbar machen (root:mtgcards 0640)."""
    try:
        import grp
        gid = grp.getgrnam("mtgcards").gr_gid
        for path in (os.path.dirname(key), key):
            os.chown(path, 0, gid)
        os.chmod(os.path.dirname(key), 0o750)
        os.chmod(key, 0o640)
    except (KeyError, PermissionError, OSError):
        pass


def offline_io(args, db_path):
    from .db import Database
    from .importexport import export_csv, export_json, import_cards
    from .scryfall import Scryfall
    from .server import cache_path_for

    db = Database(db_path)
    try:
        if args.export:
            data = export_csv(db) if args.export.endswith(".csv") else export_json(db)
            if args.export == "-":
                sys.stdout.write(data)
            else:
                with open(args.export, "w", encoding="utf-8") as f:
                    f.write(data)
                print(f"{len(db.all())} Einträge exportiert nach {args.export}", file=sys.stderr)
        if args.import_file:
            with open(args.import_file, encoding="utf-8-sig") as f:
                res = import_cards(db, Scryfall(cache_path=cache_path_for(db_path)), f.read(), mode="replace" if args.replace else "add")
            print(f"{res['imported']} Karten importiert ({res['created']} neu, {res['merged']} zusammengeführt)")
            for err in res["errors"]:
                print("  " + err, file=sys.stderr)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
