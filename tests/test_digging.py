"""Test della sezione Digging: parsing feed e endpoint (senza rete)."""

from __future__ import annotations

from pathlib import Path

from web import digging

RAW = Path(__file__).resolve().parents[1] / "player_engine" / "fixtures" / "raw"


def _load(name: str) -> str:
    return (RAW / name).read_text(encoding="utf-8")


def test_parse_rss_feed():
    items = digging.parse_feed(_load("digging_rss.xml"), {"name": "Example Mag", "category": "Editoriale"})
    assert len(items) == 2

    first = items[0]
    assert first["title"] == "Kou Records Builds Community"
    assert first["url"] == "https://example.com/label-profile/kou-records"
    assert first["source"] == "Example Mag"
    assert first["category"] == "Editoriale"
    assert first["author"] == "George Grella"
    assert first["categories"] == ["Label Profile"]
    assert first["image"] == "https://cdn.example.com/kou.jpg"
    assert first["summary"].startswith("The Brooklyn label")
    assert first["published"].startswith("2026-10-14")

    second = items[1]
    assert second["image"] == "https://cdn.example.com/second.jpg"
    assert second["summary"] == "Plain summary here."


def test_parse_atom_feed():
    items = digging.parse_feed(_load("digging_atom.xml"), {"name": "Atom Mag"})
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Atom Entry One"
    assert item["url"] == "https://atom.example.com/one"
    assert item["author"] == "Jane Doe"
    assert item["categories"] == ["Features"]
    assert item["summary"].startswith("An atom summary")
    assert item["published"].startswith("2026-10-10")


def test_parse_invalid_returns_empty():
    assert digging.parse_feed("not xml at all") == []


def test_fetch_all_dedup_and_sort(monkeypatch):
    feed_a = {"id": 1, "name": "A", "url": "a", "category": "CatA"}
    feed_b = {"id": 2, "name": "B", "url": "b", "category": "CatB"}

    def fake_fetch(feed, force=False):
        if feed["url"] == "a":
            return [{"id": "1", "title": "Old A", "url": "https://x/1",
                     "published": "2026-10-01T00:00:00+00:00"}]
        return [
            {"id": "2", "title": "New B", "url": "https://x/2",
             "published": "2026-10-14T00:00:00+00:00"},
            {"id": "1", "title": "Old A dup", "url": "https://x/1",
             "published": "2026-10-01T00:00:00+00:00"},
        ]

    monkeypatch.setattr(digging, "fetch_feed", fake_fetch)
    items, errors = digging.fetch_all([feed_a, feed_b], limit=10)

    assert errors == {}
    assert [i["url"] for i in items] == ["https://x/2", "https://x/1"]  # dedup + data desc
    assert items[0]["source"] == "B"
    assert items[0]["category"] == "CatB"


def test_fetch_all_reports_empty_feed(monkeypatch):
    monkeypatch.setattr(digging, "fetch_feed", lambda feed, force=False: [])
    items, errors = digging.fetch_all([{"name": "Void", "url": "v", "category": ""}])
    assert items == []
    assert "Void" in errors


def test_api_digging_feeds_listing(client):
    resp = client.get("/api/digging/feeds")
    assert resp.status_code == 200
    feeds = resp.get_json()["feeds"]
    assert any(f["name"] == "Bandcamp Daily" for f in feeds)


def test_api_digging_aggregates(client, app_module, monkeypatch):
    def fake_fetch_all(feeds, limit=60):
        return ([{"id": "1", "title": "Hello", "url": "https://x/1",
                  "source": "Fonte", "category": "Cat", "published": "", "summary": "", "image": ""}],
                {})

    monkeypatch.setattr(app_module.digging, "fetch_all", fake_fetch_all)
    resp = client.get("/api/digging?limit=5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"][0]["title"] == "Hello"
    assert "feeds" in body and "errors" in body


def test_api_digging_feeds_crud(client):
    url = "https://example.test/digging-feed.xml"
    # validazione
    assert client.post("/api/digging/feeds", json={}).status_code == 400
    assert client.post("/api/digging/feeds", json={"name": "X", "url": "ftp://x"}).status_code == 400

    created = client.post("/api/digging/feeds",
                          json={"name": "Test Feed", "url": url, "category": "Test"})
    assert created.status_code == 200
    feed_id = created.get_json()["id"]

    assert client.post("/api/digging/feeds",
                       json={"name": "Test Feed", "url": url, "category": "Test"}).status_code == 400

    feeds = client.get("/api/digging/feeds").get_json()["feeds"]
    assert any(f["id"] == feed_id for f in feeds)

    assert client.delete(f"/api/digging/feeds/{feed_id}").status_code == 200
    feeds = client.get("/api/digging/feeds").get_json()["feeds"]
    assert all(f["id"] != feed_id for f in feeds)
