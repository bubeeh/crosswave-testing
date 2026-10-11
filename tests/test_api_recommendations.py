from __future__ import annotations


def _track(cid: str = "sha256:abc", url: str = "https://www.youtube.com/watch?v=abc") -> dict:
    return {
        "canonical_id": cid,
        "source": "youtube",
        "url": url,
        "title": "Test Track",
        "artist": "Test Artist",
        "duration": 100,
    }


def test_play_backward_compatible(client):
    r = client.post("/api/play", json={"track": _track(), "seconds": 90})
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_play_extended_event_types(client):
    r = client.post("/api/play", json={"track": _track(), "seconds": 95, "completion": 0.95})
    assert r.get_json()["event_type"] == "complete"

    r = client.post("/api/play", json={"track": _track(), "seconds": 5})
    assert r.get_json()["event_type"] == "skip"

    r = client.post("/api/play", json={"track": _track(), "seconds": 60, "event_type": "replay"})
    assert r.get_json()["event_type"] == "replay"


def test_play_validation(client):
    assert client.post("/api/play", json={"track": _track(), "seconds": 0}).status_code == 400
    assert client.post("/api/play", json={"seconds": 30}).status_code == 400


def test_feedback(client):
    ok = client.post("/api/recommendations/feedback", json={"artist": "Burial", "action": "like"})
    assert ok.status_code == 200
    bad = client.post("/api/recommendations/feedback", json={"artist": "Burial", "action": "nope"})
    assert bad.status_code == 400
    missing = client.post("/api/recommendations/feedback", json={"action": "like"})
    assert missing.status_code == 400


def test_seeds(client):
    r = client.post("/api/recommendations/seeds", json={"artists": ["Burial", "Aphex Twin", ""]})
    assert r.status_code == 200
    assert r.get_json()["seeds"] == ["burial", "aphex twin"]
    assert client.post("/api/recommendations/seeds", json={"artists": "nope"}).status_code == 400


def test_recommendations_and_forget(client):
    client.post("/api/play", json={"track": _track("sha256:z", "https://www.youtube.com/watch?v=z"), "seconds": 60})
    r = client.get("/api/recommendations")
    assert r.status_code == 200
    assert "items" in r.get_json()
    assert client.post("/api/recommendations/forget").status_code == 200
