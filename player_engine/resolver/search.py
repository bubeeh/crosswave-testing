"""Ricerca per piattaforma (adapter pattern — coerente col normalizer).

La ricerca restituisce SOLO link leggeri (SearchResult): la risoluzione
completa avviene al click via /api/resolve (riserva Astrid: TTF < 5s).

Canali reali verificati (yt-dlp --list-extractors):
  - youtube   → `ytsearchN:"query"`  (estrattore youtube:search, flat)
  - soundcloud→ `scsearchN:"query"`  (estrattore soundcloud:search, flat)
  - bandcamp  → pagina HTML server-rendered bandcamp.com/search (parsed)
  - mixcloud  → API pubblica JSON api.mixcloud.com/search
  - vimeo     → nessun canale: ricerca NON supportata (esclusa dalla UI)

Regole del piano rispettate:
  - rate limiting etico 1 richiesta/5s per piattaforma (anche sul nostro fetch)
  - cache ricerche TTL 30 min (le query cambiano: niente 72h)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from ..core.schema import SearchResult, compute_canonical_id, normalize_thumbnail
from ..storage.repos import RateLimitRepo, SearchCacheRepo
from . import soundcloud_api
from .rate_limit import RateLimiter

# Piattaforme ricercabili (Vimeo escluso: nessun canale)
SEARCHABLE_PLATFORMS: tuple[str, ...] = ("youtube", "soundcloud", "bandcamp", "mixcloud")

YTDLP_SEARCH_TIMEOUT = 25.0
HTTP_TIMEOUT = 15.0
RESULT_LIMIT = 50
# Quante tracce di canali Topic/Official promuovere in cima alla ricerca YT
_PROMOTED_CAP = 15
# Quanti album (raccolte OLAK5uy) mettere in testa alla ricerca YT
_ALBUM_CAP = 8
# Quante voci (miste) leggere dalla pagina risultati YouTube
_YOUTUBE_PAGE_FETCH = 60
# Parole non significative per capire se un canale è pertinente alla query
_STOPWORDS = {
    "official", "video", "audio", "music", "lyrics", "topic", "feat",
    "featuring", "hd", "hq", "full", "album", "live", "remix", "version", "edit",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 PlayerCrossSource/0.1"
)


@dataclass
class SearchOutcome:
    results: list[SearchResult] | None = None
    error_kind: str = ""
    message: str = ""
    retry_after: float = 0.0
    cache_hit: bool = False


def _ytdlp_bin() -> str:
    return os.environ.get("PLAYER_YTDLP_BIN", "yt-dlp")


def _ytdlp_cmd(args: list[str]) -> list[str]:
    bin_ = _ytdlp_bin()
    if bin_.endswith(".py"):
        return [sys.executable, bin_, *args]
    if shutil.which(bin_):
        return [bin_, *args]
    return [sys.executable, "-m", "yt_dlp", *args]


class Searcher:
    """Esegue ricerche per piattaforma, con rate limit e cache 30 min."""

    def __init__(self, conn, rate_limiter: RateLimiter | None = None,
                 cache: SearchCacheRepo | None = None) -> None:
        self._conn = conn
        self.rate = rate_limiter or RateLimiter(RateLimitRepo(conn))
        self.cache = cache or SearchCacheRepo(conn)

    # ------------------------------------------------------------------
    def search(self, platform: str, query: str, limit: int = RESULT_LIMIT) -> SearchOutcome:
        query = query.strip()
        if not query:
            return SearchOutcome(error_kind="bad_query", message="query vuota")
        if platform not in SEARCHABLE_PLATFORMS:
            return SearchOutcome(
                error_kind="search_unsupported",
                message=f"ricerca non supportata per la piattaforma '{platform}'",
            )

        # 1) cache 30 min (prima del rate limit: le query ripetute non consumano slot)
        key = f"{platform}:{query.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            results = [SearchResult.model_validate(r) for r in cached]
            return SearchOutcome(results=results, cache_hit=True)

        # 2) rate limit 1/5s per piattaforma
        gate = self.rate.check(platform)
        if not gate.allowed:
            return SearchOutcome(
                error_kind="rate_limited",
                message=f"Sorgente occupata — riprovo tra {gate.retry_after:.0f}s",
                retry_after=gate.retry_after,
            )

        try:
            if platform == "youtube":
                outcome = self._search_youtube(query, limit)
            elif platform == "soundcloud":
                outcome = self._search_soundcloud(query, limit)
            elif platform == "bandcamp":
                outcome = self._search_bandcamp(query)
            else:
                outcome = self._search_mixcloud(query)
        except Exception as exc:  # mai morire nel worker
            return SearchOutcome(error_kind="search_failed", message=str(exc))

        if outcome.results is not None:
            self.rate.release(platform)
            self.cache.set(key, platform, [r.model_dump(mode="json") for r in outcome.results])
        return outcome

    # ------------------------------------------------------------------
    # youtube / soundcloud: ricerca
    # ------------------------------------------------------------------
    def _search_ytdlp(self, platform: str, query: str, limit: int) -> SearchOutcome:
        prefix = "ytsearch" if platform == "youtube" else "scsearch"
        url = f"{prefix}{limit}:{query}"
        try:
            proc = subprocess.run(
                _ytdlp_cmd(["-J", "--flat-playlist", "--no-warnings", url]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=YTDLP_SEARCH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return SearchOutcome(error_kind="timeout", message=f"timeout ricerca {platform}")
        except FileNotFoundError:
            return SearchOutcome(
                error_kind="search_failed",
                message=f"binario yt-dlp non trovato ('{_ytdlp_bin()}')",
            )
        if proc.returncode != 0:
            return SearchOutcome(
                error_kind="search_failed",
                message=proc.stderr.strip()[:300] or f"yt-dlp fallito ({platform})",
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SearchOutcome(error_kind="search_failed", message=f"output non valido ({platform})")

        results: list[SearchResult] = []
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("title"):
                continue
            # per SoundCloud il flat restituisce url=api.soundcloud.com/...
            # (non risolvibile): usa la pagina canonica quando presente
            entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
            if not entry_url:
                continue
            native_id = entry.get("id")
            channel = str(entry.get("uploader") or entry.get("channel") or entry.get("artist") or "")
            results.append(
                SearchResult(
                    platform=platform,
                    url=entry_url,
                    title=str(entry["title"])[:300],
                    uploader=channel,
                    duration=float(entry.get("duration") or 0.0),
                    thumbnail=_flat_thumb(entry),
                    canonical_id=compute_canonical_id(platform, native_id, entry_url),
                    channel_is_verified=bool(entry.get("channel_is_verified")),
                    is_topic=bool(re.search(r"[-–—]\s*topic$", channel.strip(), re.IGNORECASE)),
                    catalog_url=str(entry.get("channel_url") or ""),
                )
            )
            if len(results) >= limit:
                break
        if not results:
            return SearchOutcome(
                error_kind="no_results", message=f"nessun risultato per '{query}' ({platform})"
            )
        return SearchOutcome(results=results)

    # ------------------------------------------------------------------
    # youtube: una sola flat della pagina risultati (video + album + playlist)
    # ------------------------------------------------------------------
    def _search_youtube(self, query: str, limit: int) -> SearchOutcome:
        """Ricerca YouTube in un'unica chiamata alla pagina /results.

        La pagina risultati non filtrata contiene, insieme ai video, anche le
        **raccolte**: gli album auto-generati (`playlist?list=OLAK5uy_...`) e le
        playlist utente (`list=PL...`). Sono proprio gli album a dare la vista
        album tipo Bandcamp, quindi vanno in testa. I video mantengono i
        metadati canale (Topic/ufficiale) usati per la priorità.
        """
        url = f"https://www.youtube.com/results?search_query={quote(query)}"
        try:
            proc = subprocess.run(
                _ytdlp_cmd(["-J", "--flat-playlist", "--playlist-end",
                            str(max(limit, _YOUTUBE_PAGE_FETCH)), "--no-warnings", url]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=YTDLP_SEARCH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return SearchOutcome(error_kind="timeout", message="timeout ricerca youtube")
        except FileNotFoundError:
            return SearchOutcome(
                error_kind="search_failed",
                message=f"binario yt-dlp non trovato ('{_ytdlp_bin()}')",
            )
        if proc.returncode != 0:
            return SearchOutcome(
                error_kind="search_failed",
                message=proc.stderr.strip()[:300] or "yt-dlp fallito (youtube)",
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SearchOutcome(error_kind="search_failed", message="output non valido (youtube)")

        tracks: list[SearchResult] = []
        albums: list[SearchResult] = []
        playlists: list[SearchResult] = []
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
            title = str(entry.get("title") or "").strip()
            if not entry_url or not title:
                continue
            if "/playlist" in entry_url:
                list_id = str(entry.get("id") or _youtube_list_id(entry_url))
                if list_id.startswith("RD"):
                    continue  # mix radio auto-generati (rumore)
                item = SearchResult(
                    platform="youtube",
                    url=entry_url,
                    title=title[:300],
                    uploader=str(entry.get("channel") or entry.get("uploader") or ""),
                    duration=0.0,
                    thumbnail=_flat_thumb(entry),
                    canonical_id=compute_canonical_id("youtube", entry.get("id"), entry_url),
                )
                (albums if list_id.startswith("OLAK5uy") else playlists).append(item)
            elif entry.get("ie_key") == "Youtube":
                channel = str(entry.get("channel") or entry.get("uploader") or "")
                tracks.append(
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

        if not tracks and not albums and not playlists:
            return SearchOutcome(
                error_kind="no_results", message=f"nessun risultato per '{query}' (youtube)"
            )

        # Ordine: album (vista album) in testa → tracce Topic/ufficiali → altre
        # tracce interallacciate con le playlist utente.
        tokens = _query_tokens(query)
        promoted: list[SearchResult] = []
        others: list[SearchResult] = []
        for r in tracks:
            (promoted if _channel_rank(r, tokens) <= 1 else others).append(r)
        promoted.sort(key=lambda r: 0 if r.is_topic else 1)
        merged = (
            albums[:_ALBUM_CAP]
            + promoted[:_PROMOTED_CAP]
            + _interleave(others, playlists, every=3)
        )
        return SearchOutcome(results=merged[:limit])

    # ------------------------------------------------------------------
    # soundcloud: tracce (scsearch) + RACCOLTE (set/playlist via API v2)
    # ------------------------------------------------------------------
    def _search_soundcloud(self, query: str, limit: int) -> SearchOutcome:
        tracks = self._search_ytdlp("soundcloud", query, limit)
        sets = self._search_soundcloud_sets(query, max(1, limit // 2))
        track_items = tracks.results or []
        set_items = sets.results or []
        if not track_items and not set_items:
            return tracks if tracks.results is None else sets
        merged = _interleave(track_items, set_items, every=3)
        return SearchOutcome(results=merged[:limit])

    def _search_soundcloud_sets(self, query: str, limit: int) -> SearchOutcome:
        """Set/playlist SoundCloud cercati via API v2 pubblica (client_id)."""
        try:
            items = soundcloud_api.search_playlists(query, limit)
        except soundcloud_api.SoundCloudApiError as exc:
            return SearchOutcome(error_kind="search_failed", message=str(exc))

        results: list[SearchResult] = []
        for item in items:
            item_url = str(item.get("permalink_url") or "")
            if not item_url or "/sets/" not in item_url:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            user = item.get("user")
            uploader = str(user.get("username") or "") if isinstance(user, dict) else ""
            results.append(
                SearchResult(
                    platform="soundcloud",
                    url=item_url,
                    title=title[:300],
                    uploader=uploader,
                    duration=float(item.get("duration") or 0.0) / 1000.0,
                    thumbnail=soundcloud_api.artwork_url(item),
                    canonical_id=compute_canonical_id("soundcloud", item.get("id"), item_url),
                )
            )
            if len(results) >= limit:
                break
        if not results:
            return SearchOutcome(
                error_kind="no_results", message=f"nessun set per '{query}' (soundcloud)"
            )
        return SearchOutcome(results=results)

    # ------------------------------------------------------------------
    # bandcamp: API mobile fuzzysearch (JSON) — NON la pagina HTML protetta
    # ------------------------------------------------------------------
    def _search_bandcamp(self, query: str) -> SearchOutcome:
        base = os.environ.get(
            "PLAYER_BANDCAMP_SEARCH_URL",
            "https://bandcamp.com/api/fuzzysearch/1/app_autocomplete",
        )
        url = f"{base}?q={quote(query)}"
        resp = httpx.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code in (403, 429) or "content-security-policy" in resp.headers:
            return SearchOutcome(
                error_kind="search_blocked",
                message=(
                    "Bandcamp ha rifiutato la ricerca: incolla direttamente "
                    "l'URL di una traccia o album in 'Incolla URL'."
                ),
            )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            # challenge anti-bot HTML al posto del JSON
            return SearchOutcome(
                error_kind="search_blocked",
                message=(
                    "Bandcamp protegge la ricerca (anti-bot): incolla direttamente "
                    "l'URL di una traccia o album in 'Incolla URL'."
                ),
            )

        results: list[SearchResult] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or item.get("type") not in ("t", "a"):
                continue  # solo tracce (t) e album (a), niente band (b)
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            item_url = str(item.get("url") or "")
            # l'API restituisce URL duplicati ("https://a.bc.comhttps://a.bc.com/..."):
            # tieni solo l'ultima parte https://
            if item_url.count("https://") > 1:
                item_url = "https://" + item_url.split("https://")[-1]
            elif item_url.startswith("//"):
                item_url = "https:" + item_url
            if not item_url:
                continue
            art_id = item.get("art_id")
            thumbnail = f"https://f4.bcbits.com/img/a{art_id}_2.jpg" if art_id else ""
            results.append(
                SearchResult(
                    platform="bandcamp",
                    url=item_url,
                    title=name[:300],
                    uploader=str(item.get("band_name") or ""),
                    thumbnail=thumbnail,
                    canonical_id=compute_canonical_id("bandcamp", None, item_url),
                    catalog_url=f"{urlparse(item_url).scheme}://{urlparse(item_url).netloc}",
                )
            )
        if not results:
            return SearchOutcome(error_kind="no_results", message=f"nessun risultato per '{query}' (bandcamp)")
        return SearchOutcome(results=results)

    # ------------------------------------------------------------------
    # mixcloud: API JSON pubblica
    # ------------------------------------------------------------------
    def _search_mixcloud(self, query: str) -> SearchOutcome:
        base = os.environ.get("PLAYER_MIXCLOUD_SEARCH_URL", "https://api.mixcloud.com/search/")
        url = f"{base}?q={quote(query)}&type=cloudcast"
        resp = httpx.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("data") or []:
            item_url = str(item.get("url") or "")
            if not item_url:
                continue
            user = (item.get("user") or {}).get("name", "") if isinstance(item.get("user"), dict) else ""
            pictures = item.get("pictures") or {}
            results.append(
                SearchResult(
                    platform="mixcloud",
                    url=item_url,
                    title=str(item.get("name") or item_url)[:300],
                    uploader=str(user),
                    thumbnail=str(pictures.get("medium") or ""),
                    canonical_id=compute_canonical_id("mixcloud", None, item_url),
                )
            )
        if not results:
            return SearchOutcome(error_kind="no_results", message=f"nessun risultato per '{query}' (mixcloud)")
        return SearchOutcome(results=results)


def _youtube_list_id(url: str) -> str:
    """Estrae l'id playlist da un URL YouTube (`...?list=OLAK5uy_...`)."""
    m = re.search(r"[?&]list=([\w-]+)", url)
    return m.group(1) if m else ""


