from __future__ import annotations

import json
from pathlib import Path

import httpx

from player_engine.recommend.identity import ArtistRef
from player_engine.recommend.sources.lastfm import LastFmSource
from player_engine.recommend.sources.musicbrainz import MusicBrainzSource

RAW = Path(__file__).resolve().parents[1] / "player_engine" / "fixtures" / "raw"


def _load(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


class FakeCache:
    def __init__(self) -> None:
        self.data: dict = {}

    def get(self, source, key):
        return self.data.get((source, key))

    def set(self, source, key, payload):
        self.data[(source, key)] = payload


class FakeLimiter:
    def __init__(self) -> None:
        self.waits = 0

    def wait(self, name) -> float:
        self.waits += 1
        return 0.0


def _client(routes: dict[str, dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, data in routes.items():
            if key in url:
                return httpx.Response(200, json=data)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Last.fm ---
def test_lastfm_parse_fixture():
    cands = LastFmSource._parse(_load("lastfm_similar.json"))
    names = [c.name for c in cands]
    assert names == ["Massive Attack", "Portishead", "Tricky"]
    assert cands[0].score == 1.0
    assert cands[0].mbid == "mb-massive"
    assert all(c.source == "lastfm" for c in cands)


def test_lastfm_disabled_without_key():
    src = LastFmSource(http=_client({}), api_key="")
    assert src.enabled() is False
    assert src.similar(ArtistRef(name="Burial", name_norm="burial")) == []


def test_lastfm_similar_uses_cache_and_limiter():
    cache = FakeCache()
    limiter = FakeLimiter()
    http = _client({"ws.audioscrobbler.com": _load("lastfm_similar.json")})
    src = LastFmSource(http=http, cache=cache, limiter=limiter, api_key="KEY")
    assert src.enabled() is True

    first = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=2)
    assert [c.name for c in first] == ["Massive Attack", "Portishead"]
    assert limiter.waits == 1
    assert ("lastfm", "similar:burial") in cache.data

    second = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=2)
    assert [c.name for c in second] == ["Massive Attack", "Portishead"]
    assert limiter.waits == 1  # seconda chiamata servita dalla cache


# --- MusicBrainz ---
def test_musicbrainz_resolve_and_similar():
    cache = FakeCache()
    limiter = FakeLimiter()
    http = _client({
        "/artist/mb-burial": _load("musicbrainz_artist_rels.json"),
        "/artist": _load("musicbrainz_artist_search.json"),
    })
    src = MusicBrainzSource(http=http, cache=cache, limiter=limiter, user_agent="Test/1.0")

    cands = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=10)
    names = [c.name for c in cands]
    assert "Four Tet" in names and "Massive Attack" in names
    # la relazione non-artist (url) va ignorata
    assert all(c.source == "musicbrainz" for c in cands)

    # MBID risolto e messo in cache
    assert ("musicbrainz", "mbid:burial") in cache.data
    assert cache.data[("musicbrainz", "mbid:burial")]["mbid"] == "mb-burial"


def test_musicbrainz_best_mbid_prefers_exact():
    data = _load("musicbrainz_artist_search.json")
    assert MusicBrainzSource._best_mbid(data, "burial") == "mb-burial"
    assert MusicBrainzSource._best_mbid({"artists": []}, "burial") is None
