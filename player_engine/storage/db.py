"""SQLite (WAL) + migrazioni — riserva Lucas Meyer.

Storage locale: metadati, cronologia aggregata, preferiti, playlist, coda,
download, rate limiting, cache risoluzioni e log di conformità 24 mesi.
WAL mode, scritture atomiche, migrazioni versionate idempotenti.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..core.errors import StorageError

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

# Retention policy (riserva Yuki Nakamura):
#  - cronologia aggregata: 6 mesi
#  - log conformità: 24 mesi (esportabile, non prunabile dalla UI)
RETENTION_HISTORY_DAYS = 180
RETENTION_COMPLIANCE_DAYS = 730


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Apre una connessione SQLite in WAL mode con le PRAGMA e le migrazioni applicate."""
    db_path = Path(db_path)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        try:
            migrate(conn)
        except Exception:
            pass
        return conn
    except sqlite3.Error as exc:  # pragma: no cover
        raise StorageError(f"apertura database fallita: {exc}") from exc


def migrate(conn: sqlite3.Connection) -> None:
    """Applica lo schema corrente in modo idempotente + micro-migrazioni."""
    try:
        conn.executescript(_SCHEMA)
        # Migrazioni incrementali per DB creati con una versione precedente
        for sql in (
            "ALTER TABLE history_aggregates ADD COLUMN source_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE recommendations ADD COLUMN source_url TEXT NOT NULL DEFAULT ''",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # colonna/tabella già presente
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(version, applied_at) "
            "VALUES(1, datetime('now'))"
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StorageError(f"migrazione fallita: {exc}") from exc


@contextmanager
def transaction(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Contesto transazionale: commit a fine blocco, rollback su errore."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Helper: connette e migra in un colpo solo."""
    conn = connect(db_path)
    migrate(conn)
    return conn


# --------------------------------------------------------------------------
# Serializzazione helper
# --------------------------------------------------------------------------
def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text: str | None, default: object = None) -> object:
    if not text:
        return default
    return json.loads(text)
