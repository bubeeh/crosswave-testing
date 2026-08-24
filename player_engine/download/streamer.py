"""StreamCache: riproduzione affidabile scaricando-on-demand.

Perché: le URL dirette di googlevideo (senza cookie) vengono throttlate dopo
~5 richieste Range (403) — il proxy URL-by-URL è inaffidabile. yt-dlp invece
scarica senza problemi (gestisce throttling/signature). Quindi:

  1. al primo play, yt-dlp scarica l'audio (bestaudio, formato nativo)
     in stream_cache/{canonical_id}.{ext}
  2. /api/stream serve il FILE LOCALE con Range header (crescita progressiva,
     zero dipendenze esterne, pausa/ripresa su mobile — riserva Aiko)

È streaming personale (attività legittima del piano): nessun gate licenza
(quello resta per i DOWNLOAD espliciti, che passano dal DownloadWorker con
watermark). Log di conformità: stream.start / stream.done.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core.events import DownloadProgress
from ..core.schema import MediaObject
from ..storage.repos import ComplianceRepo


YTDLP_BIN_ENV = "PLAYER_YTDLP_BIN"
_FS_SAFE_RE = None


def _fs_safe(media_id: str) -> str:
    """Chiave file CORTA dal canonical_id. I canonical_id sono
    'sha256:<64hex>' (~71 caratteri): annidati nelle directory di lavoro
    superano MAX_PATH di Windows (260) → download fallito → hang.
    Usiamo solo i primi 16 hex: deterministica, sufficiente, collusioni
    praticamente impossibili."""
    import re

    raw = media_id.split(":")[-1] if ":" in media_id else media_id
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)[:16]



def _ytdlp_bin() -> str:
    return os.environ.get(YTDLP_BIN_ENV, "yt-dlp")


def _ytdlp_cmd(args: list[str]) -> list[str]:
    bin_ = _ytdlp_bin()
    if bin_.endswith(".py"):
        return [sys.executable, bin_, *args]
    return [bin_, *args]


class StreamCache:
    """Cache audio per la riproduzione: un download yt-dlp per media, dedup
    su richieste concorrenti, file servito via Range mentre cresce."""

    def __init__(self, cache_dir: str | Path, conn: sqlite3.Connection) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._conn = conn
        self._compliance = ComplianceRepo(conn)
        self._lock = threading.Lock()
        self._jobs: set[str] = set()

    def wait_for_complete(self, media_id: str, timeout: float = 300.0) -> Path | None:
        """Attende il file COMPLETO (fuori dalla work dir .part). Gli mp4
        android hanno moov in coda: un file in crescita non è decodificabile,
        quindi si serve solo a download finito (per i contenuti lunghi vale
        il cap --download-sections)."""
        base = _fs_safe(media_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for p in self.cache_dir.glob(f"{base}.*"):
                if p.is_file() and p.stat().st_size > 0:
                    return p
            time.sleep(0.5)
        # fallback: file in crescita (migliore del nulla)
        return self.path_for(media_id)

    # ------------------------------------------------------------------
    def path_for(self, media_id: str) -> Path | None:
        """File già scaricato per questo media (qualunque estensione), o il
        file in crescita nella work dir (download ancora in corso)."""
        for p in self.cache_dir.glob(f"{_fs_safe(media_id)}.*"):
            if p.is_file():
                return p
        work = self.cache_dir / f"{_fs_safe(media_id)}.part"
        if work.exists():
            for p in work.glob("*"):
                if p.is_file():
                    return p
        return None

    def ensure_job(self, media: MediaObject) -> Path | None:
        """Avvia il download se serve; ritorna il path (anche non ancora
        completo). None solo se il download non è partito."""
        existing = self.path_for(media.canonical_id)
        if existing:
            return existing
        with self._lock:
            if media.canonical_id in self._jobs:
                return self.cache_dir / f"{_fs_safe(media.canonical_id)}.part"
            self._jobs.add(media.canonical_id)
            self._compliance.log_simple(
                "stream.start", media.source_url, media.platform,
                media.rights.download_license.value, "playback on-demand",
            )
            thread = threading.Thread(
                target=self._download, args=(media,), daemon=True
            )
            thread.start()
            return self.cache_dir / f"{_fs_safe(media.canonical_id)}.part"

    def _sections_args(self, media: MediaObject) -> list[str]:
        """Cap sui contenuti molto lunghi (radio): scarica solo i primi N
        secondi, così il file è COMPLETO e riproducibile subito (gli mp4
        android hanno moov in coda: un file in crescita non è decodificabile).
        Configurabile con PLAYER_STREAM_CAP_SECONDS (default 1 ora)."""
        import os as _os

        cap = int(_os.environ.get("PLAYER_STREAM_CAP_SECONDS", "3600"))
        if media.duration > 0 and media.duration > cap:
            return ["--download-sections", f"*0-{cap}"]
        return []

    # ------------------------------------------------------------------
    def _download(self, media: MediaObject) -> None:
        try:
            safe = _fs_safe(media.canonical_id)
            work = self.cache_dir / f"{safe}.part"
            work.mkdir(parents=True, exist_ok=True)
            cmd = _ytdlp_cmd([
                # muxed ≤720p (h264+aac, riproducibile sia da <audio> che da
                # <video>); il client android fornisce muxed senza cookie.
                "-f", "b[height<=720]/best",
                "--no-playlist", "--no-warnings",
                # Le URL del client default (tv) vengono throttlate con 403:
                # il client android fornisce URL scaricabili senza cookie
                # (verificato: web/ios falliscono su molti video).
                "--extractor-args", "youtube:player_client=android",
                *self._sections_args(media),
                "-o", str(work / f"{safe}.%(ext)s"),
                media.source_url,
            ])
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600,
            )
            if proc.returncode != 0:
                self._compliance.log_simple(
                    "stream.fail", media.source_url, media.platform, "", proc.stderr[:300],
                )
                return
            # sposta il file scaricato nella cache finale
            for p in work.iterdir():
                if p.is_file():
                    final = self.cache_dir / p.name
                    if final.exists():
                        final.unlink()
                    shutil.move(str(p), str(final))
                    break
            self._compliance.log_simple(
                "stream.done", media.source_url, media.platform,
                media.rights.download_license.value, "audio pronto",
            )
        finally:
            with self._lock:
                self._jobs.discard(media.canonical_id)
            try:
                shutil.rmtree(work, ignore_errors=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def wait_for_bytes(self, media_id: str, timeout: float = 15.0) -> Path | None:
        """Attende che il file locale abbia almeno qualche byte."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            path = self.path_for(media_id)
            if path and path.stat().st_size > 0:
                return path
            # anche il file .part (download in corso) può essere servito? No:
            # yt-dlp scrive nel work dir; il file finale appare al termine.
            time.sleep(0.3)
        return self.path_for(media_id)


