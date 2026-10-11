"""Fonte SoundCloud: tracce correlate (API v2 pubblica).

Trova una traccia seed dell'artista e ne legge i correlati; i loro uploader
diventano candidati. Riusa `player_engine/resolver/soundcloud_api.py`.
"""

from __future__ import annotations

from ..identity import normalize_name
from .base import Candidate


class SoundCloudSource:
    name = "soundcloud"
    max_seeds = 6

    def __init__(self, api=None) -> None:
        if api is None:
            from ...resolver import soundcloud_api as api  # lazy: evita import pesanti
        self._api = api

    def enabled(self) -> bool:
        return self._api is not None

    def similar(self, artist, limit: int = 20) -> list[Candidate]:
        if not self.enabled() or not artist.name:
            return []
        try:
            tracks = self._api.search_tracks(artist.name, 5)
        except Exception:
            return []

        seed = None
        for t in tracks or []:
            user = t.get("user") or {}
            if normalize_name(user.get("username")) == artist.name_norm:
                seed = t
                break
        if seed is None and tracks:
            seed = tracks[0]
        if not seed or not seed.get("id"):
            return []

        try:
            related = self._api.related_tracks(seed["id"], limit)
        except Exception:
            return []

        out: list[Candidate] = []
        seen: set[str] = set()
        for t in related or []:
            user = t.get("user") or {}
            name = str(user.get("username") or "").strip()
            norm = normalize_name(name)
            if not norm or norm == artist.name_norm or norm in seen:
                continue
            seen.add(norm)
            out.append(Candidate(
                name=name,
                source="soundcloud",
                score=0.6,
                reason=f"correlato su SoundCloud a {artist.name}",
            ))
        return out
