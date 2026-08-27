"""ResolverService — facciata lato API verso il processo worker.

Il server NON parla mai direttamente con yt-dlp: delega al processo separato
(spawn automatico all'avvio). Health-check ping/ok con degradazione a
"solo link" se il worker è giù (riserve Elena Rossi + Aiko Tanaka).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

from ..core.errors import (
    RateLimitedError,
    ResolveError,
    ResolverUnavailableError,
    ResolveTimeoutError,
    SearchError,
    SearchRateLimitedError,
    SearchUnsupportedError,
    SourceForbiddenError,
    UnsupportedPlatformError,
)
from ..core.schema import MediaObject, SearchResult, compute_canonical_id
from ..core.platforms import detect_platform

RESPONSE_TIMEOUT = 50.0
PING_TIMEOUT = 5.0

_ERROR_KIND_MAP: dict[str, type[ResolveError]] = {
    "unsupported": UnsupportedPlatformError,
    "source_forbidden": SourceForbiddenError,
    "timeout": ResolveTimeoutError,
    "ytdlp": ResolveError,
    "parse": ResolveError,
    "internal": ResolveError,
}


class ResolverService:
    """Gestisce il ciclo di vita del processo worker e il protocollo JSON-lines."""

    def __init__(self, db_path: str | None = None, autostart: bool = True) -> None:
        self.db_path = db_path or os.environ.get("PLAYER_DB_PATH")
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self._events: dict[int, threading.Event] = {}
        self._reader: threading.Thread | None = None
        self._next_id = 0
        self.resolver_version = "yt-dlp/unknown"
        if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            autostart = False
        if autostart:
            self.start()

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Avvia (o riavvia) il processo worker."""
        if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            env = dict(os.environ)
            if self.db_path:
                env["PLAYER_DB_PATH"] = self.db_path
            # stdout del worker in UTF-8 puro (su Windows il locale encoding
            # romperebbe il protocollo JSON-lines: 0x97 cp1252 ≠ UTF-8)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            # Il worker viene lanciato come `-m player_app.resolver.worker`:
            # la radice che CONTIENE il pacchetto deve essere in sys.path
            # (PYTHONPATH) e cwd — il fallimento dello spawn NON deve
            # bloccare il server (BrokenPipeError gestito sotto).
            package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "player_engine.resolver.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=package_root,
            )
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    def _read_loop(self) -> None:
        """Thread lettore: popola self._responses e sveglia gli eventi."""
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = response.get("id")
            if rid in self._events:
                self._responses[rid] = response
                self._events[rid].set()

    # ------------------------------------------------------------------
    def _request(self, payload: dict[str, Any], timeout: float = RESPONSE_TIMEOUT) -> dict[str, Any]:
        # Ambienti serverless (Vercel) o processi senza worker daemon attivo
        if os.environ.get("VERCEL") or (not self._proc or self._proc.poll() is not None):
            with self._lock:
                if not hasattr(self, "_inprocess_worker") or self._inprocess_worker is None:
                    from .worker import ResolverWorker
                    self._inprocess_worker = ResolverWorker(db_path=self.db_path)
            return self._inprocess_worker.handle(payload)

        with self._lock:
            self._next_id += 1
            rid = self._next_id
            payload["id"] = rid
            self._events[rid] = threading.Event()
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, AttributeError):
                self._events.pop(rid, None)
                with self._lock:
                    if not hasattr(self, "_inprocess_worker") or self._inprocess_worker is None:
                        from .worker import ResolverWorker
                        self._inprocess_worker = ResolverWorker(db_path=self.db_path)
                return self._inprocess_worker.handle(payload)

        try:
            if not self._events[rid].wait(timeout):
                with self._lock:
                    if not hasattr(self, "_inprocess_worker") or self._inprocess_worker is None:
                        from .worker import ResolverWorker
                        self._inprocess_worker = ResolverWorker(db_path=self.db_path)
                return self._inprocess_worker.handle(payload)
            return self._responses.pop(rid)
        finally:
            self._events.pop(rid, None)

    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """Health-check: ping al worker. False se giù o senza risposta."""
        try:
            response = self._request({"op": "ping"}, timeout=PING_TIMEOUT)
            ok = bool(response.get("ok"))
            if ok:
                self.resolver_version = response.get("resolver_version", self.resolver_version)
            return {"ok": ok, "resolver_version": self.resolver_version}
        except ResolveError:
            return {"ok": False, "resolver_version": self.resolver_version}

    def resolve(self, url: str, refresh: bool = False) -> MediaObject:
        """Risolve un URL. Degrada a 'solo link' se il resolver è giù
        (riserva Elena: health-check runtime con degradazione).
        refresh=True salta la cache (token stream scaduti)."""
        media, _ = self.resolve_full(url, refresh=refresh)
        return media

    def resolve_full(self, url: str, refresh: bool = False) -> tuple[MediaObject, list[MediaObject]]:
        """Risolve un URL e, per le raccolte (album), restituisce anche la
        tracklist completa (già in cache → play immediato)."""
        platform = detect_platform(url)
        if platform is None:
            raise UnsupportedPlatformError(url, "piattaforma non supportata")

        try:
            response = self._request({"op": "resolve", "url": url, "refresh": refresh})
        except ResolverUnavailableError as exc:
            # Degradazione: oggetto 'solo link' con diritto unknown → download bloccato
            return self._link_only(url, platform, str(exc)), []

        if response.get("ok"):
            media = MediaObject.model_validate(response["media"])
            tracks = [MediaObject.model_validate(t) for t in response.get("tracks", [])]
            return media, tracks

        error = response.get("error", {})
        kind = error.get("kind", "internal")
        if kind == "rate_limited":
            raise RateLimitedError(url, platform, retry_after=error.get("retry_after", 5.0))
        exc_cls = _ERROR_KIND_MAP.get(kind, ResolveError)
        raise exc_cls(url, error.get("message", "errore del resolver"))

    def search(self, platform: str, query: str) -> list[SearchResult]:
        """Ricerca su una piattaforma. Solleva errori tipizzati;
        se il resolver è giù solleva ResolverUnavailableError (degradazione
        esplicita, così la UI mostra il messaggio invece di una lista vuota
        silenziosa — stesso contratto di resolve_full)."""
        try:
            response = self._request({"op": "search", "platform": platform, "q": query})
        except ResolverUnavailableError:
            raise ResolverUnavailableError(platform, "processo Media Resolver non attivo")

        if response.get("ok"):
            return [SearchResult.model_validate(r) for r in response.get("results", [])]

        error = response.get("error", {})
        kind = error.get("kind", "internal")
        if kind == "rate_limited":
            raise SearchRateLimitedError(platform, error.get("retry_after", 5.0), query)
        if kind == "search_unsupported":
            raise SearchUnsupportedError(platform)
        raise SearchError(platform, error.get("message", "errore di ricerca"))

    def channel(self, platform: str, channel_id: str) -> list[SearchResult]:
        """Feed mix di un canale curato (solo set lunghi, filtro nel worker).
        Solleva errori tipizzati; se il resolver è giù solleva
        ResolverUnavailableError (stesso contratto di search)."""
        try:
            response = self._request({"op": "channel", "platform": platform, "channel_id": channel_id})
        except ResolverUnavailableError:
            raise ResolverUnavailableError(channel_id, "processo Media Resolver non attivo")

        if response.get("ok"):
            return [SearchResult.model_validate(r) for r in response.get("results", [])]

        error = response.get("error", {})
        kind = error.get("kind", "internal")
        if kind == "rate_limited":
            raise SearchRateLimitedError(platform, error.get("retry_after", 5.0), channel_id)
        if kind == "search_unsupported":
            raise SearchUnsupportedError(platform)
        raise SearchError(platform, error.get("message", "errore feed canale"))

    def album(self, url: str) -> tuple[MediaObject, list[MediaObject]]:
        """Tracklist completa di un album (meta + tracce già in cache)."""
        try:
            response = self._request({"op": "album", "url": url})
        except ResolverUnavailableError:
            raise ResolveError(url, "resolver non disponibile")

        if response.get("ok"):
            album = MediaObject.model_validate(response["album"])
            tracks = [MediaObject.model_validate(t) for t in response.get("tracks", [])]
            return album, tracks

        error = response.get("error", {})
        kind = error.get("kind", "internal")
        if kind == "rate_limited":
            raise RateLimitedError(url, error.get("message", ""),
                                   retry_after=error.get("retry_after", 5.0))
        raise ResolveError(url, error.get("message", "errore album"))

    def _link_only(self, url: str, platform: str, reason: str) -> MediaObject:
        """Media Object minimo 'solo link': nessuno stream, download bloccato."""
        from ..core.schema import Rights, RiskLevel, DownloadLicense, MediaType

        return MediaObject(
            canonical_id=compute_canonical_id(platform, None, url),
            platform=platform,
            source_url=url,
            title=url,
            media_type=MediaType.AUDIO if platform in ("bandcamp", "soundcloud", "mixcloud") else MediaType.VIDEO,
            rights=Rights(
                download_license=DownloadLicense.UNKNOWN,
                terms_violation_risk=RiskLevel.HIGH,
                license_note=f"Resolver non disponibile: {reason}",
            ),
            degraded=True,
            resolved_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            resolver_version=self.resolver_version,
        )

    def shutdown(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
                except Exception:
                    self._proc.kill()
            self._proc = None
