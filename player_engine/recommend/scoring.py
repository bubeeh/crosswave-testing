"""Scoring del sistema di raccomandazione v2: seed, RRF, diversificazione.

Modulo puro (nessuna I/O): testabile con dati in memoria.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import config
from .sources.base import Candidate


def _decay(age_days: float) -> float:
    return 0.5 ** (max(0.0, age_days) / config.HALF_LIFE_DAYS)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def compute_seed_weights(events: list[dict[str, Any]], feedback_actions: dict[str, str],
                         now: datetime | None = None) -> list[dict[str, Any]]:
    """Pesi dei seed per artista: somma eventi × decadimento + feedback.

    Ritorna i top `SEED_TOP_N` con peso > `SEED_MIN_WEIGHT`, ordinati desc.
    """
    now = now or datetime.now(timezone.utc)
    seeds: dict[str, dict[str, Any]] = {}

    for ev in events or []:
        norm = ev.get("artist_name_norm")
        if not norm:
            continue
        entry = seeds.setdefault(norm, {
            "name": ev.get("artist_name") or norm,
            "name_norm": norm,
            "weight": 0.0,
            "mbid": ev.get("artist_mbid"),
        })
        if not entry.get("mbid") and ev.get("artist_mbid"):
            entry["mbid"] = ev["artist_mbid"]
        weight = config.EVENT_WEIGHTS.get(ev.get("event_type") or "play", 0.0)
        ts = _parse_ts(ev.get("watched_at"))
        age = 0.0 if ts is None else max(0.0, (now - ts).total_seconds() / 86400.0)
        entry["weight"] += weight * _decay(age)

    for norm, action in (feedback_actions or {}).items():
        if action not in config.EVENT_WEIGHTS:
            continue
        entry = seeds.setdefault(norm, {"name": norm, "name_norm": norm, "weight": 0.0, "mbid": None})
        entry["weight"] += config.EVENT_WEIGHTS[action]

    ranked = [s for s in seeds.values() if s["weight"] > config.SEED_MIN_WEIGHT]
    ranked.sort(key=lambda s: s["weight"], reverse=True)
    return ranked[: config.SEED_TOP_N]


def fuse(grouped: dict[str, dict[str, list[Candidate]]],
         source_weights: dict[str, float],
         seed_weight_norm: dict[str, float],
         k: int | None = None) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion tra fonti, pesata per fonte e peso del seed.

    `grouped`: seed_norm → {source → [Candidate ordinati per score desc]}.
    """
    k = config.RRF_K if k is None else k
    agg: dict[str, dict[str, Any]] = {}

    for seed_norm, per_source in grouped.items():
        seed_w = seed_weight_norm.get(seed_norm, 0.0)
        if seed_w <= 0:
            continue
        for source, cands in per_source.items():
            sw = source_weights.get(source, 0.0)
            if sw <= 0:
                continue
            for rank, cand in enumerate(cands, start=1):
                norm = cand.name_norm
                if not norm:
                    continue
                item = agg.setdefault(norm, {
                    "name": cand.name,
                    "name_norm": norm,
                    "mbid": cand.mbid,
                    "score": 0.0,
                    "sources": {},
                    "seeds": set(),
                    "reasons": [],
                })
                if not item["mbid"] and cand.mbid:
                    item["mbid"] = cand.mbid
                contrib = sw * seed_w * (1.0 / (k + rank))
                item["score"] += contrib
                item["sources"][source] = item["sources"].get(source, 0.0) + contrib
                item["seeds"].add(seed_norm)
                if cand.reason:
                    item["reasons"].append({"source": source, "text": cand.reason})

    return sorted(agg.values(), key=lambda x: x["score"], reverse=True)


def diversify(ranked: list[dict[str, Any]], limit: int,
              max_per_seed: int | None = None,
              explore: float | None = None,
              top_n: int | None = None) -> list[dict[str, Any]]:
    """Limita i candidati per seed e riserva una quota `explore` più varia.

    L'`explore` riempie una parte della lista con candidati che sarebbero stati
    scartati dal cap per-seed (quindi più "lontani" dal seed principale).
    """
    max_per_seed = config.MAX_PER_SEED_TOP if max_per_seed is None else max_per_seed
    explore = config.DEFAULT_EXPLORE if explore is None else max(0.0, min(1.0, explore))
    top_n = config.MAX_PER_SEED_TOP_N if top_n is None else top_n

    picked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seed_count: dict[str, int] = {}

    for item in ranked:
        if len(picked) >= limit:
            skipped.append(item)
            continue
        if any(seed_count.get(s, 0) >= max_per_seed for s in item["seeds"]):
            skipped.append(item)
            continue
        picked.append(item)
        for s in item["seeds"]:
            seed_count[s] = seed_count.get(s, 0) + 1

    if explore > 0 and skipped and picked:
        n_explore = min(int(round(limit * explore)), len(skipped))
        if n_explore > 0 and len(picked) > n_explore:
            picked = picked[: max(0, limit - n_explore)] + skipped[:n_explore]

    return picked[:limit]
