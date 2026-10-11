from __future__ import annotations

from player_engine.core.schema import MediaObject, MediaType, compute_canonical_id
from player_engine.recommend.identity import resolve_local
from player_engine.recommend.sources.base import Candidate
from player_engine.recommend.worker import RecommendationEngine
from player_engine.storage.db import init_db
from player_engine.storage.repos import ArtistRepo, HistoryRepo


class FakeSource:
    def __init__(self, name: str, mapping: dict[str, list[dict]]) -> None:
        self.name = name
        self._mapping = mapping

    def enabled(self) -> bool:
        return True

    def similar(self, artist, limit: int) -> list[Candidate]:
        return [Candidate(**c) for c in self._mapping.get(artist.name_norm, [])][:limit]


def _media(artist: str, url: str) -> MediaObject:
    return MediaObject(
        canonical_id=compute_canonical_id("youtube", None, url),
        platform="youtube",
        source_url=url,
        title="Track",
        uploader=artist,
        duration=180.0,
        media_type=MediaType.VIDEO,
        tags=["youtube", f"artist:{artist}"],
    )


def _seed(conn, artist: str, url: str):
    ref = resolve_local(ArtistRepo(conn), artist)
    HistoryRepo(conn).record_event(_media(artist, url), 180.0, event_type="complete",
                                    completion=1.0, artist_id=ref.artist_id)
    return ref


def test_recommend_modes_weight_sources_differently():
    conn = init_db(":memory:")
    _seed(conn, "Burial", "https://www.youtube.com/watch?v=1")

    lastfm = FakeSource("lastfm", {"burial": [
        {"name": "A", "source": "lastfm", "score": 0.9, "reason": "simile (Last.fm)"},
    ]})
    mb = FakeSource("musicbrainz", {"burial": [
        {"name": "B", "source": "musicbrainz", "score": 0.9, "reason": "membro di Burial"},
    ]})
    engine = RecommendationEngine(conn)

    close = engine.recommend(mode="close", explore=0.0, limit=5, sources=[lastfm, mb])
    scene = engine.recommend(mode="scene", explore=0.0, limit=5, sources=[lastfm, mb])

    assert close[0]["name"] == "A"
    assert scene[0]["name"] == "B"
    conn.close()


def test_recommend_reasons_and_excludes_seeds():
    conn = init_db(":memory:")
    _seed(conn, "Burial", "https://www.youtube.com/watch?v=1")

    lastfm = FakeSource("lastfm", {"burial": [
        {"name": "Burial", "source": "lastfm", "score": 0.99, "reason": "self"},
        {"name": "Four Tet", "source": "lastfm", "score": 0.8, "reason": "simile (Last.fm)"},
    ]})
    engine = RecommendationEngine(conn)
    items = engine.recommend(mode="close", explore=0.0, limit=5, sources=[lastfm])

    names = [i["name"] for i in items]
    assert "Four Tet" in names
    assert "Burial" not in names           # seed escluso dai candidati
    assert items[0]["reasons"][0]["text"] == "simile (Last.fm)"
    assert items[0]["mode"] == "close"
    assert items[0]["sources"][0]["source"] == "lastfm"
    conn.close()


def test_recommend_empty_without_seeds():
    conn = init_db(":memory:")
    engine = RecommendationEngine(conn)
    assert engine.recommend(mode="mixed", sources=[]) == []
    conn.close()
