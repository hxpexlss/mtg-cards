"""Headless-Server: `mtg-cards-server`."""

import argparse
import os
import signal
import sys

from . import __version__, config
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

    if args.export or args.import_file:
        return offline_io(args, args.db or cfg["db_path"])

    bind = args.bind or cfg["bind"]
    port = args.port or int(cfg["port"])
    db_path = args.db or cfg["db_path"]
    srv = Server(db_path, cfg["token"], bind=bind, port=port, kind="server",
                 discovery=cfg.get("discovery", True) and not args.no_discovery)

    def _stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    print(f"MTG Cards Server {__version__} läuft auf http://{bind}:{srv.port}", flush=True)
    print(f"Datenbank: {db_path}", flush=True)
    print(f"Token anzeigen: mtg-cards-server --show-token (Config: {args.config})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


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
