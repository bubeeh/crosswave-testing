"""Media Resolver worker — processo separato (riserva Elena Rossi).

Il worker vive in un processo OS dedicato: yt-dlp è un binario nativo che
cambia parser ogni settimana; se crasha, deve crashare fuori dal processo
principale (API/UI). Protocollo JSON-lines su stdin/stdout:

  richiesta : {"id": 1, "op": "resolve", "url": "..."}
  risposta  : {"id": 1, "ok": true,  "media": {...}}
            | {"id": 1, "ok": false, "error": {"kind": "...", "message": "...", "retry_after": 3.0}}
  ping      : {"id": 2, "op": "ping"} → {"id": 2, "ok": true, "resolver_version": "..."}

Variabili d'ambiente:
  PLAYER_YTDLP_BIN : binario yt-dlp (default "yt-dlp"; override nei test)
  PLAYER_DB_PATH   : database SQLite per rate limit + cache TTL 72h
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import (
    ResolveTimeoutError,
    SourceForbiddenError,
    UnsupportedPlatformError,
)
from ..core.platforms import detect_platform
from ..core.schema import MediaObject
from .cache import ResolutionCache
from .normalizer import Normalizer
from .rate_limit import RateLimiter

YTDLP_BIN = os.environ.get("PLAYER_YTDLP_BIN", "yt-dlp")
RESOLVE_TIMEOUT = 45.0
YTDLP_TIMEOUT = 40.0


def _ytdlp_cmd(args: list[str]) -> list[str]:
    """Comando yt-dlp: se il binario è uno script .py o non nel PATH, usa python -m yt_dlp."""
    if YTDLP_BIN.endswith(".py"):
        return [sys.executable, YTDLP_BIN, *args]
    if shutil.which(YTDLP_BIN):
        return [YTDLP_BIN, *args]
    return [sys.executable, "-m", "yt_dlp", *args]


@dataclass
class ResolveOutcome:
    media: MediaObject | None = None
    tracks: list[MediaObject] = field(default_factory=list)
    error_kind: str = ""
    message: str = ""
    retry_after: float = 0.0
    cache_hit: bool = False


class ResolverWorker:
    """Implementazione del worker: esegue yt-dlp, normalizza, rate-limita, cache."""

    def __init__(self, db_path: str | None = None) -> None:
        from ..storage.db import init_db
        from ..storage.repos import CacheRepo, RateLimitRepo, SearchCacheRepo

        self.db_path = db_path or os.environ.get("PLAYER_DB_PATH") or ":memory:"
        self._conn = init_db(self.db_path)
        self.rate = RateLimiter(RateLimitRepo(self._conn))
        self.cache = ResolutionCache(CacheRepo(self._conn))
        self.normalizer = Normalizer(resolver_version=self._resolver_version())

        from .search import Searcher

        self.searcher = Searcher(self._conn, rate_limiter=self.rate)

    @staticmethod
    def _resolver_version() -> str:
        try:
            out = subprocess.run(
                _ytdlp_cmd(["--version"]), capture_output=True, text=True, timeout=10
            )
            ver = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "unknown"
            return f"yt-dlp/{ver}"
        except Exception:
            return "yt-dlp/unknown"

    # ------------------------------------------------------------------
    def resolve(self, url: str, refresh: bool = False) -> ResolveOutcome:
        platform = detect_platform(url)
        if platform is None:
            return ResolveOutcome(error_kind="unsupported", message=f"URL non supportato: {url}")

        # 1) cache TTL 72h (saltata se refresh=True: i token degli stream
        #    diretti scadono prima del TTL, es. Bandcamp)
        if not refresh:
            cached = self._fetch_cache(url, platform)
            if cached is None:
                # id nativo non derivabile dall'URL (bandcamp/soundcloud usano id
                # numerici): si usa l'alias urleq:<url> salvato alla 1ª risoluzione
                alias_cid = self.cache.get_alias(url)
                if alias_cid:
                    cached = self.cache.get(alias_cid)
            if cached:
                return ResolveOutcome(media=cached, cache_hit=True)

        # 2) rate limit 1/5s per piattaforma
        gate = self.rate.check(platform)
        if not gate.allowed:
            return ResolveOutcome(
                error_kind="rate_limited",
                message=f"Sorgente occupata — riprovo tra {gate.retry_after:.0f}s",
                retry_after=gate.retry_after,
            )

        # 3) yt-dlp (subprocess) — il crash non tocca il processo principale.
        #    NB: niente --no-playlist: se l'URL è una raccolta (album), yt-dlp
        #    restituisce gli entries e la tracklist arriva in un colpo solo
        #    (niente doppia chiamata = niente doppio slot rate limit).
        raw = self._run_ytdlp(url)
        if isinstance(raw, ResolveOutcome):
            return raw

        self.rate.release(platform)
        resolved_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        media = self.normalizer.normalize(platform, raw, source_url=url, resolved_at=resolved_at)
        self.cache.put(media)
        # alias URL→canonical_id: l'id nativo di yt-dlp può non essere
        # derivabile dall'URL → lookup in cache pre-yt-dlp alle richieste successive
        self.cache.put_alias(url, media.canonical_id, media.resolved_at)

        # raccolta → normalizza anche le tracce (già in cache per il play immediato)
        tracks: list[MediaObject] = []
        if media.is_collection:
            for entry in raw.get("entries") or []:
                if not isinstance(entry, dict) or not entry.get("title"):
                    continue
                entry_url = str(entry.get("webpage_url") or entry.get("url") or url)
                track = self.normalizer.normalize(
                    platform, entry, source_url=entry_url, resolved_at=resolved_at
                )
                track.cache_hit = False
                tracks.append(track)
                self.cache.put(track)
            media.tags = media.tags or [f"album:{len(tracks)} tracce"]
        return ResolveOutcome(media=media, tracks=tracks)

    # ------------------------------------------------------------------
    def resolve_album(self, url: str) -> ResolveOutcome:
        """Estrae un album (playlist): meta + tracklist COMPLETA con stream.
        Una sola chiamata yt-dlp (senza --no-playlist) → ogni traccia viene
        normalizzata e messa in cache: play immediato senza N risoluzioni."""
        platform = detect_platform(url)
        if platform is None:
            return ResolveOutcome(error_kind="unsupported", message=f"URL non supportato: {url}")

        # 1) cache TTL 72h (album + tracklist) — stesso pattern di resolve():
        #    niente rate limit né yt-dlp se la raccolta è già in cache.
        #    Per le raccolte l'id nativo di yt-dlp può non coincidere con lo
        #    slug dell'URL: si usa anche l'alias urleq:<url> salvato al primo
        #    accesso (nessun modo di derivarlo pre-yt-dlp).
        cached = self._fetch_cache(url, platform)
        if cached is None:
            alias_cid = self.cache.get_alias(url)
            if alias_cid:
                cached = self.cache.get(alias_cid)
        if cached:
            tracklist = self.cache.get_tracklist(cached.canonical_id)
            if tracklist is not None:
                tracks = [MediaObject.model_validate(t) for t in tracklist]
                return ResolveOutcome(media=cached, tracks=tracks, cache_hit=True)
            # album in cache ma tracklist assente (cache di versione vecchia):
            # riesegui l'estrazione completa

        gate = self.rate.check(platform)
        if not gate.allowed:
            return ResolveOutcome(
                error_kind="rate_limited",
                message=f"Sorgente occupata — riprovo tra {gate.retry_after:.0f}s",
                retry_after=gate.retry_after,
            )

        try:
            proc = subprocess.run(
                _ytdlp_cmd(["-J", "--no-warnings", url]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=YTDLP_TIMEOUT + 30,
            )
        except subprocess.TimeoutExpired:
            return ResolveOutcome(error_kind="timeout", message=f"Timeout album: {url}")
        except FileNotFoundError:
            return ResolveOutcome(
                error_kind="resolver_unavailable",
                message=f"Binario yt-dlp non trovato ('{YTDLP_BIN}').",
            )
        if proc.returncode != 0:
            return self._error_from_ytdlp(proc.stderr, url)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ResolveOutcome(error_kind="parse", message=f"Output yt-dlp non valido per {url}")

        entries = data.get("entries") or []
        if not entries:
            return ResolveOutcome(
                error_kind="no_tracks",
                message=f"Nessuna traccia trovata per l'album: {url}",
            )

        self.rate.release(platform)
        resolved_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        album = self.normalizer.normalize(platform, data, source_url=url, resolved_at=resolved_at)
        album.cache_hit = False
        self.cache.put(album)

        tracks: list[MediaObject] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("title"):
                continue
            entry_url = str(entry.get("webpage_url") or entry.get("url") or url)
            track = self.normalizer.normalize(
                platform, entry, source_url=entry_url, resolved_at=resolved_at
            )
            track.cache_hit = False
            tracks.append(track)
            self.cache.put(track)

        # tracklist in cache (chiave derivata): il secondo accesso all'album
        # è istantaneo e completo, senza consumare il rate limit
        self.cache.put_tracklist(
            album.canonical_id,
            [t.model_dump(mode="json") for t in tracks],
            album.resolved_at,
        )
        # alias URL→canonical_id: l'id nativo di yt-dlp per un album può non
        # essere derivabile dall'URL (es. album:2921611913 vs /album/slug)
        self.cache.put_alias(url, album.canonical_id, album.resolved_at)
        return ResolveOutcome(media=album, tracks=tracks)

    def _fetch_cache(self, url: str, platform: str) -> MediaObject | None:
        """Cerca in cache per canonical_id derivato dall'URL (id nativo
        riconoscibile pre-yt-dlp: evita di consumare il rate limit)."""
        from ..core.platforms import native_id_from_url
        from ..core.schema import compute_canonical_id

        native_id = native_id_from_url(platform, url)
        if native_id is None:
            return None
        cid = compute_canonical_id(platform, native_id, url)
        cached = self.cache.get(cid)
        if cached:
            if platform == "soundcloud":
                dur = float(cached.duration or 0.0)
                is_preview_stream = any("preview" in str(s.url) for s in cached.streams) if cached.streams else False
                if dur <= 45 or is_preview_stream:
                    return None
        return cached

    def _run_ytdlp(self, url: str) -> dict[str, Any] | ResolveOutcome:
        raw_info = None

        # 1) Direct Python API in-process (fastest & Vercel compatible)
        try:
            import yt_dlp
            opts = {
                'extract_flat': False,
                'quiet': True,
                'no_warnings': True,
                'skip_download': True
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and isinstance(info, dict):
                    raw_info = info
        except Exception:
            pass

        # 2) Subprocess execution fallback
        if not raw_info:
            try:
                proc = subprocess.run(
                    _ytdlp_cmd(["-J", "--no-warnings", url]),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=YTDLP_TIMEOUT,
                )
                if proc.returncode == 0 and proc.stdout:
                    raw_info = json.loads(proc.stdout)
            except Exception:
                pass

        # Check SoundCloud 30s preview snippet or 404 fallback to YouTube full track
        is_soundcloud = "soundcloud.com" in url or (raw_info and raw_info.get("extractor_key") == "Soundcloud")
        if is_soundcloud:
            is_preview = False
            if raw_info:
                formats = raw_info.get("formats") or []
                is_preview_fmt = any("preview" in str(f.get("format_id", "")) for f in formats)
                duration = float(raw_info.get("duration") or 0.0)
                if raw_info.get("is_preview") or is_preview_fmt or (0 < duration <= 45 and not raw_info.get("entries")):
                    is_preview = True

            if is_preview or not raw_info:
                query = ""
                if raw_info:
                    title = raw_info.get("title") or ""
                    artist = raw_info.get("uploader") or raw_info.get("artist") or ""
                    query = f"{artist} {title}".strip()
                if not query:
                    parts = [p for p in url.rstrip("/").split("/") if p]
                    if len(parts) >= 2:
                        query = f"{parts[-2]} {parts[-1]}".replace("-", " ").replace("_", " ")

                if query:
                    try:
                        import yt_dlp
                        opts = {'extract_flat': 'in_playlist', 'quiet': True, 'no_warnings': True}
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            yt_search = ydl.extract_info(f"ytsearch1:{query}", download=False)
                            if yt_search and yt_search.get("entries"):
                                yt_entry = yt_search["entries"][0]
                                yt_id = yt_entry.get("id") or ""
                                yt_url = yt_entry.get("webpage_url") or yt_entry.get("url") or f"https://www.youtube.com/watch?v={yt_id}"
                                with yt_dlp.YoutubeDL({'extract_flat': False, 'quiet': True, 'no_warnings': True, 'skip_download': True}) as ydl_full:
                                    yt_full = ydl_full.extract_info(yt_url, download=False)
                                    if yt_full and isinstance(yt_full, dict):
                                        tags = yt_full.get("tags") or []
                                        if yt_id:
                                            tags.append(f"yt_fallback:{yt_id}")
                                        yt_full["tags"] = tags

                                        if raw_info:
                                            raw_info["formats"] = yt_full.get("formats")
                                            raw_info["url"] = yt_full.get("url")
                                            raw_info["duration"] = yt_full.get("duration") or raw_info.get("duration")
                                            raw_info["is_preview"] = False
                                            raw_info["tags"] = (raw_info.get("tags") or []) + [f"yt_fallback:{yt_id}"]
                                        else:
                                            raw_info = yt_full
                                            raw_info["webpage_url"] = url
                    except Exception:
                        pass

        if raw_info:
            return raw_info

        return ResolveOutcome(error_kind="ytdlp", message=f"Impossibile estrarre metadati per {url}")

    @staticmethod
    def _error_from_ytdlp(stderr: str, url: str) -> ResolveOutcome:
        err = stderr.lower()
        if "unsupported url" in err:
            return ResolveOutcome(error_kind="unsupported", message=f"URL non supportato: {url}")
        if "http error 403" in err or "http error 429" in err:
            return ResolveOutcome(
                error_kind="source_forbidden",
                message=f"La piattaforma ha rifiutato la richiesta: {stderr.strip()[:200]}",
            )
        if "private video" in err or "members only" in err:
            return ResolveOutcome(error_kind="source_forbidden", message=stderr.strip()[:200])
        return ResolveOutcome(
            error_kind="ytdlp", message=stderr.strip()[:300] or f"yt-dlp fallito per {url}"
        )

    # ------------------------------------------------------------------
    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatcher di una richiesta del protocollo JSON-lines."""
        rid = request.get("id")
        op = request.get("op")
        if op == "ping":
            return {"id": rid, "ok": True, "resolver_version": self._resolver_version()}
        if op == "search":
            outcome = self.searcher.search(request.get("platform", ""), request.get("q", ""))
            if outcome.results is not None:
                return {
                    "id": rid,
                    "ok": True,
                    "results": [r.model_dump(mode="json") for r in outcome.results],
                    "cache_hit": outcome.cache_hit,
                }
            error: dict[str, Any] = {"kind": outcome.error_kind, "message": outcome.message}
            if outcome.retry_after:
                error["retry_after"] = round(outcome.retry_after, 1)
            return {"id": rid, "ok": False, "error": error}
        if op == "channel":
            outcome = self.searcher.fetch_channel(
                request.get("platform", ""), request.get("channel_id", ""),
                limit=int(request.get("limit") or 20),
            )
            if outcome.results is not None:
                return {
                    "id": rid,
                    "ok": True,
                    "results": [r.model_dump(mode="json") for r in outcome.results],
                    "cache_hit": outcome.cache_hit,
                }
            error = {"kind": outcome.error_kind, "message": outcome.message}
            if outcome.retry_after:
                error["retry_after"] = round(outcome.retry_after, 1)
            return {"id": rid, "ok": False, "error": error}
        if op == "album":
            outcome = self.resolve_album(request.get("url", ""))
            if outcome.media is not None:
                return {
                    "id": rid,
                    "ok": True,
                    "album": outcome.media.model_dump(mode="json"),
                    "tracks": [t.model_dump(mode="json") for t in outcome.tracks],
                }
            error: dict[str, Any] = {"kind": outcome.error_kind, "message": outcome.message}
            if outcome.retry_after:
                error["retry_after"] = round(outcome.retry_after, 1)
            return {"id": rid, "ok": False, "error": error}
        if op == "resolve":
            outcome = self.resolve(request.get("url", ""), refresh=bool(request.get("refresh")))
            if outcome.media is not None:
                media = outcome.media.model_copy(
                    update={"cache_hit": outcome.cache_hit}
                )
                response: dict[str, Any] = {
                    "id": rid, "ok": True, "media": media.model_dump(mode="json")
                }
                if outcome.tracks:
                    response["tracks"] = [t.model_dump(mode="json") for t in outcome.tracks]
                return response
            error: dict[str, Any] = {"kind": outcome.error_kind, "message": outcome.message}
            if outcome.retry_after:
                error["retry_after"] = round(outcome.retry_after, 1)
            return {"id": rid, "ok": False, "error": error}
        return {"id": rid, "ok": False, "error": {"kind": "bad_op", "message": f"op sconosciuta: {op}"}}


def _main() -> None:
    """Loop principale del processo: legge JSON-lines da stdin, scrive su stdout."""
    worker = ResolverWorker()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = worker.handle(request)
        except Exception as exc:  # mai morire: rispondi con errore
            response = {"id": None, "ok": False, "error": {"kind": "internal", "message": str(exc)}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _main()
