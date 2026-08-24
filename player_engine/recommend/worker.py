"""Raccomandazioni precomputate (riserve Elena Rossi + Lucas Meyer).

Il RecommendationWorker aggiorna un vettore pesato di tag in SQLite. La home
legge SOLO la tabella `recommendations`, mai la cronologia grezza.

Score(media) = Σ_tag weight(tag) dove
  weight(tag) = Σ_play log1p(seconds/60) · (1 + 0.1·play_count) · exp(−age_days/30)

Decadimento esponenziale: ciò che hai ascoltato di recente pesa di più,
senza conservare la cronologia grezza lato UI (cifrata lato client).
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..core.errors import RecommendationError
from ..core.schema import MediaObject
from ..storage.db import dumps, loads, transaction
from ..storage.repos import HistoryRepo

TOP_N = 20
HALF_LIFE_DAYS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecommendationEngine:
    """Calcola e persiste il vettore pesato di tag; la home lo legge."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._history = HistoryRepo(conn)

    # ------------------------------------------------------------------
    def record_play(self, media: MediaObject, play_seconds: float) -> None:
        """Registra un ascolto/visione e aggiorna le raccomandazioni."""
        self._history.record_play(media, play_seconds)
        self.recompute()

    def recompute(self, limit: int = TOP_N) -> int:
        """Ricalcola la tabella recommendations dallo stato aggregato."""
        now = _now()
        aggregates = self._history.aggregates(limit=500)
        if not aggregates:
            with transaction(self._conn):
                self._conn.execute("DELETE FROM recommendations")
            return 0

        # 1) vettore pesato dei tag + peso proprio di ogni media
        tag_weight: dict[str, float] = {}
        own_weight: dict[str, float] = {}
        for agg in aggregates:
            last = datetime.fromisoformat(agg["last_played"])
            age_days = max(0.0, (now - last).total_seconds() / 86400.0)
            decay = math.exp(-age_days / HALF_LIFE_DAYS)
            base = math.log1p((agg["total_seconds"] or 0) / 60.0)
            own = base * (1 + 0.1 * agg["play_count"]) * decay
            own_weight[agg["media_id"]] = own
            for tag in agg.get("tags", []):
                tag_weight[tag] = tag_weight.get(tag, 0.0) + own

        # 2) score per media = peso proprio (recency) + affinità tag
        scored: list[tuple[float, dict[str, Any], list[str]]] = []
        for agg in aggregates:
            tags = agg.get("tags", [])
            own = own_weight.get(agg["media_id"], 0.0)
            affinity = sum(tag_weight.get(t, 0.0) for t in tags)
            score = own + affinity
            if score <= 0:
                continue
            # Motivo leggibile: i 2 tag con peso maggiore
            reasons = sorted(tags, key=lambda t: tag_weight.get(t, 0.0), reverse=True)[:2]
            scored.append((score, agg, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        computed_at = now.isoformat()
        with transaction(self._conn):
            self._conn.execute("DELETE FROM recommendations")
            for rank, (score, agg, reasons) in enumerate(scored, start=1):
                self._conn.execute(
                    "INSERT INTO recommendations(rank, media_id, score, platform, title, "
                    "thumbnail, duration, reason_tags, source_url, computed_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        rank,
                        agg["media_id"],
                        round(score, 4),
                        agg["platform"],
                        self._title_for(agg["media_id"], agg["platform"]),
                        self._thumb_for(agg["media_id"]),
                        agg["total_seconds"],
                        dumps(reasons),
                        agg.get("source_url", ""),
                        computed_at,
                    ),
                )
        return len(scored)

    def _title_for(self, media_id: str, platform: str) -> str:
        row = self._conn.execute(
            "SELECT media_json FROM favorites WHERE media_id=? "
            "UNION ALL SELECT media_json FROM playlist_items WHERE media_id=? LIMIT 1",
            (media_id, media_id),
        ).fetchone()
        if row:
            try:
                return MediaObject.model_validate(loads(row["media_json"])).title
            except Exception:
                pass
        return f"{platform} · {media_id[:12]}"

    def _thumb_for(self, media_id: str) -> str:
        row = self._conn.execute(
            "SELECT media_json FROM favorites WHERE media_id=? "
            "UNION ALL SELECT media_json FROM playlist_items WHERE media_id=? LIMIT 1",
            (media_id, media_id),
        ).fetchone()
        if row:
            try:
                return MediaObject.model_validate(loads(row["media_json"])).thumbnail
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------------
    def home(self, limit: int = TOP_N) -> list[dict[str, Any]]:
        """La home legge SOLO il risultato precomputato."""
        try:
            rows = self._conn.execute(
                "SELECT rank, media_id, score, platform, title, thumbnail, duration, "
                "reason_tags, source_url, computed_at FROM recommendations ORDER BY rank LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise RecommendationError(str(exc)) from exc
        out = []
        for r in rows:
            item = dict(r)
            item["reason_tags"] = loads(item["reason_tags"], [])
            out.append(item)
        return out
