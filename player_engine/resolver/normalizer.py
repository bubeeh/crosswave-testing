"""Normalizer: da JSON grezzo yt-dlp a Media Object canonico.

Adapter pattern per piattaforma (riserva Elena Rossi): ogni piattaforma ha
una policy di licenza e di rischio esplicita e documentata, così che le
fixture congelate possano essere testate deterministicamente.

Policy licenza (riserva Yuki Nakamura — condizione di rilascio):
  - youtube   : Creative Commons → creative_commons; licenza standard → explicit_permission
                (uso personale con watermark); altra licenza testuale → explicit_permission
  - bandcamp  : l'artista pubblica con intento di download → explicit_permission
  - soundcloud: traccia pubblica → explicit_permission; altrimenti unknown
  - vimeo     : licenza CC esplicita → creative_commons; altrimenti unknown
                (Vimeo disabilita spesso il download)
  - mixcloud  : streaming-only per policy → unknown (download bloccato)

Policy rischio (terms_violation_risk):
  - availability non pubblica (private/members_only/unlisted) → high
  - live_status is_live/post_live → medium
  - age_limit >= 18 → medium
  - altrimenti low
"""

from __future__ import annotations

from typing import Any

from ..core.platforms import PLATFORM_MEDIA_TYPE
from ..core.schema import (
    DownloadLicense,
    MediaObject,
    MediaType,
    Rights,
    RiskLevel,
    StreamInfo,
    compute_canonical_id,
    derive_tags,
)

# Formati che non sono stream diretti (m3u8/liste) — il player streama via URL diretto.
_SKIP_EXTS = {"m3u8", "mpd"}


def _pick_thumbnail(raw: dict[str, Any]) -> str:
    thumbs = raw.get("thumbnails") or []
    if not thumbs:
        return str(raw.get("thumbnail") or "")
    # Preferisci la più grande tra quelle disponibili
    best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    return str(best.get("url") or "")


def _format_streams(raw: dict[str, Any]) -> list[StreamInfo]:
    streams: list[StreamInfo] = []
    seen: set[str] = set()
    for f in raw.get("formats") or []:
        fmt_id = str(f.get("format_id") or "")
        if not fmt_id or fmt_id in seen:
            continue
        url = str(f.get("url") or "")
        if not url:
            continue  # formato non risolvibile → escluso
        ext = str(f.get("ext") or "").lower()
        if ext in _SKIP_EXTS or ".m3u8" in url.lower() or ".mpd" in url.lower() or "/manifest/" in url.lower():
            continue  # HLS/DASH: niente streaming diretto (il browser non li suona)
        seen.add(fmt_id)
        vcodec = str(f.get("vcodec") or "none")
        acodec = str(f.get("acodec") or "none")
        streams.append(
            StreamInfo(
                format_id=fmt_id,
                ext=ext,
                quality=str(f.get("format_note") or ""),
                url=url,
                size_bytes=f.get("filesize") or f.get("filesize_approx"),
                abr=f.get("abr"),
                vcodec="" if vcodec == "none" else vcodec,
                acodec="" if acodec == "none" else acodec,
                height=f.get("height"),
            )
        )
    if not streams and raw.get("url"):
        direct_url = str(raw.get("url"))
        if direct_url:
            streams.append(
                StreamInfo(
                    format_id="http_direct",
                    ext=str(raw.get("ext") or "mp3"),
                    quality="direct",
                    url=direct_url,
                    acodec="mp3",
                )
            )
    # Ordina: prima gli audio-only (con bitrate audio maggiore), poi i video
    streams.sort(key=lambda s: (1 if s.is_audio_only else 0, s.abr or 0, s.height or 0), reverse=True)
    return streams


def _detect_media_type(raw: dict[str, Any], platform: str) -> MediaType:
    streams = _format_streams(raw)
    if streams and all(s.is_audio_only for s in streams):
        return MediaType.AUDIO
    if platform == "bandcamp" and raw.get("track"):
        return MediaType.AUDIO
    if PLATFORM_MEDIA_TYPE[platform] == "audio":
        return MediaType.AUDIO
    if raw.get("_type") == "playlist":
        return MediaType.AUDIO
    return MediaType.VIDEO


