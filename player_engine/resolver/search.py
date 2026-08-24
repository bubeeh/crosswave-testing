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

import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from ..core.schema import SearchResult, compute_canonical_id
from .rate_limit import RateLimiter
from ..storage.repos import RateLimitRepo, SearchCacheRepo

# Piattaforme ricercabili (Vimeo escluso: nessun canale)
SEARCHABLE_PLATFORMS: tuple[str, ...] = ("youtube", "soundcloud", "bandcamp", "mixcloud")

YTDLP_SEARCH_TIMEOUT = 25.0
CHANNEL_FETCH_TIMEOUT = 30.0
HTTP_TIMEOUT = 15.0
RESULT_LIMIT = 20
# Solo mix/set lunghi nella sezione Mix Random: 20 min di soglia
MIX_MIN_DURATION = 1200.0

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
    return [bin_, *args]


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
            if platform in ("youtube", "soundcloud"):
                outcome = self._search_ytdlp(platform, query, limit)
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
    # Feed canale (sezione Mix Random): solo mix/DJ set lunghi
    # ------------------------------------------------------------------
    def fetch_channel(self, platform: str, channel_id: str, limit: int = 20) -> SearchOutcome:
        """Ultimi mix di un canale curato (CHANNELS registry).

        YouTube → /channel/<id>/videos flat (verificato: ~1.7s per 15 upload);
        Mixcloud → API pubblica utente cloudcasts. Entrambi con filtro
        durata >= MIX_MIN_DURATION (solo set lunghi, niente video parlati).
        Stessi vincoli della ricerca: rate limit 1/5s e cache 30 min.
        """
        if platform not in ("youtube", "mixcloud"):
            return SearchOutcome(
                error_kind="search_unsupported",
                message=f"feed canale non supportato per '{platform}'",
            )
        key = f"channel:{platform}:{channel_id.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            results = [SearchResult.model_validate(r) for r in cached]
            return SearchOutcome(results=results, cache_hit=True)

        gate = self.rate.check(platform)
        if not gate.allowed:
            return SearchOutcome(
                error_kind="rate_limited",
                message=f"Sorgente occupata — riprovo tra {gate.retry_after:.0f}s",
                retry_after=gate.retry_after,
            )

        try:
            if platform == "youtube":
                outcome = self._channel_youtube(channel_id, limit)
            else:
                outcome = self._channel_mixcloud(channel_id, limit)
        except Exception as exc:  # mai morire nel worker
            return SearchOutcome(error_kind="search_failed", message=str(exc))

        if outcome.results is not None:
            self.rate.release(platform)
            self.cache.set(key, platform, [r.model_dump(mode="json") for r in outcome.results])
        return outcome

    def _channel_youtube(self, channel_id: str, limit: int) -> SearchOutcome:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        try:
            proc = subprocess.run(
                _ytdlp_cmd(["-J", "--flat-playlist", "--playlist-end", str(limit),
                            "--no-warnings", url]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CHANNEL_FETCH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return SearchOutcome(error_kind="timeout", message=f"timeout feed canale {channel_id}")
        except FileNotFoundError:
            return SearchOutcome(
                error_kind="search_failed",
                message=f"binario yt-dlp non trovato ('{_ytdlp_bin()}')",
            )
        if proc.returncode != 0:
            return SearchOutcome(
                error_kind="search_failed",
                message=proc.stderr.strip()[:300] or f"yt-dlp fallito ({channel_id})",
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SearchOutcome(error_kind="search_failed", message="output non valido")

        channel_name = str(data.get("channel") or data.get("uploader") or "YouTube")
        results: list[SearchResult] = []
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("title"):
                continue
            duration = float(entry.get("duration") or 0.0)
            if duration < MIX_MIN_DURATION:
                continue  # solo mix lunghi
            entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
            if not entry_url:
                continue
            results.append(
                SearchResult(
                    platform="youtube",
                    url=entry_url,
                    title=str(entry["title"])[:300],
                    uploader=channel_name,
                    duration=duration,
                    thumbnail=_flat_thumb(entry),
                    canonical_id=compute_canonical_id("youtube", entry.get("id"), entry_url),
                )
            )
            if len(results) >= limit:
                break
        if not results:
            return SearchOutcome(
                error_kind="no_results",
                message=f"nessun mix (≥ {int(MIX_MIN_DURATION // 60)} min) sul canale {channel_id}",
            )
        return SearchOutcome(results=results)

    def _channel_mixcloud(self, username: str, limit: int) -> SearchOutcome:
        url = f"https://api.mixcloud.com/{username}/cloudcasts/?limit={limit}"
        resp = httpx.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            item_url = str(item.get("url") or "")
            if not item_url:
                continue
            duration = float(item.get("audio_length") or 0.0)
            if duration < MIX_MIN_DURATION:
                continue
            user = (item.get("user") or {}).get("name", "") if isinstance(item.get("user"), dict) else ""
            pictures = item.get("pictures") or {}
            results.append(
                SearchResult(
                    platform="mixcloud",
                    url=item_url,
                    title=str(item.get("name") or item_url)[:300],
                    uploader=str(user or username),
                    duration=duration,
                    thumbnail=str(pictures.get("medium") or ""),
                    canonical_id=compute_canonical_id("mixcloud", None, item_url),
                )
            )
        if not results:
            return SearchOutcome(
                error_kind="no_results",
                message=f"nessun mix (≥ {int(MIX_MIN_DURATION // 60)} min) su Mixcloud '{username}'",
            )
        return SearchOutcome(results=results[:limit])

    # ------------------------------------------------------------------
    # youtube / soundcloud via yt-dlp flat playlist
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
            results.append(
                SearchResult(
                    platform=platform,
                    url=entry_url,
                    title=str(entry["title"])[:300],
                    uploader=str(entry.get("uploader") or entry.get("channel") or entry.get("artist") or ""),
                    duration=float(entry.get("duration") or 0.0),
                    thumbnail=_flat_thumb(entry),
                    canonical_id=compute_canonical_id(platform, native_id, entry_url),
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


def _flat_thumb(entry: dict[str, Any]) -> str:
    if entry.get("thumbnail"):
        return str(entry["thumbnail"])
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
        return str(best.get("url") or "")
    return ""