# --------------------------------------------------------------------------
# Servizio file locale con Range header
# --------------------------------------------------------------------------
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def serve_file_range(path: Path, range_header: str):
    """Ritorna (status, headers, body-chunks-iterable) per il file locale."""
    size = path.stat().st_size
    if not range_header:
        return 200, {"Content-Type": _mime(path), "Content-Length": str(size), "Accept-Ranges": "bytes"}, _read_chunks(path, 0, size - 1)
    m = _RANGE_RE.search(range_header)
    if not m:
        return 416, {"Content-Range": f"bytes */{size}"}, []
    start = int(m.group(1)) if m.group(1) else 0
    end = int(m.group(2)) if m.group(2) else size - 1
    if start >= size:
        return 416, {"Content-Range": f"bytes */{size}"}, []
    end = min(end, size - 1)
    length = end - start + 1
    headers = {
        "Content-Type": _mime(path),
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
    }
    return 206, headers, _read_chunks(path, start, end)


def _read_chunks(path: Path, start: int, end: int, chunk: int = 256 * 1024):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    # NB: gli mp4 scaricati col client android sono MUXED (h264+aac): come
    # audio/mp4 Chrome tenta di decodificare i pacchetti video come audio →
    # PIPELINE_ERROR_DECODE. video/mp4 è gestito anche da un <audio>.
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
    }.get(ext, "application/octet-stream")
