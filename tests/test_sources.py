from __future__ import annotations

import json
from pathlib import Path

import httpx

from player_engine.recommend.identity import ArtistRef
from player_engine.recommend.sources.bandcamp import BandcampSource
from player_engine.recommend.sources.discogs import DiscogsSource
from player_engine.recommend.sources.lastfm import LastFmSource
from player_engine.recommend.sources.musicbrainz import MusicBrainzSource
from player_engine.recommend.sources.soundcloud import SoundCloudSource
from player_engine.recommend.sources.youtube import YouTubeSource

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


# --- Fase 2: YouTube, SoundCloud, Bandcamp, Discogs ---
class _R:
    def __init__(self, url, uploader="", title=""):
        self.url = url
        self.uploader = uploader
        self.title = title


class _FakeResolver:
    def search(self, platform, query):
        return [_R("https://www.youtube.com/watch?v=abc123")]

    def related(self, video_id, limit):
        return [_R("https://www.youtube.com/watch?v=x", uploader="Four Tet"),
                _R("https://www.youtube.com/watch?v=y", uploader="Burial - Topic")]


def test_youtube_source_from_related():
    src = YouTubeSource(_FakeResolver())
    cands = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=10)
    assert [c.name for c in cands] == ["Four Tet"]   # "Burial - Topic" normalizza al seed
    assert cands[0].source == "youtube"


class _FakeSC:
    def search_tracks(self, query, limit):
        return [{"id": 1, "user": {"username": "Burial"}}]

    def related_tracks(self, track_id, limit):
        return [{"user": {"username": "Four Tet"}}, {"user": {"username": "Burial"}}]


def test_soundcloud_source_from_related():
    src = SoundCloudSource(api=_FakeSC())
    cands = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=10)
    assert [c.name for c in cands] == ["Four Tet"]
    assert cands[0].source == "soundcloud"


class _Item:
    def __init__(self, uploader):
        self.uploader = uploader


class _Section:
    def __init__(self, artists):
        self.items = [_Item(a) for a in artists]


class _Catalog:
    def __init__(self, name, artists):
        self.name = name
        self.sections = [_Section(artists)]


def test_bandcamp_source_same_label():
    def search(q):
        return [{"url": "https://ghostly.bandcamp.com/album/x", "band_name": "Ghostly"}]

    def catalog(url):
        return _Catalog("Ghostly International", ["TOPS", "Casey MQ", "TOPS"])

    src = BandcampSource(search_fn=search, catalog_fn=catalog)
    cands = src.similar(ArtistRef(name="TOPS", name_norm="tops"), limit=10)
    assert [c.name for c in cands] == ["Casey MQ"]
    assert "Ghostly International" in cands[0].reason


def test_discogs_source_same_label():
    def handler(request):
        params = request.url.params
        if params.get("artist") == "Burial":
            return httpx.Response(200, json={"results": [
                {"title": "Burial - Untrue", "label": ["Hyperdub"], "type": "release"}]})
        if params.get("label") == "Hyperdub":
            return httpx.Response(200, json={"results": [
                {"title": "Kode9 - Memories", "type": "release"},
                {"title": "Burial - Untrue", "type": "release"}]})
        return httpx.Response(200, json={"results": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    src = DiscogsSource(http, token="TOKEN")
    assert src.enabled() is True
    cands = src.similar(ArtistRef(name="Burial", name_norm="burial"), limit=10)
    assert [c.name for c in cands] == ["Kode9"]
    assert "stessa etichetta: Hyperdub" in cands[0].reason

    assert DiscogsSource(http, token="").enabled() is False
    assert DiscogsSource(http, token="").similar(ArtistRef(name="X", name_norm="x")) == []
