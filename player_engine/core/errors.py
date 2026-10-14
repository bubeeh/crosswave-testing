"""Eccezioni tipizzate del player cross-source.

Gerarchia:
    PlayerError
    ├── ResolveError
    │   ├── UnsupportedPlatformError
    │   ├── ResolverUnavailableError
    │   ├── RateLimitedError
    │   ├── SourceForbiddenError
    │   └── ResolveTimeoutError
    ├── SearchError
    │   ├── SearchUnsupportedError
    │   └── SearchRateLimitedError
    ├── StorageError
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


class RecommendationError(PlayerError):
    """Errore nel calcolo o nella lettura delle raccomandazioni."""


class RecommendationSourceError(PlayerError):
    """Errore di una fonte esterna di similarità (Last.fm, MusicBrainz, ...).

    Le fonti degradano silenziosamente: la pipeline prosegue con le altre.
    """

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"{source}: {message}")
