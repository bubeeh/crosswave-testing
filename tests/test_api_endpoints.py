"""Test degli endpoint Flask che non richiedono rete né il resolver attivo."""

from __future__ import annotations


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_search_requires_query(client):
    assert client.get("/api/search").status_code == 400


def test_search_rejects_invalid_sources(client):
    resp = client.get("/api/search?q=burial&sources=vimeo")
    assert resp.status_code == 400


def test_collection_requires_url(client):
    assert client.get("/api/collection").status_code == 400


def test_catalog_requires_url(client):
    assert client.get("/api/catalog").status_code == 400


def test_catalog_rejects_unsupported_platform(client):
    resp = client.get("/api/catalog?url=https://x&platform=vimeo")
    assert resp.status_code == 400


def test_play_requires_seconds_and_track(client):
    assert client.post("/api/play", json={}).status_code == 400
    assert client.post("/api/play", json={"seconds": 10}).status_code == 400


def test_feedback_validation(client):
    assert client.post("/api/recommendations/feedback", json={}).status_code == 400
    resp = client.post("/api/recommendations/feedback", json={"artist": "x", "action": "bad"})
    assert resp.status_code == 400


def test_recommendations_empty_history(client):
    resp = client.get("/api/recommendations")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


def test_radios_listing(client):
    resp = client.get("/api/radios")
    assert resp.status_code == 200
    assert "radios" in resp.get_json()


def test_search_returns_unified_items(client, app_module, monkeypatch):
    """`/api/search` fonde i risultati in `items` tenendo `results` per-sorgente."""
    from player_engine.core.schema import SearchResult

    def fake_search(source, query, max_results=50):
        by_source = {
            "youtube": [SearchResult(
                platform="youtube", url="https://www.youtube.com/watch?v=abc",
                title="Burial - Archangel", uploader="Burial")],
            "bandcamp": [SearchResult(
                platform="bandcamp", url="https://a.bandcamp.com/album/x",
                title="Qualcos'altro", uploader="Altro")],
        }
        raw = by_source.get(source, [])
        return {"results": [{"title": r.title, "source": source} for r in raw],
                "raw_results": raw, "error": None, "message": "", "retry_after": 0}

    monkeypatch.setattr(app_module, "execute_platform_search", fake_search)

    resp = client.get("/api/search?q=burial+archangel&sources=youtube,bandcamp")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["items"], list) and body["items"]
    assert body["items"][0]["title"] == "Burial - Archangel"
    # dict per-sorgente preservato e ripulito dai risultati grezzi (non JSON)
    assert set(body["results"].keys()) == {"youtube", "bandcamp"}
    assert "raw_results" not in body["results"]["youtube"]

