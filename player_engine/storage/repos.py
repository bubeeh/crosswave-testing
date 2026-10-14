"""Data access layer su SQLite (repository pattern).

Ogni repo incapsula le query della propria tabella; la logica di dominio
(risoluzione, raccomandazioni, download) sta nei moduli dedicati.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.schema import MediaObject
from .db import dumps, loads, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _media_to_row(media: MediaObject, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "media_id": media.canonical_id,
        "media_json": dumps(media.model_dump(mode="json")),
    }
    row.update(extra)
    return row


class CacheRepo:
    """Cache risoluzioni con TTL 72h (riserva Aiko: cold start zero-fetch)."""

    TTL_HOURS = 72

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, canonical_id: str, now: datetime | None = None) -> MediaObject | None:
        row = self._conn.execute(
            "SELECT media_json, resolved_at FROM media_cache WHERE canonical_id=?", (canonical_id,)
        ).fetchone()
        if not row or not row["resolved_at"]:
            return None
        resolved = datetime.fromisoformat(row["resolved_at"])
        now = now or datetime.now(timezone.utc)
        if now - resolved > timedelta(hours=self.TTL_HOURS):
            return None
        return MediaObject.model_validate(loads(row["media_json"]))

    def set(self, media: MediaObject) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO media_cache(canonical_id, media_json, resolved_at, platform) "
                "VALUES(?,?,?,?)",
                (media.canonical_id, dumps(media.model_dump(mode="json")), media.resolved_at, media.platform),
            )

    # --- tracklist di una raccolta (album) — chiave derivata "tracklist:<cid>" ---
    def get_tracklist(self, album_cid: str, now: datetime | None = None) -> list[dict[str, Any]] | None:
        row = self._conn.execute(
            "SELECT media_json, resolved_at FROM media_cache WHERE canonical_id=?",
            (f"tracklist:{album_cid}",),
        ).fetchone()
        if not row or not row["resolved_at"]:
            return None
        resolved = datetime.fromisoformat(row["resolved_at"])
        now = now or datetime.now(timezone.utc)
        if now - resolved > timedelta(hours=self.TTL_HOURS):
            return None
        return loads(row["media_json"])

    def set_tracklist(self, album_cid: str, tracks: list[dict[str, Any]], resolved_at: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO media_cache(canonical_id, media_json, resolved_at, platform) "
                "VALUES(?,?,?,?)",
                (f"tracklist:{album_cid}", dumps(tracks), resolved_at, "album"),
            )

    # --- alias URL→canonical_id (per le raccolte il cui id nativo di yt-dlp
    # non coincide con lo slug dell'URL: lookup in cache pre-yt-dlp) ---
    def get_alias(self, url: str) -> str | None:
        row = self._conn.execute(
            "SELECT media_json FROM media_cache WHERE canonical_id=?", (f"urleq:{url}",)
        ).fetchone()
        if not row:
            return None
        return row["media_json"]

    def set_alias(self, url: str, canonical_id: str, resolved_at: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO media_cache(canonical_id, media_json, resolved_at, platform) "
                "VALUES(?,?,?,?)",
                (f"urleq:{url}", canonical_id, resolved_at, "alias"),
            )

    def clear(self) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM media_cache")


class SearchCacheRepo:
    """Cache ricerche con TTL 30 min (le query cambiano: niente 72h)."""

    TTL_MINUTES = 30

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, query_key: str, now: datetime | None = None) -> list[dict[str, Any]] | None:
        row = self._conn.execute(
            "SELECT results_json, cached_at FROM search_cache WHERE query_key=?", (query_key,)
        ).fetchone()
        if not row:
            return None
        cached = datetime.fromisoformat(row["cached_at"])
        now = now or datetime.now(timezone.utc)
        if now - cached > timedelta(minutes=self.TTL_MINUTES):
            return None
        return loads(row["results_json"])

    def set(self, query_key: str, platform: str, results: list[dict[str, Any]]) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO search_cache(query_key, platform, results_json, cached_at) "
                "VALUES(?,?,?,?)",
                (query_key, platform, dumps(results), _now()),
            )


class RateLimitRepo:
    """Ultimo timestamp di richiesta per piattaforma (persistente)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def last_request(self, platform: str) -> float:
        row = self._conn.execute(
            "SELECT last_request_ts FROM rate_limits WHERE platform=?", (platform,)
        ).fetchone()
        return row["last_request_ts"] if row else 0.0

    def record(self, platform: str, ts: float) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO rate_limits(platform, last_request_ts) VALUES(?,?)",
                (platform, ts),
            )


