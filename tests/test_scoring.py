from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from player_engine.recommend import scoring
from player_engine.recommend.sources.base import Candidate


def test_compute_seed_weights_decay_and_feedback():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {"artist_name_norm": "burial", "artist_name": "Burial", "event_type": "complete",
         "watched_at": now.isoformat()},
        {"artist_name_norm": "burial", "artist_name": "Burial", "event_type": "skip",
         "watched_at": now.isoformat()},
        {"artist_name_norm": "aphex twin", "artist_name": "Aphex Twin", "event_type": "complete",
         "watched_at": (now - timedelta(days=30)).isoformat()},
    ]
    seeds = scoring.compute_seed_weights(events, {"burial": "like"}, now=now)
    by = {s["name_norm"]: s["weight"] for s in seeds}
    assert by["burial"] == pytest.approx(2.2, rel=1e-3)   # 1.0 - 0.3 + 1.5
    assert by["aphex twin"] == pytest.approx(0.5, rel=1e-3)  # 1.0 * 0.5^(30/30)
    assert seeds[0]["name_norm"] == "burial"


def test_fuse_respects_source_weights_and_rank():
    grouped = {
        "burial": {
            "lastfm": [Candidate("A", "lastfm", 0.9, reason="simile (Last.fm)")],
            "musicbrainz": [Candidate("B", "musicbrainz", 0.9, reason="membro di Burial")],
        }
    }
    # modalità close: lastfm pesa di più
    ranked = scoring.fuse(grouped, {"lastfm": 1.0, "musicbrainz": 0.4}, {"burial": 1.0})
    assert ranked[0]["name"] == "A"
    assert ranked[0]["reasons"][0]["source"] == "lastfm"

    # modalità scene: musicbrainz pesa di più
    ranked_scene = scoring.fuse(grouped, {"lastfm": 0.4, "musicbrainz": 1.0}, {"burial": 1.0})
    assert ranked_scene[0]["name"] == "B"


def _item(name: str, seeds: set[str]) -> dict:
    return {"name": name, "name_norm": name, "mbid": None, "score": 0.0,
            "sources": {}, "seeds": set(seeds), "reasons": []}


def test_diversify_caps_per_seed():
    ranked = [
        _item("a", {"s1"}), _item("b", {"s2"}), _item("c", {"s1"}),
        _item("d", {"s1"}), _item("e", {"s2"}),
    ]
    out = scoring.diversify(ranked, limit=4, max_per_seed=2, explore=0.0)
    assert [i["name"] for i in out] == ["a", "b", "c", "e"]


def test_diversify_explore_pulls_skipped():
    ranked = [
        _item("a", {"s1"}), _item("b", {"s1"}), _item("c", {"s1"}), _item("d", {"s2"}),
    ]
    out = scoring.diversify(ranked, limit=4, max_per_seed=2, explore=0.5)
    names = [i["name"] for i in out]
    assert "c" in names            # ex-scartato per cap, ripescato dall'explore
    assert len(names) == len(set(names))
