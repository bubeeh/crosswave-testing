"""Esplorazione cataloghi: discografie e canali apribili dalla ricerca.

Supporta (v1):
  - Bandcamp: pagina artista/label `https://<band>.bandcamp.com/music` →
    attributo HTML `data-client-items` (JSON con l'intera discografia).
    Da un URL di album/track si rileva anche l'etichetta collegata
    (`back-to-label-link`) per offrire il catalogo della label.
  - YouTube: canale/artista `https://www.youtube.com/channel/<id>`.
    Ordine di sezioni: `/releases` (album, playlist OLAK5uy), poi
    `/playlists`, poi `/videos` con fallback alla root per i canali Topic
    (che non espongono i tab videos/releases).

Ogni elemento usa il contratto leggero `SearchResult` (kind derivabile da
`is_collection_url`: album/playlist → apribile nella vista album; watch/track
→ riproducibile). Limite semplice per sezione (`CATALOG_LIMIT`).
"""

from __future__ import annotations

import html as html_mod
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from ..core.schema import SearchResult, compute_canonical_id
from .search import YTDLP_SEARCH_TIMEOUT, _flat_thumb, _ytdlp_cmd

CATALOG_LIMIT = 100

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 PlayerCrossSource/0.1"
)
HTTP_TIMEOUT = 20.0


@dataclass
class CatalogSection:
    key: str
    label: str
    items: list[SearchResult] = field(default_factory=list)


@dataclass
class Catalog:
    name: str
    platform: str
    source_url: str
    thumbnail: str = ""
    sections: list[CatalogSection] = field(default_factory=list)
    related: list[dict[str, str]] = field(default_factory=list)


def catalog_to_dict(cat: Catalog) -> dict[str, Any]:
    return {
        "name": cat.name,
        "platform": cat.platform,
        "source_url": cat.source_url,
        "thumbnail": cat.thumbnail,
        "sections": [
            {
                "key": s.key,
                "label": s.label,
                "total": len(s.items),
                "items": [i.model_dump(mode="json") for i in s.items],
            }
            for s in cat.sections
        ],
        "related": cat.related,
    }


def build_catalog(platform: str, url: str, limit: int = CATALOG_LIMIT,
                  topic_hint: bool = False) -> Catalog:
    """Costruisce il catalogo per la piattaforma. Solleva ValueError se non supportata.

    `topic_hint=True` (dalla ricerca) evita i tab releases/playlists/videos sui
    canali Topic, che non li espongono: si usa subito la root (upload).
    """
    if platform == "bandcamp":
        return _bandcamp_catalog(url, limit)
    if platform == "youtube":
        return _youtube_catalog(url, limit, topic_hint)
    raise ValueError(f"catalogo non supportato per '{platform}'")


# ---------------------------------------------------------------------------
# Bandcamp
# ---------------------------------------------------------------------------
def _bandcamp_profile_url(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        raise ValueError(f"URL Bandcamp non valido: {url}")
    return f"{p.scheme}://{p.netloc}"


def _extract_bandcamp_label(url: str) -> dict[str, str] | None:
    """Rileva l'etichetta collegata alla release (link 'back-to-label')."""
    try:
        resp = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=HTTP_TIMEOUT)
        page = resp.text
    except Exception:
        return None
    m = re.search(r"<a[^>]*back-to-label-link[^>]*>(.*?)</a>", page, re.DOTALL)
    if not m:
        return None
    tag = m.group(0)
    host_match = re.search(r"href=\"https?://([a-z0-9-]+)\.bandcamp\.com", tag)
    if not host_match:
        return None
    label_host = host_match.group(1)
    name = re.sub(r"<[^>]+>", " ", m.group(1))
    name = html_mod.unescape(name).replace("←", " ").replace("→", " ").strip()
    name = re.sub(r"^\s*(more from|back to)\s*", "", name, flags=re.IGNORECASE).strip()
    return {
        "name": name or label_host,
        "url": f"https://{label_host}.bandcamp.com",
        "platform": "bandcamp",
        "kind": "label",
    }


def _bandcamp_items_from_json(page: str) -> list[SearchResult]:
    match = re.search(r"data-client-items=\"([^\"]*)\"", page)
    if not match:
        return []
    try:
        raw_items = json.loads(html_mod.unescape(match.group(1)))
    except (json.JSONDecodeError, TypeError):
        return []
    items: list[SearchResult] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        page_url = str(item.get("page_url") or "").split("?")[0]
        title = str(item.get("title") or "").strip()
        if not page_url or not title:
            continue
        art_id = item.get("art_id")
        items.append(
            SearchResult(
                platform="bandcamp",
                url=page_url,
                title=title[:300],
                uploader=str(item.get("artist") or ""),
                thumbnail=f"https://f4.bcbits.com/img/a{art_id}_2.jpg" if art_id else "",
                canonical_id=compute_canonical_id("bandcamp", None, page_url),
                catalog_url=f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}",
            )
        )
    return items