class HistoryRepo:
    """Cronologia: eventi grezzi + aggregati (retention 6 mesi)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record_event(self, media: MediaObject, play_seconds: float, event_type: str = "play",
                     completion: float = 0.0, artist_id: int | None = None,
                     watched_at: str | None = None) -> None:
        """Registra un evento di ascolto esteso (play/complete/skip/replay/...)."""
        watched_at = watched_at or _now()
        tags_json = dumps(media.tags)
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO history_events(media_id, platform, tags, play_seconds, watched_at, "
                "artist_id, event_type, completion) VALUES(?,?,?,?,?,?,?,?)",
                (media.canonical_id, media.platform, tags_json, play_seconds, watched_at,
                 artist_id, event_type, float(completion or 0.0)),
            )
            row = self._conn.execute(
                "SELECT play_count, total_seconds FROM history_aggregates WHERE media_id=?",
                (media.canonical_id,),
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE history_aggregates SET play_count=play_count+1, "
                    "total_seconds=total_seconds+?, last_played=?, tags=?, source_url=?, uploader=?, "
                    "title=?, thumbnail=? WHERE media_id=?",
                    (play_seconds, watched_at, tags_json, media.source_url,
                     media.uploader, media.title, media.thumbnail, media.canonical_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO history_aggregates(media_id, platform, play_count, total_seconds, "
                    "last_played, tags, source_url, uploader, title, thumbnail) "
                    "VALUES(?,?,1,?,?,?,?,?,?,?)",
                    (media.canonical_id, media.platform, play_seconds, watched_at, tags_json,
                     media.source_url, media.uploader, media.title, media.thumbnail),
                )

    def recent_events(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Eventi di ascolto con l'artista collegato (per i seed delle reco v2)."""
        rows = self._conn.execute(
            "SELECT e.event_type, e.watched_at, e.play_seconds, e.completion, e.artist_id, "
            "a.name AS artist_name, a.name_norm AS artist_name_norm, a.mbid AS artist_mbid "
            "FROM history_events e LEFT JOIN artists a ON a.id = e.artist_id "
            "WHERE e.artist_id IS NOT NULL ORDER BY e.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def aggregates(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT media_id, platform, play_count, total_seconds, last_played, tags, source_url, "
            "uploader, title, thumbnail FROM history_aggregates ORDER BY last_played DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) | {"tags": loads(r["tags"], [])} for r in rows]

    def forget_all(self) -> None:
        """'Dimentica tutto' (fallback privacy in home)."""
        with transaction(self._conn):
            self._conn.execute("DELETE FROM history_events")
            self._conn.execute("DELETE FROM history_aggregates")
            self._conn.execute("DELETE FROM recommendations")


class ArtistRepo:
    """Identità artisti: anagrafica, alias e link piattaforma (sistema reco v2)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, artist_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        return dict(row) if row else None

    def get_by_norm(self, name_norm: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM artists WHERE name_norm=? ORDER BY id LIMIT 1", (name_norm,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_alias(self, alias_norm: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT a.* FROM artists a JOIN artist_aliases al ON al.artist_id=a.id "
            "WHERE al.alias_norm=? ORDER BY a.id LIMIT 1",
            (alias_norm,),
        ).fetchone()
        return dict(row) if row else None

    def get_by_mbid(self, mbid: str) -> dict[str, Any] | None:
        if not mbid:
            return None
        row = self._conn.execute("SELECT * FROM artists WHERE mbid=?", (mbid,)).fetchone()
        return dict(row) if row else None

    def resolve(self, name_norm: str) -> dict[str, Any] | None:
        """Trova per nome normalizzato, alias o (fallback) per nome grezzo."""
        return self.get_by_norm(name_norm) or self.get_by_alias(name_norm)

    def upsert(self, name: str, name_norm: str, mbid: str | None = None) -> int:
        existing = self.get_by_norm(name_norm)
        if not existing and mbid:
            existing = self.get_by_mbid(mbid)
        if not existing:
            existing = self.get_by_alias(name_norm)
        if existing:
            artist_id = int(existing["id"])
            if mbid and not existing.get("mbid"):
                self.set_mbid(artist_id, mbid, status="resolved")
            self.add_alias(artist_id, name_norm)
            return artist_id
        with transaction(self._conn):
            cur = self._conn.execute(
                "INSERT INTO artists(name, name_norm, mbid, resolve_status, created_at) "
                "VALUES(?,?,?,?,?)",
                (name, name_norm, mbid, "resolved" if mbid else "unresolved", _now()),
            )
            artist_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT OR IGNORE INTO artist_aliases(artist_id, alias_norm) VALUES(?,?)",
                (artist_id, name_norm),
            )
        return artist_id

    def add_alias(self, artist_id: int, alias_norm: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR IGNORE INTO artist_aliases(artist_id, alias_norm) VALUES(?,?)",
                (artist_id, alias_norm),
            )

    def set_mbid(self, artist_id: int, mbid: str, status: str = "resolved") -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE artists SET mbid=?, resolve_status=?, resolved_at=? WHERE id=?",
                (mbid, status, _now(), artist_id),
            )

    def link(self, artist_id: int, platform: str, url: str) -> None:
        if not platform or not url:
            return
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR IGNORE INTO artist_links(artist_id, platform, url) VALUES(?,?,?)",
                (artist_id, platform, url),
            )

    def list_links(self, artist_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT platform, url FROM artist_links WHERE artist_id=? ORDER BY platform",
            (artist_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class FeedbackRepo:
    """Feedback esplicito dell'utente sugli artisti (like/dislike/hide/seed)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, artist_name_norm: str, action: str, artist_id: int | None = None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO rec_feedback(artist_id, artist_name_norm, action, ts) VALUES(?,?,?,?)",
                (artist_id, artist_name_norm, action, _now()),
            )

    def latest_actions(self) -> dict[str, str]:
        """Ultima azione per artista (name_norm → action)."""
        rows = self._conn.execute(
            "SELECT artist_name_norm, action FROM rec_feedback f "
            "WHERE id = (SELECT MAX(id) FROM rec_feedback g "
            "            WHERE g.artist_name_norm = f.artist_name_norm)"
        ).fetchall()
        return {r["artist_name_norm"]: r["action"] for r in rows}

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, artist_id, artist_name_norm, action, ts FROM rec_feedback ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM rec_feedback")


class SourceCacheRepo:
    """Cache delle risposte delle fonti esterne di similarità (TTL lungo)."""

    def __init__(self, conn: sqlite3.Connection, ttl_days: float = 14.0) -> None:
        self._conn = conn
        self.ttl_days = ttl_days

    def get(self, source: str, cache_key: str, now: datetime | None = None) -> Any | None:
        row = self._conn.execute(
            "SELECT payload, fetched_at FROM source_cache WHERE source=? AND cache_key=?",
            (source, cache_key),
        ).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        now = now or datetime.now(timezone.utc)
        if now - fetched > timedelta(days=self.ttl_days):
            return None
        return loads(row["payload"])

    def set(self, source: str, cache_key: str, payload: Any) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO source_cache(source, cache_key, payload, fetched_at) "
                "VALUES(?,?,?,?)",
                (source, cache_key, dumps(payload), _now()),
            )
