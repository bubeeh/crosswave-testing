"""CLI del player cross-source.

Comandi:
  player-app serve [--host H] [--port P] [--db PATH] [--downloads DIR]
  player-app resolve URL        → risolve e stampa il Media Object
  player-app download URL       → accoda un download (se la licenza lo consente)
  player-app home               → raccomandazioni precomputate
  player-app compliance-export  → export log conformità (JSON)
  player-app resolve-worker     → avvia il worker resolver come processo separato
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.schema import MediaObject
from .storage.db import init_db
from .storage.repos import ComplianceRepo, DownloadsRepo, HistoryRepo, LibraryRepo, SettingsRepo

DEFAULT_DB = "player_data/player.db"
DEFAULT_DOWNLOADS = "player_data/downloads"


def _db_path(arg: str | None) -> Path:
    return Path(arg) if arg else Path(DEFAULT_DB)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.server import create_app

    app = create_app(db_path=_db_path(args.db), downloads_dir=Path(args.downloads or DEFAULT_DOWNLOADS))
    print(f"Player Cross-Source su http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    from .resolver.service import ResolverService

    svc = ResolverService(db_path=str(_db_path(args.db)))
    try:
        media = svc.resolve(args.url)
    finally:
        svc.shutdown()
    print(media.model_dump_json(indent=2))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    from .api.server import Services

    svc = Services(_db_path(args.db), Path(args.downloads or DEFAULT_DOWNLOADS))
    try:
        media = svc.resolver.resolve(args.url)
        svc.cache.set(media)
        progress = svc.download_worker.enqueue(media, priority=args.priority)
        print(json.dumps(progress.to_dict(), indent=2))
        if progress.status == "blocked":
            print(f"[BLOCKED] {progress.error}", file=sys.stderr)
            return 3
    finally:
        svc.close()
    return 0


def cmd_home(args: argparse.Namespace) -> int:
    conn = init_db(_db_path(args.db))
    from .recommend.worker import RecommendationEngine

    engine = RecommendationEngine(conn)
    for item in engine.home(limit=args.limit):
        print(f"#{item['rank']:2d} [{item['score']:6.2f}] {item['title']} "
              f"({item['platform']}) perché: {', '.join(item['reason_tags'])}")
    conn.close()
    return 0


def cmd_compliance_export(args: argparse.Namespace) -> int:
    conn = init_db(_db_path(args.db))
    entries = ComplianceRepo(conn).export()
    print(json.dumps(entries, indent=2, ensure_ascii=False))
    conn.close()
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from .resolver.worker import _main as worker_main

    return worker_main()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="player-app", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="avvia il server API + frontend")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--db", default=None)
    p_serve.add_argument("--downloads", default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_res = sub.add_parser("resolve", help="risolvi un URL")
    p_res.add_argument("url")
    p_res.add_argument("--db", default=None)
    p_res.set_defaults(func=cmd_resolve)

    p_dl = sub.add_parser("download", help="accoda un download")
    p_dl.add_argument("url")
    p_dl.add_argument("--db", default=None)
    p_dl.add_argument("--downloads", default=None)
    p_dl.add_argument("--priority", type=int, default=5)
    p_dl.set_defaults(func=cmd_download)

    p_home = sub.add_parser("home", help="raccomandazioni precomputate")
    p_home.add_argument("--db", default=None)
    p_home.add_argument("--limit", type=int, default=10)
    p_home.set_defaults(func=cmd_home)

    p_exp = sub.add_parser("compliance-export", help="export log conformità")
    p_exp.add_argument("--db", default=None)
    p_exp.set_defaults(func=cmd_compliance_export)

    p_wk = sub.add_parser("resolve-worker", help="processo resolver (uso interno)")
    p_wk.set_defaults(func=cmd_worker)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
