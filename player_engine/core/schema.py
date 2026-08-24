"""Media Object versionato (schema semver) — riserva Elena Rossi.

Il Media Object è il contratto canonico tra resolver, storage, API e UI.
Ogni cambio di struttura incrementa `SCHEMA_VERSION` (major.minor.patch).
La degradazione a "solo link" (riserva Elena + Aiko: health-check runtime)
mantiene invariata la struttura: `streams` resta presente ma vuoto e
`degraded: true` segnala che il resolver non era disponibile.

Vincolo di rilascio (riserva Yuki Nakamura): nessun download è consentito
senza `rights.download_license` popolato; `terms_violation_risk == high`
blocca il download.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator

from .platforms import PLATFORMS

SCHEMA_VERSION = "1.0.0"

# Termini del vocabolario controllato per la licenza di download
LICENSE_VALUES: tuple[str, ...] = (
    "public_domain",
    "creative_commons",
    "explicit_permission",
    "unknown",
)

RISK_VALUES: tuple[str, ...] = ("low", "medium", "high")


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


class DownloadLicense(str, Enum):
    PUBLIC_DOMAIN = "public_domain"
    CREATIVE_COMMONS = "creative_commons"
    EXPLICIT_PERMISSION = "explicit_permission"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Rights(BaseModel):
    """Vincoli legali rilevati dal resolver (riserva Yuki Nakamura)."""

    download_license: DownloadLicense = DownloadLicense.UNKNOWN
    terms_violation_risk: RiskLevel = RiskLevel.MEDIUM
    watermark_required: bool = Field(
        default=True,
        description="True se il download deve applicare il watermark ID3 "
        "(hash utente, timestamp, URL sorgente).",
    )
    license_note: str = ""
    license_source: str = ""


class StreamInfo(BaseModel):
    """Un flusso risolvibile (URL diretto) con i suoi attributi."""

    format_id: str
    ext: str
    quality: str = ""
    url: str = ""
    size_bytes: int | None = None
    abr: float | None = None
    vcodec: str = ""
    acodec: str = ""
    height: int | None = None

    @property
    def is_audio_only(self) -> bool:
        return not self.vcodec and bool(self.acodec)

    @property
    def is_manifest(self) -> bool:
        """True se l'URL punta a un manifest (HLS/DASH) e non a un file diretto.
        I manifest non sono riproducibili da un <audio>/<video> senza demuxer
        esterni: esclusi dallo streaming diretto."""
        u = self.url.lower()
        return ".m3u8" in u or ".mpd" in u or "/manifest/" in u


class MediaObject(BaseModel):
    """Contratto canonico: un media risolto da qualsiasi piattaforma."""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    canonical_id: str = Field(description="sha256:piattaforma:id — identità stabile")
    platform: str
    source_url: str
    title: str
    uploader: str = ""
    duration: float = 0.0
    thumbnail: str = ""
    description: str = ""
    media_type: MediaType
    tags: list[str] = Field(default_factory=list)
    streams: list[StreamInfo] = Field(default_factory=list)
    rights: Rights = Field(default_factory=Rights)
    resolved_at: str = ""
    resolver_version: str = ""
    cache_hit: bool = False
    is_collection: bool = Field(
        default=False,
        description="True se il media è una raccolta (album/playlist): niente "
        "stream diretto, ha una tracklist (GET /api/album/{id}).",
    )
    degraded: bool = Field(
        default=False,
        description="True se il resolver era giù: 'solo link', niente streams.",
    )

    @field_validator("platform")
    @classmethod
    def _platform_supported(cls, v: str) -> str:
        if v not in PLATFORMS:
            raise ValueError(f"piattaforma non supportata: {v}")
        return v

    # ------------------------------------------------------------------
    # API utili
    # ------------------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_downloadable(self) -> bool:
        """Condizione di rilascio: licenza popolata E rischio non alto."""
        return (
            self.rights.download_license != DownloadLicense.UNKNOWN
            and self.rights.terms_violation_risk != RiskLevel.HIGH
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def can_stream(self) -> bool:
        return bool(self.streams)

    def best_stream(self, prefer_audio: bool = False) -> StreamInfo | None:
        """Selezione dello stream migliore per la riproduzione diretta.

        Priorità (verificata dal vivo su YouTube senza cookie):
          1. muxed progressivi (vcodec+acodec, URL diretto) — supportano i
             range su più connessioni; un <audio> estrae la traccia audio
          2. audio-only (per le piattaforme audio: Bandcamp/SoundCloud/Mixcloud)
          3. altrimenti il più alto in qualità
        I manifest (HLS/DASH) sono già esclusi dal normalizer.
        """
        if not self.streams:
            return None
        direct = [s for s in self.streams if s.url and not s.is_manifest]
        if not direct:
            return None
        if prefer_audio or self.media_type == MediaType.AUDIO:
            muxed = [s for s in direct if s.vcodec and s.acodec]
            if muxed:
                return max(muxed, key=lambda s: (s.height or 0, s.abr or 0))
            audio_only = [s for s in direct if s.is_audio_only]
            if audio_only:
                return max(audio_only, key=lambda s: (s.abr or 0))
        return max(direct, key=lambda s: (s.height or 0, s.abr or 0))

    def downgrade_to_link(self, resolver_version: str, resolved_at: str) -> "MediaObject":
        """Degradazione a 'solo link': streams svuotati, flag degraded."""
        return self.model_copy(
            update={
                "streams": [],
                "degraded": True,
                "resolver_version": resolver_version,
                "resolved_at": resolved_at,
            }
        )

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:  # noqa: D102
        return super().model_dump_json(*args, **kwargs)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def compute_canonical_id(platform: str, native_id: str | None, source_url: str) -> str:
    """Identità stabile: sha256 della coppia piattaforma+id nativo (o URL)."""
    raw = native_id if native_id else source_url
    digest = hashlib.sha256(f"{platform}:{raw}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class SearchResult(BaseModel):
    """Risultato di ricerca LEGGERO: solo il link, niente stream.

    La risoluzione completa (streams, licenza) avviene al click tramite
    /api/resolve (riserva Astrid: TTF < 5s — la UI è pronta subito).
    """

    platform: str
    url: str
    title: str
    uploader: str = ""
    duration: float = 0.0
    thumbnail: str = ""
    canonical_id: str = ""


def derive_tags(raw: dict[str, Any]) -> list[str]:
    """Tag normalizzati e deduplicati derivati dai metadati yt-dlp grezzi."""
    tags: list[str] = []
    for key in ("tags", "genres", "categories"):
        for t in raw.get(key) or []:
            if isinstance(t, str) and t.strip():
                tags.append(t.strip())
    # Generi/topic comuni di yt-dlp non vuoti
    if raw.get("genre"):
        tags.append(str(raw["genre"]))
    if raw.get("album"):
        tags.append(f"album:{raw['album']}")
    if raw.get("artist"):
        tags.append(f"artist:{raw['artist']}")
    if raw.get("live_status") and raw["live_status"] not in (None, "not_live"):
        tags.append("live")
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            out.append(t)
    return out[:12]
