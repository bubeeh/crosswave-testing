"""Registro delle piattaforme supportate.

Ogni piattaforma espone: nome, regex di riconoscimento URL, tipo di contenuto
prevalente e soglia di `terms_violation_risk` di default. Il registry è
l'unico posto dove si dichiara una piattaforma: normalizer, rate limiter,
filtri UI e fixtures devono usarlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Piattaforme supportate (ordine di visualizzazione nei filtri UI)
PLATFORMS: tuple[str, ...] = (
    "youtube",
    "bandcamp",
    "soundcloud",
    "vimeo",
    "mixcloud",
)

# Media type prevalente per piattaforma
PLATFORM_MEDIA_TYPE: dict[str, str] = {
    "youtube": "video",
    "bandcamp": "audio",
    "soundcloud": "audio",
    "vimeo": "video",
    "mixcloud": "audio",
}


@dataclass(frozen=True)
class PlatformSpec:
    """Specifica statica di una piattaforma."""

    key: str
    label: str
    url_pattern: re.Pattern[str]
    media_type: str


_PATTERNS: dict[str, str] = {
    "youtube": r"https?://(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|live/|embed/)|youtu\.be/)",
    "bandcamp": r"https?://([a-z0-9-]+\.)?bandcamp\.com/(track/|album/|.*\.bandcamp\.com/)",
    # api.soundcloud.com/tracks/... è l'URL che restituisce la ricerca flat
    "soundcloud": r"https?://(www\.|m\.)?(api\.)?soundcloud\.com/[^/]+/[^/?]+",
    "vimeo": r"https?://(www\.)?vimeo\.com/\d+",
    "mixcloud": r"https?://(www\.)?mixcloud\.com/[^/]+/[^/?]+",
}

_SPECS: dict[str, PlatformSpec] = {
    key: PlatformSpec(
        key=key,
        label={
            "youtube": "YouTube",
            "bandcamp": "Bandcamp",
            "soundcloud": "SoundCloud",
            "vimeo": "Vimeo",
            "mixcloud": "Mixcloud",
        }[key],
        url_pattern=re.compile(pat),
        media_type=PLATFORM_MEDIA_TYPE[key],
    )
    for key, pat in _PATTERNS.items()
}


def detect_platform(url: str) -> str | None:
    """Riconosce la piattaforma da un URL. None se non supportata."""
    for key in PLATFORMS:
        if _SPECS[key].url_pattern.match(url):
            return key
    return None


def native_id_from_url(platform: str, url: str) -> str | None:
    """Id nativo derivabile dall'URL (per il lookup in cache pre-yt-dlp).

    È l'identità che il normalizer ricaverà da `raw["id"]`; se le due
    derivazioni coincidono, una risoluzione ripetuta viene servita dalla
    cache TTL 72h SENZA consumare il rate limit (riserva Aiko).
    """
    if platform == "youtube":
        m = re.search(r"[?&]v=([\w-]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"youtu\.be/([\w-]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"shorts/([\w-]+)", url)
        if m:
            return m.group(1)
    elif platform == "vimeo":
        m = re.search(r"/(\d+)", url)
        if m:
            return m.group(1)
    elif platform == "bandcamp":
        m = re.search(r"/(track|album)/([\w-]+)", url)
        if m:
            return f"{m.group(1)}:{m.group(2)}"
    elif platform in ("soundcloud", "mixcloud"):
        # l'identità nativa è il percorso completo (slug utente + slug traccia)
        from urllib.parse import urlparse

        path = urlparse(url).path.strip("/")
        if path:
            return path
    return None


def platform_spec(key: str) -> PlatformSpec:
    if key not in _SPECS:
        raise KeyError(f"piattaforma sconosciuta: {key}")
    return _SPECS[key]


def labels() -> dict[str, str]:
    """Mappa chiave → label leggibile (per i filtri UI)."""
    return {key: spec.label for key, spec in _SPECS.items()}