def _availability_risk(raw: dict[str, Any]) -> RiskLevel:
    availability = raw.get("availability")
    if availability and availability not in ("public", None):
        return RiskLevel.HIGH  # private / members_only / unlisted
    if raw.get("live_status") in ("is_live", "post_live", "is_upcoming"):
        return RiskLevel.MEDIUM
    if (raw.get("age_limit") or 0) >= 18:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _license_policy(platform: str, raw: dict[str, Any]) -> tuple[DownloadLicense, str, str]:
    """(licenza, nota, sorgente della licenza) per piattaforma."""
    license_text = str(raw.get("license") or "").strip()
    webpage = str(raw.get("webpage_url") or "")
    if platform == "youtube":
        if "creative commons" in license_text.lower():
            return DownloadLicense.CREATIVE_COMMONS, license_text, webpage
        return DownloadLicense.EXPLICIT_PERMISSION, (
            "Licenza standard YouTube — download consentito solo per uso personale, "
            "con watermark e log di conformità."
        ), webpage
    if platform == "bandcamp":
        return DownloadLicense.EXPLICIT_PERMISSION, (
            "Bandcamp: l'artista pubblica con intento di download; watermark attivo."
        ), webpage
    if platform == "soundcloud":
        if raw.get("availability") in (None, "public"):
            return DownloadLicense.EXPLICIT_PERMISSION, (
                "Traccia pubblica SoundCloud — uso personale con watermark."
            ), webpage
        return DownloadLicense.UNKNOWN, "Traccia non pubblica.", webpage
    if platform == "vimeo":
        if "creative commons" in license_text.lower():
            return DownloadLicense.CREATIVE_COMMONS, license_text, webpage
        return DownloadLicense.UNKNOWN, (
            "Nessuna licenza di download esplicita rilevata (Vimeo spesso lo disabilita)."
        ), webpage
    if platform == "mixcloud":
        return DownloadLicense.UNKNOWN, (
            "Mixcloud è streaming-only per policy della piattaforma: download non attivo."
        ), webpage
    return DownloadLicense.UNKNOWN, "", webpage  # pragma: no cover


class Normalizer:
    """Trasforma JSON grezzo yt-dlp → MediaObject canonico (adapter per piattaforma)."""

    def __init__(self, resolver_version: str = "yt-dlp") -> None:
        self.resolver_version = resolver_version

    def normalize(
        self,
        platform: str,
        raw: dict[str, Any],
        *,
        source_url: str = "",
        resolved_at: str = "",
        cache_hit: bool = False,
    ) -> MediaObject:
        """Normalizza un output grezzo di yt-dlp."""
        webpage = str(raw.get("webpage_url") or source_url or "")
        canonical_id = compute_canonical_id(platform, raw.get("id"), webpage)
        title = str(raw.get("title") or webpage)
        uploader = str(raw.get("uploader") or raw.get("artist") or raw.get("channel") or "")
        license_, note, license_source = _license_policy(platform, raw)

        media = MediaObject(
            canonical_id=canonical_id,
            platform=platform,
            source_url=webpage,
            title=title,
            uploader=uploader,
            duration=float(raw.get("duration") or 0.0),
            thumbnail=_pick_thumbnail(raw),
            description=str(raw.get("description") or "")[:2000],
            media_type=_detect_media_type(raw, platform),
            tags=derive_tags(raw),
            streams=_format_streams(raw),
            rights=Rights(
                download_license=license_,
                terms_violation_risk=_availability_risk(raw),
                watermark_required=True,
                license_note=note,
                license_source=license_source,
            ),
            resolved_at=resolved_at,
            resolver_version=self.resolver_version,
            cache_hit=cache_hit,
            is_collection=(raw.get("_type") == "playlist") or "entries" in raw,
        )
        return media
