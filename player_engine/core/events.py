"""Eventi tipizzati emessi dal sistema (log conformità, worker, API).

Ogni evento ha: tipo, timestamp, piattaforma, URL sorgente e un payload.
Il log di conformità (24 mesi) si basa esclusivamente su questi eventi:
zero telemetria verso terzi (riserva Yuki Nakamura).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Tipi di evento registrati nel compliance_log
EVENT_RESOLVE_OK = "resolve.ok"
EVENT_RESOLVE_FAIL = "resolve.fail"
EVENT_STREAM = "stream.start"
EVENT_DOWNLOAD_START = "download.start"
EVENT_DOWNLOAD_DONE = "download.done"
EVENT_DOWNLOAD_FAIL = "download.fail"
EVENT_DOWNLOAD_BLOCKED = "download.blocked"
EVENT_EXPORT_COMPLIANCE = "compliance.export"
EVENT_FORGET_ALL = "history.forget_all"
EVENT_LICENSE_APPLIED = "download.watermark"


@dataclass(frozen=True)
class ComplianceEvent:
    """Un evento registrato nel log di conformità (retention 24 mesi)."""

    event_type: str
    source_url: str
    platform: str = ""
    license: str = ""
    detail: str = ""
    ts: str = field(default_factory=_now)

    def to_row(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source_url": self.source_url,
            "platform": self.platform,
            "license": self.license,
            "detail": self.detail,
            "ts": self.ts,
        }


@dataclass
class DownloadProgress:
    """Progresso di un download, trasmesso via WebSocket."""

    download_id: int
    media_id: str
    status: str  # queued | running | done | failed | blocked
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    path: str = ""
    watermark: str = ""
    error: str = ""
    ts: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "download_id": self.download_id,
            "media_id": self.media_id,
            "status": self.status,
            "percent": self.percent,
            "speed": self.speed,
            "eta": self.eta,
            "path": self.path,
            "error": self.error,
            "ts": self.ts,
        }
