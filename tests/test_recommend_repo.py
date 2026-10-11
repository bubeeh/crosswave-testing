from __future__ import annotations

from player_engine.core.schema import MediaObject, MediaType, compute_canonical_id
from player_engine.recommend.identity import resolve_local
from player_engine.recommend.worker import RecommendationEngine
from player_engine.storage.db import init_db
from player_engine.storage.repos import ArtistRepo, FeedbackRepo, HistoryRepo


def _media(title: str, artist: str, url: str) -> MediaObject:
    return MediaObject(
        canonical_id=compute_canonical_id("youtube", None, url),
        platform="youtube",
        source_url=url,
        title=title,
        uploader=artist,
        duration=180.0,
        media_type=MediaType.VIDEO,
        tags=["youtube", f"artist:{artist}"],
    )


def test_artist_resolve_links_and_aliases():
    conn = init_db(":memory:")
    repo = ArtistRepo(conn)
    ref = resolve_local(repo, "Burial - Topic", platform="youtube", url="https://www.youtube.com/watch?v=x")
    assert ref is not None
    assert ref.name_norm == "burial"

    stored = repo.get_by_norm("burial")
    assert stored and stored["id"] == ref.artist_id

    links = repo.list_links(ref.artist_id)
    assert links and links[0] == {"platform": "youtube", "url": "https://www.youtube.com/watch?v=x"}

    # variante/diacritici → stesso artista
    again = resolve_local(repo, "BÜRIAL")
    assert again.artist_id == ref.artist_id
    conn.close()


def test_record_event_and_engine():
    conn = init_db(":memory:")
    repo = ArtistRepo(conn)
    history = HistoryRepo(conn)
    feedback = FeedbackRepo(conn)

    ref = resolve_local(repo, "Artist X")
    media = _media("Track A", "Artist X", "https://www.youtube.com/watch?v=aaaaaaaaaaa")
    history.record_event(media, 180.0, event_type="complete", completion=1.0, artist_id=ref.artist_id)

    row = conn.execute("SELECT event_type, completion, artist_id FROM history_events").fetchone()
    assert row["event_type"] == "complete"
    assert row["completion"] == 1.0
    assert row["artist_id"] == ref.artist_id

    engine = RecommendationEngine(conn)
    assert engine.recompute() >= 1
    items = engine.home(10)
    assert items and items[0]["title"] == "Track A"
    assert items[0]["uploader"] == "Artist X"

    feedback.add("burial", "dislike")
    feedback.add("burial", "like")
    assert feedback.latest_actions()["burial"] == "like"
    feedback.clear()
    assert feedback.list_all() == []
    conn.close()
