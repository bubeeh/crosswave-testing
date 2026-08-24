"""DownloadWorker con scheduler a priorità (riserva Lucas Meyer).

L'utente avvia 3 download e guarda 4K senza jank: il worker gira in un
thread dedicato, i download sono in coda SQLite ordinata per priorità
(anti-starvation FIFO a parità di priorità) e il progresso è trasmesso
via callback (→ WebSocket nell'API).

Pipeline per ogni download (Fase 2/3 del piano):
  1. gate licenza: bloccato se `rights.download_license` è UNKNOWN o
     `terms_violation_risk == high` (condizione di rilascio non negoziabile)
  2. yt-dlp → audio (bestaudio) + ffmpeg loudnorm (normalizzazione nel
     pipeline resolver, zero CPU contention col decode video — riserva Aiko)
  3. watermark ID3 (hash utente, timestamp, URL sorgente)
  4. spostamento nella cartella download dell'utente
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
import uuid
from pathlib import Path
from typing import Callable

from ..core.events import DownloadProgress
from ..core.errors import DownloadFailedError, LicenseBlockedError
from ..core.schema import DownloadLicense, MediaObject, RiskLevel
from ..storage.db import loads, transaction
from ..storage.repos import ComplianceRepo, DownloadsRepo, SettingsRepo
from .watermark import apply_watermark

YTDLP_BIN = os.environ.get("PLAYER_YTDLP_BIN", "yt-dlp")
ProgressCallback = Callable[[DownloadProgress], None]


def _ytdlp_bin() -> str:
    """Binario yt-dlp letto a runtime (non all'import: i test lo cambiano
    per-test via env)."""
    return os.environ.get("PLAYER_YTDLP_BIN", "yt-dlp")


def _ytdlp_cmd(args: list[str]) -> list[str]:
    """Comando yt-dlp: se il binario è uno script .py, invocalo con il python
    corrente (necessario per i fake nei test)."""
    bin_ = _ytdlp_bin()
    if bin_.endswith(".py"):
        return [sys.executable, bin_, *args]
    return [bin_, *args]


# `[download]  45.2% of 12.34MiB at 1.2MiB/s ETA 00:05`
_PROGRESS_RE = re.compile(
    r"\[download\]\s+([\d.]+)%\s+of\s+~?([\d.]+)(\w+).*?at\s+([\d.]+)(\w+)/s"
    r"(?:\s+ETA\s+(\d+):(\d+))?"
)


class DownloadWorker:
    """Scheduler a priorità: un thread unico consuma la coda SQLite."""

    def __init__(self, conn: sqlite3.Connection, downloads_dir: str | Path,
                 worker_dir: str | Path | None = None, auto_start: bool = True) -> None:
        self._conn = conn
        self._repo = DownloadsRepo(conn)
        self._compliance = ComplianceRepo(conn)
        self._settings = SettingsRepo(conn)
        self.auto_start = auto_start
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.worker_dir = Path(worker_dir or self.downloads_dir / ".work")
        self.worker_dir.mkdir(parents=True, exist_ok=True)
        self._listeners: list[ProgressCallback] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def subscribe(self, cb: ProgressCallback) -> None:
        self._listeners.append(cb)

    def _emit(self, progress: DownloadProgress) -> None:
        self._repo.update(progress)
        for cb in self._listeners:
            try:
                cb(progress)
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    def enqueue(self, media: MediaObject, priority: int = 5) -> DownloadProgress:
        """Aggiunge un download alla coda (con gate licenza immediato).

        Gate (condizione di rilascio non negoziabile): consentito solo se
        `rights.download_license` è popolato E rischio non alto.
        """
        allowed = self._license_gate(media)
        if allowed:
            did = self._repo.create(media, priority)
            progress = DownloadProgress(download_id=did, media_id=media.canonical_id, status="queued")
        else:
            progress = DownloadProgress(
                download_id=0,
                media_id=media.canonical_id,
                status="blocked",
                error=self._gate_reason(media),
            )
            self._compliance.log_simple(
                "download.blocked", media.source_url, media.platform,
                media.rights.download_license.value,
                f"download non consentito: {self._gate_reason(media)}",
            )
        if self.auto_start:
            self._ensure_thread()
        return progress

    def _license_gate(self, media: MediaObject) -> bool:
        """True se il download è CONSENTITO (vincolo di rilascio)."""
        return media.is_downloadable

    def _gate_reason(self, media: MediaObject) -> str:
        if media.rights.terms_violation_risk == RiskLevel.HIGH:
            return "rischio violazione termini: high (download bloccato)"
        if media.rights.download_license == DownloadLicense.UNKNOWN:
            return "nessuna licenza di download rilevata"
        return "licenza non valida"

    # ------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            item = self._repo.next_queued()
            if item is None:
                break
            self._process(item)

    # ------------------------------------------------------------------
    def _process(self, item: dict) -> None:
        media = MediaObject.model_validate(loads(item["media_json"]))
        did = int(item["id"])
        progress = DownloadProgress(download_id=did, media_id=media.canonical_id, status="running")
        self._emit(progress)
        self._compliance.log_simple(
            "download.start", media.source_url, media.platform,
            media.rights.download_license.value, f"priorità {item['priority']}",
        )

        try:
            if not self._license_gate(media):
                raise LicenseBlockedError(media.source_url, self._gate_reason(media))

            out_file = self._download_audio(media, did, progress)
            user_hash = self._user_hash()
            watermark = apply_watermark(
                out_file,
                user_hash=user_hash,
                source_url=media.source_url,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                title=media.title,
            )
            final = self.downloads_dir / out_file.name
            if final.exists():
                final.unlink()
            shutil.move(str(out_file), str(final))
            progress.status = "done"
            progress.percent = 100.0
            progress.path = str(final)
            progress.watermark = watermark
            self._emit(progress)
            self._compliance.log_simple(
                "download.done", media.source_url, media.platform,
                media.rights.download_license.value, f"watermark applicato: {watermark[:60]}",
            )
        except LicenseBlockedError as exc:
            self._fail(progress, did, media, "blocked", str(exc), event="download.blocked")
        except Exception as exc:
            self._fail(progress, did, media, "failed", str(exc), event="download.fail")

    def _fail(self, progress: DownloadProgress, did: int, media: MediaObject,
              status: str, error: str, event: str) -> None:
        progress.status = status
        progress.error = error
        self._emit(progress)
        self._compliance.log_simple(
            event, media.source_url, media.platform, media.rights.download_license.value, error
        )

    # ------------------------------------------------------------------
    def _user_hash(self) -> str:
        """Hash locale dell'utente, creato al primo utilizzo (mai PII)."""
        existing = self._settings.get("user_hash")
        if existing:
            return existing
        user_hash = uuid.uuid4().hex
        with transaction(self._conn):
            self._settings.set("user_hash", user_hash)
        return user_hash

    def _download_audio(self, media: MediaObject, did: int, progress: DownloadProgress) -> Path:
        """yt-dlp → audio + loudnorm. Ritorna il percorso del file temporaneo."""
        work = self.worker_dir / f"dl-{did}"
        work.mkdir(parents=True, exist_ok=True)
        cmd = _ytdlp_cmd([
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "--no-playlist", "--no-warnings",
            "--newline",
            "--extractor-args", "youtube:player_client=android",
            "--postprocessor-args", "ffmpeg:-af loudnorm=I=-16:TP=-1.5:LRA=11",
            "-o", str(work / "%(id)s.%(ext)s"),
            media.source_url,
        ])
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            match = _PROGRESS_RE.search(line)
            if match:
                progress.percent = float(match.group(1))
                speed = f"{match.group(4)}{match.group(5)}/s"
                eta = f"{match.group(6)}:{match.group(7)}" if match.group(6) else ""
                progress.speed = speed
                progress.eta = eta
                self._emit(progress)
        code = proc.wait()
        if code != 0:
            raise DownloadFailedError(media.source_url, f"yt-dlp terminato con codice {code}")

        files = list(work.glob("*.mp3"))
        if not files:
            # Formato non mp3 (es. già mp4): prendi qualunque file audio
            files = [f for f in work.iterdir() if f.is_file()]
        if not files:
            raise DownloadFailedError(media.source_url, "nessun file prodotto da yt-dlp")
        return files[0]