def _query_tokens(query: str) -> list[str]:
    """Token significativi (>=3 char, senza stopword) per il match canale/query."""
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def _strip_topic_suffix(name: str) -> str:
    """'Burial - Topic' → 'Burial' (per confrontare il nome artista)."""
    return re.sub(r"\s*[-–—]\s*topic$", "", name.strip(), flags=re.IGNORECASE).strip()


def _channel_rank(result: SearchResult, tokens: list[str]) -> int:
    """Priorità del canale: 0 = Topic, 1 = verified pertinente, 2 = altri."""
    if result.is_topic:
        return 0
    if result.channel_is_verified:
        name = _strip_topic_suffix(result.uploader).lower()
        if name and (any(t in name for t in tokens) or name in result.title.lower()):
            return 1
    return 2


def _interleave(primary: list[SearchResult], secondary: list[SearchResult], every: int = 3) -> list[SearchResult]:
    """Alterna `primary` e `secondary` (una raccolta ogni `every` tracce).

    Serve a far emergere le raccolte nelle prime pagine dei risultati senza
    seppellire le tracce singole: l'ordine resta deterministico.
    """
    out: list[SearchResult] = []
    pi = si = 0
    while pi < len(primary) or si < len(secondary):
        for _ in range(every):
            if pi < len(primary):
                out.append(primary[pi])
                pi += 1
        if si < len(secondary):
            out.append(secondary[si])
            si += 1
    return out


def _flat_thumb(entry: dict[str, Any]) -> str:
    if entry.get("thumbnail"):
        return normalize_thumbnail(str(entry["thumbnail"]))
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
        return normalize_thumbnail(str(best.get("url") or ""))
    return ""
