"""API del player cross-source (contratto Fase 2 del piano).

Endpoint principali:
  POST /api/resolve                → risolvi URL in Media Object
  GET  /api/stream/{media_id}      → proxy con Range header
  POST /api/download               → accoda download (gate licenza)
  WS   /ws/downloads               → progresso download in tempo reale
  GET  /api/home                   → raccomandazioni precomputate
  POST /api/home/play              → registra ascolto (→ raccomandazioni)
  POST /api/home/forget_all        → "Dimentica tutto"
  GET  /api/compliance/export      → log conformità 24 mesi (esportabile)
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core.errors import (
    LicenseBlockedError,
    PlayerError,
    RateLimitedError,
    ResolveError,
    ResolverUnavailableError,
    SearchError,
    SearchRateLimitedError,
    StreamNotFoundError,
)
from ..core.events import DownloadProgress
from ..core.platforms import labels
from ..core.schema import MediaObject
from ..download.streamer import StreamCache, serve_file_range
from ..download.worker import DownloadWorker
from ..recommend.worker import RecommendationEngine
from ..resolver.service import ResolverService
from ..storage.db import init_db
from ..storage.repos import (
    CacheRepo,
    ComplianceRepo,
    DownloadsRepo,
    HistoryRepo,
    LibraryRepo,
    SettingsRepo,
)

DEFAULT_DB = Path(os.environ.get("PLAYER_DB_PATH", "player_data/player.db"))
DEFAULT_DOWNLOADS = Path(os.environ.get("PLAYER_DOWNLOADS_DIR", "player_data/downloads"))


# --------------------------------------------------------------------------
# Schemi richiesta
# --------------------------------------------------------------------------
class ResolveRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    media_id: str
    priority: int = 5


class QueueItem(BaseModel):
    media_id: str


class QueueRequest(BaseModel):
    items: list[QueueItem]
    current: str = ""


class PlayRequest(BaseModel):
    media_id: str
    play_seconds: float = 0.0


class PlaylistCreate(BaseModel):
    name: str


class SettingsUpdate(BaseModel):
    value: str


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
class Services:
    """Contenitore dei servizi condivisi (iniettabile nei test)."""

    def __init__(self, db_path: str | Path, downloads_dir: str | Path) -> None:
        self.conn: sqlite3.Connection = init_db(db_path)
        self.cache = CacheRepo(self.conn)
        self.library = LibraryRepo(self.conn)
        self.settings = SettingsRepo(self.conn)
        self.history = HistoryRepo(self.conn)
        self.compliance = ComplianceRepo(self.conn)
        self.downloads = DownloadsRepo(self.conn)
        self.recommend = RecommendationEngine(self.conn)
        self.resolver = ResolverService(db_path=str(db_path))
        self.download_worker = DownloadWorker(self.conn, downloads_dir)
        self.stream_cache = StreamCache(Path(downloads_dir) / "stream_cache", self.conn)
        self._ws_clients: set[WebSocket] = set()

    def broadcast_download(self, progress: DownloadProgress) -> None:
        import asyncio

        payload = progress.to_dict()
        for ws in list(self._ws_clients):
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda w=ws, p=payload: asyncio.create_task(w.send_json(p)), ws
                )
            except Exception:
                pass

    def close(self) -> None:
        try:
            self.resolver.shutdown()
        finally:
            self.conn.close()


def create_app(services: Services | None = None, db_path: str | Path = DEFAULT_DB,
               downloads_dir: str | Path = DEFAULT_DOWNLOADS) -> FastAPI:
    svc = services or Services(db_path, downloads_dir)
    if svc.download_worker and svc.download_worker not in getattr(svc, "_subscribed", ()):
        svc.download_worker.subscribe(svc.broadcast_download)
        svc._subscribed = (svc.download_worker,)

    app = FastAPI(title="Player Cross-Source", version="0.1.0")
    app.state.services = svc

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # app locale: nessuna chiamata a server terzi
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Platforms & health
    # ------------------------------------------------------------------
    @app.get("/api/platforms")
    def api_platforms() -> dict[str, Any]:
        return {"platforms": labels()}

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        health = svc.resolver.health()
        return {
            **health,
            "db": "ok",
            "downloads_pending": svc.downloads.pending_count(),
            "compliance_entries": svc.compliance.count(),
        }

    # ------------------------------------------------------------------
    # Resolve
    # ------------------------------------------------------------------
    @app.post("/api/resolve")
    def api_resolve(req: ResolveRequest) -> dict[str, Any]:
        url = req.url.strip()
        if not url:
            raise HTTPException(422, "url vuoto")
        try:
            media, tracks = svc.resolver.resolve_full(url)
        except RateLimitedError as exc:
            # Rate limiting visibile (riserva Astrid): la UI mostra il retry
            raise HTTPException(429, detail={
                "error": "rate_limited",
                "message": f"Sorgente occupata — riprovo tra {exc.retry_after:.0f}s",
                "retry_after": exc.retry_after,
                "platform": exc.platform,
            })
        except ResolveError as exc:
            svc.compliance.log_simple(
                "resolve.fail", url, "", "", str(exc)
            )
            raise HTTPException(422, detail={"error": "resolve_failed", "message": str(exc)})

        svc.compliance.log_simple(
            "resolve.ok", media.source_url, media.platform,
            media.rights.download_license.value,
            f"degraded={media.degraded} streams={len(media.streams)} cache_hit={media.cache_hit}"
            + (f" tracks={len(tracks)}" if tracks else ""),
        )
        payload = media.model_dump(mode="json")
        if tracks:
            payload["tracks"] = [t.model_dump(mode="json") for t in tracks]
        return payload

    # ------------------------------------------------------------------
    # Ricerca (link leggeri; risoluzione al click — riserva Astrid)
    # ------------------------------------------------------------------
    from ..resolver.search import SEARCHABLE_PLATFORMS

    @app.get("/api/search")
    async def api_search(q: str = "", platform: str = "all") -> dict[str, Any]:
        query = q.strip()
        if not query:
            raise HTTPException(422, "query vuota")
        if platform == "all":
            targets = list(SEARCHABLE_PLATFORMS)
        elif platform in SEARCHABLE_PLATFORMS:
            targets = [platform]
        else:
            raise HTTPException(422, detail={
                "error": "search_unsupported",
                "message": f"ricerca non supportata per la piattaforma '{platform}'",
            })

        import asyncio

        async def _search_one(p: str):
            """Ricerca su una piattaforma: in thread separato, errori per-piattaforma.
            (modello ThreadPoolExecutor di CrossWave — la coda non si blocca)."""
            try:
                results = await asyncio.to_thread(svc.resolver.search, p, query)
                return p, {"results": [r.model_dump(mode="json") for r in results], "error": None}
            except SearchRateLimitedError as exc:
                entry = {
                    "results": [], "error": "rate_limited",
                    "retry_after": exc.retry_after,
                    "message": f"Sorgente occupata — riprovo tra {exc.retry_after:.0f}s",
                }
                if platform != "all":
                    raise HTTPException(429, detail={
                        "error": "rate_limited",
                        "message": entry["message"],
                        "retry_after": exc.retry_after,
                        "platform": p,
                    })
                return p, entry
            except (SearchError, ResolverUnavailableError) as exc:
                return p, {"results": [], "error": "search_failed", "message": str(exc)}

        outs = await asyncio.gather(*(_search_one(p) for p in targets))
        return {"query": query, "platform": platform, "platforms": dict(outs)}

    @app.get("/api/media/{media_id}")
    def api_media(media_id: str) -> dict[str, Any]:
        media = svc.cache.get(media_id)
        if media is None:
            # Fallback: cerca nella libreria locale
            for fav in svc.library.list_favorites():
                if fav.canonical_id == media_id:
                    media = fav
                    break
        if media is None:
            raise HTTPException(404, "media non trovato")
        return media.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Album: tracklist completa (play immediato, tracce già in cache)
    # ------------------------------------------------------------------
    @app.get("/api/album/{media_id}")
    def api_album(media_id: str) -> dict[str, Any]:
        media = svc.cache.get(media_id)
        if media is None or not media.is_collection:
            raise HTTPException(404, detail={"error": "not_an_album", "message": "Media non è una raccolta."})
        try:
            album, tracks = svc.resolver.album(media.source_url)
        except RateLimitedError as exc:
            raise HTTPException(429, detail={
                "error": "rate_limited",
                "message": f"Sorgente occupata — riprovo tra {exc.retry_after:.0f}s",
                "retry_after": exc.retry_after,
                "platform": media.platform,
            })
        except ResolveError as exc:
            raise HTTPException(422, detail={"error": "album_failed", "message": str(exc)})
        svc.cache.set(album)
        for t in tracks:
            svc.cache.set(t)
        svc.compliance.log_simple(
            "album.open", album.source_url, album.platform,
            album.rights.download_license.value, f"{len(tracks)} tracce",
        )
        return {
            "album": album.model_dump(mode="json"),
            "tracks": [t.model_dump(mode="json") for t in tracks],
        }

    # ------------------------------------------------------------------
    # Stream con Range header (riserva Aiko: mai presigned URL)
    # ------------------------------------------------------------------
    # Strategia: scarica-on-demand + file locale. Le URL dirette di googlevideo
    # senza cookie vengono throttlate dopo ~5 Range (403): il proxy URL-by-URL è
    # inaffidabile. yt-dlp scarica senza problemi; /api/stream serve il file
    # locale con Range header (crescita progressiva, pausa/ripresa mobile).
    @app.get("/api/stream/{media_id}")
    async def api_stream(media_id: str, prefer_audio: bool = False,
                         request: Request = None):
        import asyncio

        from fastapi.responses import StreamingResponse

        media = svc.cache.get(media_id)
        if media is None:
            raise HTTPException(404, detail={
                "error": "solo_link",
                "message": "Media non risolto: cerca/incolla prima il contenuto.",
            })

        # avvia (o riusa) il download on-demand dell'audio
        path = await asyncio.to_thread(svc.stream_cache.ensure_job, media)
        if path is None:
            raise HTTPException(503, "download on-demand non avviato")

        # attende il file COMPLETO (moov degli mp4 android è in coda: un file
        # in crescita non è decodificabile — per le radio vale il cap)
        path = await asyncio.to_thread(svc.stream_cache.wait_for_complete, media.canonical_id, 300.0)
        if path is None or path.stat().st_size == 0:
            raise HTTPException(503, "sorgente non ancora disponibile, riprova")

        range_header = (request.headers.get("range") if request.headers else "") or ""

        def _serve():
            # se la richiesta supera la fine del file ancora in crescita,
            # attendi un po' (il download procede) e riprova
            for _ in range(30):
                status, headers, _ = serve_file_range(path, range_header)
                if status != 416 or svc.stream_cache.path_for(media_id) is None:
                    break
                time.sleep(0.5)
            status, headers, chunks = serve_file_range(path, range_header)
            return status, headers, chunks

        status, headers, chunks = await asyncio.to_thread(_serve)
        if status == 416:
            raise HTTPException(416, detail={"error": "range_not_satisfiable"})
        return StreamingResponse(
            chunks,
            status_code=status,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Download (endpoint + WebSocket progress)
    # ------------------------------------------------------------------
    @app.post("/api/download")
    def api_download(req: DownloadRequest) -> dict[str, Any]:
        media = svc.cache.get(req.media_id)
        if media is None:
            raise HTTPException(404, "media non trovato (risolvilo prima)")
        progress = svc.download_worker.enqueue(media, priority=req.priority)
        if progress.status == "blocked":
            raise HTTPException(403, detail={
                "error": "download_blocked",
                "message": progress.error or "download non consentito (licenza/termini)",
            })
        return progress.to_dict()

    @app.get("/api/downloads")
    def api_downloads(status: str | None = None) -> list[dict[str, Any]]:
        return svc.downloads.list_all(status)

    @app.websocket("/ws/downloads")
    async def ws_downloads(websocket: WebSocket) -> None:
        await websocket.accept()
        svc._ws_clients.add(websocket)
        # Stato iniziale dei download in corso
        for item in svc.downloads.list_all():
            await websocket.send_json({
                "download_id": item["id"],
                "media_id": item["media_id"],
                "status": item["status"],
                "percent": item["percent"],
                "path": item["path"],
                "error": item["error"],
            })
        try:
            while True:
                await websocket.receive_text()  # keepalive ping
        except WebSocketDisconnect:
            svc._ws_clients.discard(websocket)

    # ------------------------------------------------------------------
    # Home: raccomandazioni + cronologia aggregata + "Dimentica tutto"
    # ------------------------------------------------------------------
    @app.get("/api/home")
    def api_home() -> dict[str, Any]:
        return {
            "recommendations": svc.recommend.home(),
            "history_aggregates": svc.history.aggregates(limit=15),
            "platforms": labels(),
            "user_hash": svc.settings.get("user_hash", ""),
            "onboarding_done": svc.settings.get("onboarding_done", "0") == "1",
        }

    @app.post("/api/home/play")
    def api_home_play(req: PlayRequest) -> dict[str, Any]:
        media = svc.cache.get(req.media_id)
        if media is None:
            raise HTTPException(404, "media non trovato")
        svc.recommend.record_play(media, req.play_seconds)
        svc.compliance.log_simple(
            "history.play", media.source_url, media.platform,
            media.rights.download_license.value, f"{req.play_seconds:.0f}s",
        )
        return {"ok": True}

    @app.post("/api/home/forget_all")
    def api_forget_all() -> dict[str, Any]:
        """'Dimentica tutto': svuota cronologia grezza, aggregati e raccomandazioni."""
        svc.history.forget_all()
        svc.compliance.log_simple(
            "history.forget_all", "", "", "",
            "cronologia cancellata su richiesta dell'utente",
        )
        return {"ok": True, "message": "Cronologia cancellata. Le raccomandazioni ripartono da zero."}

    # ------------------------------------------------------------------
    # Cronologia aggregata (mai grezza — riserva privacy)
    # ------------------------------------------------------------------
    @app.get("/api/history")
    def api_history() -> dict[str, Any]:
        return {"aggregates": svc.history.aggregates(limit=100)}

    # ------------------------------------------------------------------
    # Libreria: preferiti, playlist, coda
    # ------------------------------------------------------------------
    @app.post("/api/favorites")
    def api_favorite_add(req: QueueItem) -> dict[str, Any]:
        media = _require_media(svc, req.media_id)
        svc.library.add_favorite(media)
        return {"ok": True}

    @app.get("/api/favorites")
    def api_favorites() -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in svc.library.list_favorites()]

    @app.delete("/api/favorites/{media_id}")
    def api_favorite_del(media_id: str) -> dict[str, Any]:
        svc.library.remove_favorite(media_id)
        return {"ok": True}

    # --- Watch Later (Guarda dopo) ---
    @app.post("/api/watch_later")
    def api_watch_later_add(req: QueueItem) -> dict[str, Any]:
        media = _require_media(svc, req.media_id)
        svc.library.add_watch_later(media)
        return {"ok": True}

    @app.get("/api/watch_later")
    def api_watch_later() -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in svc.library.list_watch_later()]

    @app.delete("/api/watch_later/{media_id}")
    def api_watch_later_del(media_id: str) -> dict[str, Any]:
        svc.library.remove_watch_later(media_id)
        return {"ok": True}

    @app.post("/api/playlists")
    def api_playlist_create(req: PlaylistCreate) -> dict[str, Any]:
        if not req.name.strip():
            raise HTTPException(422, "nome playlist vuoto")
        pid = svc.library.create_playlist(req.name.strip())
        return {"id": pid, "name": req.name.strip()}

    @app.get("/api/playlists")
    def api_playlists() -> list[dict[str, Any]]:
        return svc.library.list_playlists()

    @app.delete("/api/playlists/{playlist_id}")
    def api_playlist_del(playlist_id: int) -> dict[str, Any]:
        svc.library.delete_playlist(playlist_id)
        return {"ok": True}

    @app.post("/api/playlists/{playlist_id}/items")
    def api_playlist_add(playlist_id: int, req: QueueItem) -> dict[str, Any]:
        media = _require_media(svc, req.media_id)
        svc.library.add_to_playlist(playlist_id, media)
        return {"ok": True}

    @app.get("/api/playlists/{playlist_id}/items")
    def api_playlist_items(playlist_id: int) -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in svc.library.list_playlist_items(playlist_id)]

    @app.get("/api/queue")
    def api_queue() -> dict[str, Any]:
        items = svc.library.get_queue()
        return {
            "items": [{"media_id": i["media_id"], "is_current": bool(i["is_current"])}
                      for i in items],
            "media": [i["media"].model_dump(mode="json") for i in items],
        }

    @app.put("/api/queue")
    def api_queue_put(req: QueueRequest) -> dict[str, Any]:
        media_items = []
        for item in req.items:
            media = _require_media(svc, item.media_id)
            media_items.append(media)
        svc.library.replace_queue(media_items, current=req.current)
        return {"ok": True}

    @app.post("/api/queue/current")
    def api_queue_current(req: QueueItem) -> dict[str, Any]:
        svc.library.set_current(req.media_id)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Conformità: export 24 mesi (esportabile, non prunabile dalla UI)
    # ------------------------------------------------------------------
    @app.get("/api/compliance/export")
    def api_compliance_export(since: str | None = None) -> dict[str, Any]:
        entries = svc.compliance.export(since)
        svc.compliance.log_simple(
            "compliance.export", "", "", "", f"{len(entries)} righe esportate"
        )
        return {
            "schema": "player-compliance-log/v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "retention_days": 730,
            "entries": entries,
        }

    # ------------------------------------------------------------------
    # Onboarding (3 passi) + impostazioni
    # ------------------------------------------------------------------
    @app.get("/api/onboarding")
    def api_onboarding() -> dict[str, Any]:
        return {
            "done": svc.settings.get("onboarding_done", "0") == "1",
            "steps": [
                {"key": "connect", "title": "Collega piattaforme",
                 "done": True},
                {"key": "import", "title": "Importa preferiti",
                 "done": svc.settings.get("onboarding_import", "0") == "1"},
                {"key": "home", "title": "Home popolata",
                 "done": bool(svc.recommend.home(limit=1))},
            ],
        }

    @app.post("/api/onboarding/complete")
    def api_onboarding_complete() -> dict[str, Any]:
        svc.settings.set("onboarding_done", "1")
        return {"ok": True}

    @app.get("/api/settings")
    def api_settings() -> dict[str, str]:
        return {key: svc.settings.get(key) for key in ("user_hash", "onboarding_done")}

    @app.post("/api/settings/{key}")
    def api_settings_set(key: str, req: SettingsUpdate) -> dict[str, Any]:
        svc.settings.set(key, req.value)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Frontend statico (web/dist) — se presente, `player-app serve` serve tutto
    # ------------------------------------------------------------------
    from fastapi.staticfiles import StaticFiles

    web_dist = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        svc.close()

    app.router.lifespan_context = _lifespan

    return app


def _require_media(svc: Services, media_id: str) -> MediaObject:
    media = svc.cache.get(media_id)
    if media is not None:
        return media
    for fav in svc.library.list_favorites():
        if fav.canonical_id == media_id:
            return fav
    for item in svc.library.get_queue():
        if item["media"].canonical_id == media_id:
            return item["media"]
    raise HTTPException(404, f"media non trovato: {media_id}")
