"""Data access layer su SQLite (repository pattern).

Ogni repo incapsula le query della propria tabella; la logica di dominio
(risoluzione, raccomandazioni, download) sta nei moduli dedicati.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ..core.events import ComplianceEvent, DownloadProgress
from ..core.schema import MediaObject
from .db import RETENTION_COMPLIANCE_DAYS, RETENTION_HISTORY_DAYS, dumps, loads, transaction


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

    def record_play(self, media: MediaObject, play_seconds: float, watched_at: str | None = None) -> None:
        """Retrocompatibile: registra un evento 'play'."""
        self.record_event(media, play_seconds, event_type="play", completion=0.0, watched_at=watched_at)

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

    def aggregates(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT media_id, platform, play_count, total_seconds, last_played, tags, source_url, "
            "uploader, title, thumbnail FROM history_aggregates ORDER BY last_played DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) | {"tags": loads(r["tags"], [])} for r in rows]

    def prune(self, days: int = RETENTION_HISTORY_DAYS, now: datetime | None = None) -> int:
        """Pruning cronologia aggregata oltre 6 mesi (ritenzione differenziata)."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat()
        with transaction(self._conn):
            cur = self._conn.execute("DELETE FROM history_aggregates WHERE last_played < ?", (cutoff,))
            self._conn.execute("DELETE FROM history_events WHERE watched_at < ?", (cutoff,))
            return cur.rowcount

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

    def set_tags(self, artist_id: int, tags: list[tuple[str, float]], source: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM artist_tags WHERE artist_id=? AND source=?", (artist_id, source)
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO artist_tags(artist_id, tag, weight, source) VALUES(?,?,?,?)",
                [(artist_id, str(tag), float(weight), source) for tag, weight in tags],
            )

    def get_tags(self, artist_id: int, source: str | None = None) -> list[dict[str, Any]]:
        if source:
            rows = self._conn.execute(
                "SELECT tag, weight, source FROM artist_tags WHERE artist_id=? AND source=? "
                "ORDER BY weight DESC", (artist_id, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT tag, weight, source FROM artist_tags WHERE artist_id=? ORDER BY weight DESC",
                (artist_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_similarity(self, artist_id: int, similar_name_norm: str, score: float,
                       source: str, reason: str = "", similar_artist_id: int | None = None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO artist_similarity(artist_id, similar_name_norm, "
                "similar_artist_id, score, source, reason, fetched_at) VALUES(?,?,?,?,?,?,?)",
                (artist_id, similar_name_norm, similar_artist_id, float(score), source, reason, _now()),
            )

    def get_similarity(self, artist_id: int, source: str | None = None) -> list[dict[str, Any]]:
        if source:
            rows = self._conn.execute(
                "SELECT similar_name_norm, similar_artist_id, score, source, reason, fetched_at "
                "FROM artist_similarity WHERE artist_id=? AND source=? ORDER BY score DESC",
                (artist_id, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT similar_name_norm, similar_artist_id, score, source, reason, fetched_at "
                "FROM artist_similarity WHERE artist_id=? ORDER BY score DESC",
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


class ComplianceRepo:
    """Log di conformità 24 mesi: esportabile, non prunabile dalla UI."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def log(self, event: ComplianceEvent) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO compliance_log(event_type, source_url, platform, license, detail, ts) "
                "VALUES(?,?,?,?,?,?)",
                (
                    event.event_type,
                    event.source_url,
                    event.platform,
                    event.license,
                    event.detail,
                    event.ts,
                ),
            )

    def log_simple(self, event_type: str, source_url: str, platform: str = "",
                   license: str = "", detail: str = "") -> None:
        self.log(ComplianceEvent(event_type, source_url, platform, license, detail))

    def export(self, since: str | None = None) -> list[dict[str, Any]]:
        """Export completo (24 mesi) per audit. JSON esportabile."""
        if since:
            rows = self._conn.execute(
                "SELECT event_type, source_url, platform, license, detail, ts "
                "FROM compliance_log WHERE ts >= ? ORDER BY id",
                (since,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT event_type, source_url, platform, license, detail, ts "
                "FROM compliance_log ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM compliance_log").fetchone()
        return int(row["n"])

    def prune(self, days: int = RETENTION_COMPLIANCE_DAYS, now: datetime | None = None) -> int:
        """Pruning automatico oltre 24 mesi (mai chiamato dalla UI)."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat()
        with transaction(self._conn):
            cur = self._conn.execute("DELETE FROM compliance_log WHERE ts < ?", (cutoff,))
            return cur.rowcount


class LibraryRepo:
    """Preferiti, playlist, coda condivisa."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Preferiti ---
    def add_favorite(self, media: MediaObject) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR IGNORE INTO favorites(media_id, media_json, added_at) VALUES(?,?,?)",
                (media.canonical_id, dumps(media.model_dump(mode="json")), _now()),
            )

    def remove_favorite(self, media_id: str) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM favorites WHERE media_id=?", (media_id,))

    def is_favorite(self, media_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM favorites WHERE media_id=?", (media_id,)).fetchone()
        return row is not None

    def list_favorites(self) -> list[MediaObject]:
        rows = self._conn.execute(
            "SELECT media_json FROM favorites ORDER BY added_at DESC"
        ).fetchall()
        return [MediaObject.model_validate(loads(r["media_json"])) for r in rows]

    # --- Watch Later (Guarda dopo) ---
    def add_watch_later(self, media: MediaObject) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR IGNORE INTO watch_later(media_id, media_json, added_at) VALUES(?,?,?)",
                (media.canonical_id, dumps(media.model_dump(mode="json")), _now()),
            )

    def remove_watch_later(self, media_id: str) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM watch_later WHERE media_id=?", (media_id,))

    def is_watch_later(self, media_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM watch_later WHERE media_id=?", (media_id,)).fetchone()
        return row is not None

    def list_watch_later(self) -> list[MediaObject]:
        rows = self._conn.execute(
            "SELECT media_json FROM watch_later ORDER BY added_at DESC"
        ).fetchall()
        return [MediaObject.model_validate(loads(r["media_json"])) for r in rows]

    # --- Playlist ---
    def create_playlist(self, name: str) -> int:
        with transaction(self._conn):
            cur = self._conn.execute(
                "INSERT INTO playlists(name, created_at) VALUES(?,?)", (name, _now())
            )
            return int(cur.lastrowid)

    def list_playlists(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT p.id, p.name, p.created_at, "
            "(SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id=p.id) AS item_count "
            "FROM playlists p ORDER BY p.created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_playlist(self, playlist_id: int) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))

    def add_to_playlist(self, playlist_id: int, media: MediaObject) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position),0)+1 AS pos FROM playlist_items WHERE playlist_id=?",
            (playlist_id,),
        ).fetchone()
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR IGNORE INTO playlist_items(playlist_id, media_id, media_json, position) "
                "VALUES(?,?,?,?)",
                (playlist_id, media.canonical_id, dumps(media.model_dump(mode="json")), row["pos"]),
            )

    def list_playlist_items(self, playlist_id: int) -> list[MediaObject]:
        rows = self._conn.execute(
            "SELECT media_json FROM playlist_items WHERE playlist_id=? ORDER BY position",
            (playlist_id,),
        ).fetchall()
        return [MediaObject.model_validate(loads(r["media_json"])) for r in rows]

    # --- Coda condivisa ---
    def replace_queue(self, items: Iterable[MediaObject], current: str = "") -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM queue")
            for pos, media in enumerate(items):
                self._conn.execute(
                    "INSERT INTO queue(position, media_id, media_json, is_current) VALUES(?,?,?,?)",
                    (pos, media.canonical_id, dumps(media.model_dump(mode="json")),
                     1 if media.canonical_id == current else 0),
                )

    def get_queue(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT position, media_id, media_json, is_current FROM queue ORDER BY position"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["media"] = MediaObject.model_validate(loads(r["media_json"]))
            out.append(item)
        return out

    def set_current(self, media_id: str) -> None:
        with transaction(self._conn):
            self._conn.execute("UPDATE queue SET is_current=0")
            self._conn.execute("UPDATE queue SET is_current=1 WHERE media_id=?", (media_id,))


class SettingsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, value)
            )


class DownloadsRepo:
    """Persistenza dei download; lo stato di avanzamento è in memoria + DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, media: MediaObject, priority: int = 5) -> int:
        with transaction(self._conn):
            cur = self._conn.execute(
                "INSERT INTO downloads(media_id, media_json, status, priority, created_at) "
                "VALUES(?,?,?,?,?)",
                (media.canonical_id, dumps(media.model_dump(mode="json")), "queued", priority, _now()),
            )
            return int(cur.lastrowid)

    def update(self, progress: DownloadProgress) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE downloads SET status=?, percent=?, path=?, watermark=?, error=?, "
                "finished_at=COALESCE(finished_at, ?) WHERE id=?",
                (
                    progress.status,
                    progress.percent,
                    progress.path,
                    progress.watermark,
                    progress.error,
                    progress.ts if progress.status in ("done", "failed", "blocked") else None,
                    progress.download_id,
                ),
            )

    def get(self, download_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM downloads WHERE id=?", (download_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_all(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM downloads"
        args: list[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY id DESC"
        rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["media"] = MediaObject.model_validate(loads(r["media_json"]))
            out.append(item)
        return out

    def next_queued(self) -> dict[str, Any] | None:
        """Prossimo download in coda, ordinato per priorità (anti-starvation
        round-robin semplice: FIFO a parità di priorità)."""
        row = self._conn.execute(
            "SELECT * FROM downloads WHERE status='queued' "
            "ORDER BY priority DESC, id ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def pending_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM downloads WHERE status IN ('queued','running')"
        ).fetchone()
        return int(row["n"])
