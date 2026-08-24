"""Eccezioni tipizzate del player cross-source.

Gerarchia:
    PlayerError
    ├── ResolveError
    │   ├── UnsupportedPlatformError
    │   ├── ResolverUnavailableError
    │   ├── RateLimitedError
    │   ├── SourceForbiddenError
    │   └── ResolveTimeoutError
    ├── StreamingError
    │   ├── StreamNotFoundError
    │   └── RangeNotSupportedError
    ├── DownloadError
    │   ├── LicenseBlockedError
    │   ├── WatermarkError
    │   └── DownloadFailedError
    ├── SearchError
    │   ├── SearchUnsupportedError
    │   └── SearchRateLimitedError
    ├── StorageError
    ├── ComplianceError
    └── RecommendationError
"""

from __future__ import annotations


class PlayerError(Exception):
    """Base per tutte le eccezioni del player."""


# --------------------------------------------------------------------------
# Resolver layer
# --------------------------------------------------------------------------
class ResolveError(PlayerError):
    """Errore generico durante la risoluzione di un URL."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")


class UnsupportedPlatformError(ResolveError):
    """L'URL non appartiene a nessuna piattaforma supportata."""


class ResolverUnavailableError(ResolveError):
    """Il processo Media Resolver non risponde (health-check fallito)."""


class RateLimitedError(ResolveError):
    """La piattaforma è occupata: rate limit 1 richiesta/5s non rispettabile.

    Attributi: retry_after (secondi).
    """

    def __init__(self, url: str, platform: str, retry_after: float) -> None:
        self.platform = platform
        self.retry_after = retry_after
        super().__init__(url, f"rate limit {platform}: riprova tra {retry_after:.0f}s")


class SourceForbiddenError(ResolveError):
    """La piattaforma ha rifiutato la richiesta (403 / bot detection)."""


class ResolveTimeoutError(ResolveError):
    """Timeout durante la risoluzione."""


# --------------------------------------------------------------------------
# Streaming layer
# --------------------------------------------------------------------------
class StreamingError(PlayerError):
    """Errore generico durante lo streaming."""


class StreamNotFoundError(StreamingError):
    """Nessuno stream disponibile per il media richiesto (degradazione 'solo link')."""


class RangeNotSupportedError(StreamingError):
    """La sorgente non supporta richieste con Range header."""


# --------------------------------------------------------------------------
# Download layer
# --------------------------------------------------------------------------
class DownloadError(PlayerError):
    """Errore generico durante il download."""


class LicenseBlockedError(DownloadError):
    """Download bloccato: `rights.download_license` assente o
    `terms_violation_risk == high`. Condizione non negoziabile del go-live.
    """


class WatermarkError(DownloadError):
    """Impossibile applicare il watermark ID3 al file scaricato."""


class DownloadFailedError(DownloadError):
    """Il worker di download ha fallito (yt-dlp/ffmpeg errore)."""


# --------------------------------------------------------------------------
# Search layer
# --------------------------------------------------------------------------
class SearchError(PlayerError):
    """Errore generico durante la ricerca per piattaforma."""

    def __init__(self, platform: str, message: str) -> None:
        self.platform = platform
        super().__init__(f"{platform}: {message}")


class SearchUnsupportedError(SearchError):
    """La piattaforma non ha un canale di ricerca (es. Vimeo)."""

    def __init__(self, platform: str) -> None:
        super().__init__(platform, "ricerca non supportata per questa piattaforma")


class SearchRateLimitedError(SearchError):
    """Rate limit 1/5s della piattaforma raggiunto durante la ricerca."""

    def __init__(self, platform: str, retry_after: float, query: str = "") -> None:
        self.retry_after = retry_after
        self.query = query
        super().__init__(platform, f"Sorgente occupata — riprovo tra {retry_after:.0f}s")
class StorageError(PlayerError):
    """Errore generico di persistenza SQLite."""


class ComplianceError(PlayerError):
    """Violazione delle regole di conformità (log 24 mesi, retention, export)."""


class RecommendationError(PlayerError):
    """Errore nel calcolo o nella lettura delle raccomandazioni."""