def _bandcamp_items_from_grid(page: str, profile_url: str) -> list[SearchResult]:
    """Fallback: griglia server-rendered `<ol id="music-grid">` (artisti
    piccoli che non espongono `data-client-items`)."""
    grid_match = re.search(r"<ol id=\"music-grid\"(.*?)</ol>", page, re.DOTALL)
    if not grid_match:
        return []
    items: list[SearchResult] = []
    for block in re.findall(r"<li\b.*?</li>", grid_match.group(1), re.DOTALL):
        href_match = re.search(r"href=\"(/album/[^\"#?]+|/track/[^\"#?]+)\"", block)
        if not href_match:
            continue
        rel = href_match.group(1)
        title_match = re.search(r"<p class=\"title\">(.*?)</p>", block, re.DOTALL)
        title = html_mod.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))).strip() if title_match else ""
        if not title:
            continue
        img_match = re.search(r"<img[^>]+src=\"([^\"]+)\"", block)
        thumb = img_match.group(1) if img_match else ""
        page_url = f"{profile_url}{rel}"
        items.append(
            SearchResult(
                platform="bandcamp",
                url=page_url,
                title=title[:300],
                uploader="",
                thumbnail=thumb,
                canonical_id=compute_canonical_id("bandcamp", None, page_url),
                catalog_url=profile_url,
            )
        )
    return items


def _bandcamp_catalog(url: str, limit: int) -> Catalog:
    profile_url = _bandcamp_profile_url(url)
    related: list[dict[str, str]] = []
    if "/album/" in url or "/track/" in url:
        label = _extract_bandcamp_label(url)
        if label and label["url"] != profile_url:
            related.append(label)

    music_url = f"{profile_url}/music"
    resp = httpx.get(music_url, headers={"User-Agent": UA}, follow_redirects=True, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    page = resp.text

    items = _bandcamp_items_from_json(page)
    if not items:
        items = _bandcamp_items_from_grid(page, profile_url)

    name = _og_meta(page, "og:site_name") or urlparse(profile_url).netloc.split(".")[0]
    thumbnail = _og_meta(page, "og:image")
    if not thumbnail and items:
        thumbnail = items[0].thumbnail

    sections: list[CatalogSection] = []
    if items:
        sections.append(CatalogSection(key="releases", label="Uscite", items=items[:limit]))
    return Catalog(
        name=name,
        platform="bandcamp",
        source_url=profile_url,
        thumbnail=thumbnail,
        sections=sections,
        related=related,
    )


def _og_meta(page: str, prop: str) -> str:
    for pattern in (
        rf"<meta[^>]+property=\"{prop}\"[^>]+content=\"([^\"]*)\"",
        rf"<meta[^>]+content=\"([^\"]*)\"[^>]+property=\"{prop}\"",
    ):
        m = re.search(pattern, page)
        if m:
            return html_mod.unescape(m.group(1)).strip()
    return ""


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
def _yt_flat(url: str, limit: int) -> dict[str, Any] | None:
    """Flat yt-dlp su un tab canale. None se il tab non esiste/fallisce."""
    try:
        proc = subprocess.run(
            _ytdlp_cmd(["-J", "--flat-playlist", "--playlist-end", str(limit),
                        "--no-warnings", url]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=YTDLP_SEARCH_TIMEOUT + 15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _yt_items(data: dict[str, Any]) -> list[SearchResult]:
    items: list[SearchResult] = []
    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
        title = str(entry.get("title") or "").strip()
        if not entry_url or not title:
            continue
        channel = str(entry.get("channel") or entry.get("uploader") or "")
        items.append(
            SearchResult(
                platform="youtube",
                url=entry_url,
                title=title[:300],
                uploader=channel,
                duration=float(entry.get("duration") or 0.0),
                thumbnail=_flat_thumb(entry),
                canonical_id=compute_canonical_id("youtube", entry.get("id"), entry_url),
                channel_is_verified=bool(entry.get("channel_is_verified")),
                is_topic=bool(re.search(r"[-–—]\s*topic$", channel.strip(), re.IGNORECASE)),
                catalog_url=str(entry.get("channel_url") or ""),
            )
        )
    return items


def _youtube_catalog(url: str, limit: int, topic_hint: bool = False) -> Catalog:
    base = url.rstrip("/")
    name = ""
    thumbnail = ""
    sections: list[CatalogSection] = []

    def add_section(key: str, label: str, data: dict[str, Any] | None) -> bool:
        nonlocal name, thumbnail
        if not data:
            return False
        items = _yt_items(data)
        if not items:
            return False
        if not name:
            name = str(data.get("channel") or data.get("uploader") or data.get("title") or "YouTube")
        if not thumbnail:
            thumbnail = items[0].thumbnail
        sections.append(CatalogSection(key=key, label=label, items=items[:limit]))
        return True

    if topic_hint:
        # Canale Topic: niente tab releases/playlists/videos → root = upload.
        add_section("uploads", "Upload", _yt_flat(base, limit))
    else:
        has_releases = add_section("releases", "Uscite", _yt_flat(f"{base}/releases", limit))
        add_section("playlists", "Playlist", _yt_flat(f"{base}/playlists", limit))
        if not has_releases:
            # Canali normali: /videos; fallback root per layout non standard.
            if not add_section("uploads", "Upload", _yt_flat(f"{base}/videos", limit)):
                add_section("uploads", "Upload", _yt_flat(base, limit))

    if not sections:
        raise ValueError("nessuna uscita trovata per questo canale")
    return Catalog(name=name or "Canale", platform="youtube", source_url=base, thumbnail=thumbnail, sections=sections)
