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
from ..storage.repos import ArtistRepo, FeedbackRepo, HistoryRepo
from . import config, scoring
from .identity import ArtistRef

TOP_N = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecommendationEngine:
    """Calcola e persiste il vettore pesato di tag; la home lo legge."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._history = HistoryRepo(conn)

    # ------------------------------------------------------------------
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
            decay = math.exp(-age_days / config.HALF_LIFE_DAYS)
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
                title = agg.get("title")
                thumbnail = agg.get("thumbnail")
                if not title or not thumbnail:
                    stored = self._stored_media(agg["media_id"])
                    if stored is not None:
                        title = title or stored.title
                        thumbnail = thumbnail or stored.thumbnail
                self._conn.execute(
                    "INSERT INTO recommendations(rank, media_id, score, platform, title, "
                    "thumbnail, duration, reason_tags, source_url, uploader, computed_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        rank,
                        agg["media_id"],
                        round(score, 4),
                        agg["platform"],
                        title or f"{agg['platform']} · {agg['media_id'][:12]}",
                        thumbnail or "",
                        agg["total_seconds"],
                        dumps(reasons),
                        agg.get("source_url", ""),
                        agg.get("uploader", ""),
                        computed_at,
                    ),
                )
        return len(scored)

    def _stored_media(self, media_id: str) -> MediaObject | None:
        """MediaObject salvato (preferiti/playlist), per titolo/thumbnail di riserva."""
        row = self._conn.execute(
            "SELECT media_json FROM favorites WHERE media_id=? "
            "UNION ALL SELECT media_json FROM playlist_items WHERE media_id=? LIMIT 1",
            (media_id, media_id),
        ).fetchone()
        if not row:
            return None
        try:
            return MediaObject.model_validate(loads(row["media_json"]))
        except Exception:
            return None

    # ------------------------------------------------------------------
    def home(self, limit: int = TOP_N) -> list[dict[str, Any]]:
        """La home legge SOLO il risultato precomputato."""
        try:
            rows = self._conn.execute(
                "SELECT rank, media_id, score, platform, title, thumbnail, duration, "
                "reason_tags, source_url, uploader, computed_at "
                "FROM recommendations ORDER BY rank LIMIT ?",
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

    # ------------------------------------------------------------------
    # Sistema v2: raccomandazione per ARTISTI (close/scene/mixed)
    # ------------------------------------------------------------------
    def recommend(self, mode: str = config.DEFAULT_MODE, explore: float | None = None,
                  limit: int = 30, sources: list | None = None,
                  per_seed_limit: int = 20) -> list[dict[str, Any]]:
        """Pipeline: seed → candidati per fonte → RRF → filtri → diversificazione.

        Le fonti sono iniettate (lista di `RecSource`): degradano silenziosamente
        se disabilitate o in errore. Ritorna artisti con motivi e (quando noto)
        un `playable` ripreso dai link già associati all'artista.
        """
        if mode not in config.MODES:
            mode = config.DEFAULT_MODE
        source_weights = config.SOURCE_WEIGHTS.get(mode, config.SOURCE_WEIGHTS[config.DEFAULT_MODE])

        feedback = FeedbackRepo(self._conn).latest_actions()
        seeds = scoring.compute_seed_weights(self._history.recent_events(2000), feedback)
        if not seeds:
            return []

        excluded = {n for n, a in feedback.items() if a in ("dislike", "hide")}
        seed_norms = {s["name_norm"] for s in seeds}
        max_weight = max((s["weight"] for s in seeds), default=0.0) or 1.0
        seed_weight_norm = {s["name_norm"]: s["weight"] / max_weight for s in seeds}

        grouped: dict[str, dict[str, list]] = {}
        for seed_index, seed in enumerate(seeds):
            ref = ArtistRef(name=seed["name"], name_norm=seed["name_norm"], mbid=seed.get("mbid"))
            per_source: dict[str, list] = {}
            for src in sources or []:
                cap = getattr(src, "max_seeds", None)
                if cap is not None and seed_index >= cap:
                    continue  # fonte costosa: solo i primi seed
                try:
                    if not src.enabled():
                        continue
                    cands = src.similar(ref, per_seed_limit)
                except Exception:
                    continue  # degrado silenzioso
                if cands:
                    per_source[src.name] = cands
            if per_source:
                grouped[seed["name_norm"]] = per_source

        ranked = scoring.fuse(grouped, source_weights, seed_weight_norm)
        ranked = [r for r in ranked if r["name_norm"] not in excluded and r["name_norm"] not in seed_norms]
        final = scoring.diversify(ranked, limit, explore=explore)

        artist_repo = ArtistRepo(self._conn)
        out: list[dict[str, Any]] = []
        for item in final:
            seen_reasons: set[str] = set()
            reasons = []
            for reason in item["reasons"]:
                if reason["text"] in seen_reasons:
                    continue
                seen_reasons.add(reason["text"])
                reasons.append(reason)
            playable = None
            stored = artist_repo.get_by_norm(item["name_norm"])
            if stored:
                links = artist_repo.list_links(stored["id"])
                if links:
                    playable = {"platform": links[0]["platform"], "url": links[0]["url"]}
                if not item.get("mbid") and stored.get("mbid"):
                    item["mbid"] = stored["mbid"]
            out.append({
                "name": item["name"],
                "name_norm": item["name_norm"],
                "mbid": item.get("mbid"),
                "score": round(float(item["score"]), 6),
                "mode": mode,
                "sources": [{"source": s, "score": round(v, 6)} for s, v in
                            sorted(item["sources"].items(), key=lambda kv: kv[1], reverse=True)],
                "reasons": reasons[:3],
                "playable": playable,
            })
        return out
