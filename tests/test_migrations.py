from __future__ import annotations

import sqlite3

from player_engine.storage.db import init_db

NEW_TABLES = {
    "artists", "artist_aliases", "artist_links",
    "artist_similarity", "artist_tags", "rec_feedback",
}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_migrate_idempotent(tmp_path):
    db = tmp_path / "new.db"
    init_db(str(db)).close()
    conn = init_db(str(db))  # seconda passata non deve fallire

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert NEW_TABLES <= tables
    assert {"artist_id", "event_type", "completion"} <= _columns(conn, "history_events")
    assert {"artist_id", "mode", "reasons", "source_breakdown"} <= _columns(conn, "recommendations")
    conn.close()


def test_migrate_upgrades_old_db(tmp_path):
    """DB con tabelle 'vecchie' senza le colonne v2: la migrazione le aggiunge."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE history_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          media_id TEXT NOT NULL,
          platform TEXT NOT NULL,
          tags TEXT NOT NULL DEFAULT '[]',
          play_seconds REAL NOT NULL DEFAULT 0,
          watched_at TEXT NOT NULL
        );
        CREATE TABLE recommendations (
          rank INTEGER PRIMARY KEY,
          media_id TEXT NOT NULL,
          score REAL NOT NULL,
          platform TEXT NOT NULL,
          title TEXT NOT NULL,
          thumbnail TEXT DEFAULT '',
          duration REAL DEFAULT 0,
          reason_tags TEXT NOT NULL DEFAULT '[]',
          computed_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    upgraded = init_db(str(db))
    assert {"artist_id", "event_type", "completion"} <= _columns(upgraded, "history_events")
    assert {"artist_id", "mode", "reasons", "source_breakdown", "uploader"} <= _columns(upgraded, "recommendations")
    upgraded.close()
