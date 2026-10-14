"""Feed editoriali per la sezione "Digging".

Aggrega fonti esterne (Bandcamp Daily, riviste) lette come RSS 2.0 / Atom.
Il parsing usa solo la stdlib (`xml.etree.ElementTree`) per non aggiungere
dipendenze: estrae titolo, link, data, autore, categorie, sommario (HTML
strippato) e la migliore immagine disponibile. Fetch HTTP via `httpx` con
User-Agent e timeout; cache in-memory TTL breve; degrado silenzioso per le
fonti non raggiungibili (es. blocchi anti-bot / IP datacenter).
"""

from __future__ import annotations

import html as html_mod
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

# Fonti di default (seed). L'utente può aggiungerne/rimuoverne dalla UI.
DEFAULT_FEEDS: list[dict[str, str]] = [
    {
        "name": "Bandcamp Daily",
        "url": "https://daily.bandcamp.com/feed",
        "category": "Editoriale",
        "icon": "fa-brands fa-bandcamp",
    },
    {
        "name": "The Wire",
        "url": "https://www.thewire.co.uk/rss",
        "category": "Riviste",
        "icon": "fa-solid fa-wave-square",
    },
    {
        "name": "FACT",
        "url": "https://www.factmag.com/feed/",
        "category": "Elettronica",
        "icon": "fa-solid fa-bolt",
    },
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 CrossWave/0.1"
)
HTTP_TIMEOUT = 15.0
CACHE_TTL = 2700.0          # 45 minuti
MAX_ITEMS_PER_FEED = 40
SUMMARY_MAX = 400

_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()
_http_client: httpx.Client | None = None


def _client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": UA},
        )
    return _http_client


# ---------------------------------------------------------------------------
# Parsing helpers (namespace-agnostici: si confronta il local-name del tag)
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    wanted = set(names)
    for c in list(el):
        if _local(c.tag) in wanted:
            return c
    return None


def _child_text(el: ET.Element, *names: str) -> str:
    c = _child(el, *names)
    if c is None:
        return ""
    return (c.text or "").strip()


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = _SCRIPT_RE.sub(" ", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", " ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_date(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _entry_link(el: ET.Element) -> str:
    for c in list(el):
        if _local(c.tag) == "link":
            href = (c.attrib.get("href") or "").strip()
            if href:
                return href
            if c.text:
                return c.text.strip()
    return ""


def _entry_categories(el: ET.Element) -> list[str]:
    out: list[str] = []
    for c in list(el):
        if _local(c.tag) != "category":
            continue
        term = (c.text or "").strip() or (c.attrib.get("term") or "").strip()
        if term and term not in out:
            out.append(term)
    return out


def _entry_image(el: ET.Element, raw_html: str) -> str:
    for c in list(el):
        ln = _local(c.tag)
        if ln not in ("enclosure", "content", "thumbnail"):
            continue
        url = (c.attrib.get("url") or "").strip()
        if not url:
            continue
        ctype = (c.attrib.get("type") or "").lower()
        is_img = (
            ctype.startswith("image")
            or url.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"))
        )
        if is_img:
            return url
    m = _IMG_RE.search(raw_html or "")
    return m.group(1).strip() if m else ""


def _parse_entry(el: ET.Element, feed: dict[str, Any]) -> dict[str, Any]:
    title = _child_text(el, "title")
    link = _entry_link(el)
    raw = (
        _child_text(el, "encoded")
        or _child_text(el, "description")
        or _child_text(el, "summary")
        or _child_text(el, "content")
    )
    summary = _strip_html(raw)
    if len(summary) > SUMMARY_MAX:
        summary = summary[: SUMMARY_MAX - 3].rstrip() + "..."
    author = _child_text(el, "creator")
    if not author:
        author_el = _child(el, "author")
        if author_el is not None:
            author = _child_text(author_el, "name") or (author_el.text or "").strip()
    published = ""
    for key in ("pubdate", "published", "updated", "date"):
        published = _parse_date(_child_text(el, key))
        if published:
            break
    guid = _child_text(el, "guid", "id") or link
    return {
        "id": guid,
        "title": title,
        "url": link,
        "source": feed.get("name") or "",
        "source_id": feed.get("id"),
        "category": feed.get("category") or "",
        "categories": _entry_categories(el),
        "author": author,
        "published": published,
        "summary": summary,
        "image": _entry_image(el, raw),
    }


def parse_feed(text: str, feed: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Estrae gli item da un feed RSS 2.0, Atom o RDF. Lista vuota se illeggibile."""
    feed = feed or {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    root_name = _local(root.tag)
    if root_name == "rss":
        channel = root.find("channel")
        entries = list(channel) if channel is not None else []
        entries = [e for e in entries if _local(e.tag) == "item"]
    elif root_name == "feed":
        entries = [e for e in root if _local(e.tag) == "entry"]
    elif root_name == "rdf":  # RSS 1.0
        entries = [e for e in root if _local(e.tag) == "item"]
    else:
        entries = []

    items: list[dict[str, Any]] = []
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        item = _parse_entry(entry, feed)
        if item["title"] and item["url"]:
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------
def fetch_feed(feed: dict[str, Any], force: bool = False) -> list[dict[str, Any]]:
    """Scarica e parsa un feed. In caso di errore ricade sulla cache scaduta."""
    url = (feed.get("url") or "").strip()
    if not url:
        return []
    now = time.time()
    if not force:
        with _cache_lock:
            cached = _cache.get(url)
            if cached and now - cached["ts"] < CACHE_TTL:
                return cached["items"]

    try:
        resp = _client().get(url)
        resp.raise_for_status()
        items = parse_feed(resp.text, feed)
    except Exception:
        with _cache_lock:
            cached = _cache.get(url)
        return cached["items"] if cached else []

    with _cache_lock:
        _cache[url] = {"items": items, "ts": now}
    return items


def fetch_all(
    feeds: list[dict[str, Any]], limit: int = 60
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Aggrega più feed in parallelo. Ritorna (items, errori_per_fonte).

    Gli item sono deduplicati per URL e ordinati per data decrescente.
    """
    items: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    if not feeds:
        return [], {}

    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as executor:
        future_to_feed = {executor.submit(fetch_feed, f): f for f in feeds}
        for future in as_completed(future_to_feed):
            feed = future_to_feed[future]
            label = feed.get("name") or feed.get("url") or "feed"
            try:
                got = future.result()
            except Exception as exc:  # pragma: no cover - difensivo
                errors[label] = str(exc)
                continue
            if not got:
                errors[label] = "Feed non raggiungibile o vuoto"
                continue
            for item in got:
                item["source"] = feed.get("name") or item.get("source") or ""
                item["category"] = feed.get("category") or item.get("category") or ""
                item["source_id"] = feed.get("id")
                items.append(item)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = item.get("url") or item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda x: x.get("published") or "", reverse=True)
    return unique[:limit], errors
