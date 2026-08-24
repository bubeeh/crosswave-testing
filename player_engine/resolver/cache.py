"""Cache risoluzioni con TTL 72h (riserva Aiko Tanaka: cold start zero-fetch).

La home non fa alcun fetch all'avvio: i contenuti si popolano mentre l'utente
usa il player. La cache evita anche di consumare i rate limit su richieste
ripetute dello stesso URL.
"""

from __future__ import annotations

from typing import Any

from ..core.schema import MediaObject
from ..storage.repos import CacheRepo


class ResolutionCache:
    """Facciata sulla tabella media_cache con TTL 72 ore."""

    def __init__(self, repo: CacheRepo) -> None:
        self._repo = repo

    def get(self, canonical_id: str) -> MediaObject | None:
        return self._repo.get(canonical_id)

    def put(self, media: MediaObject) -> None:
        self._repo.set(media)

    def get_tracklist(self, album_cid: str) -> list[dict[str, Any]] | None:
        """Tracklist di un album già risolto (chiave derivata tracklist:<cid>)."""
        return self._repo.get_tracklist(album_cid)

    def put_tracklist(self, album_cid: str, tracks: list[dict[str, Any]], resolved_at: str) -> None:
        self._repo.set_tracklist(album_cid, tracks, resolved_at)

    def get_alias(self, url: str) -> str | None:
        """Alias URL→canonical_id (raccolte con id nativo non derivabile da URL)."""
        return self._repo.get_alias(url)

    def put_alias(self, url: str, canonical_id: str, resolved_at: str) -> None:
        self._repo.set_alias(url, canonical_id, resolved_at)

    def clear(self) -> None:
        self._repo.clear()
