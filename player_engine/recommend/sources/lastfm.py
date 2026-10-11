"""Fonte Last.fm: artisti simili (segnali collaborativi "chi ascolta X ascolta Y").

Richiede `LASTFM_API_KEY`. Senza chiave la fonte è disabilitata e la pipeline
prosegue con le altre (degrado silenzioso). Cache TTL lungo + rate limit
dedicato (chiave "lastfm").
"""

from __future__ import annotations

import os
from typing import Any

from ...core.errors import RecommendationSourceError
from ..identity import ArtistRef
from .base import Candidate

BASE_URL = "https://ws.audioscrobbler.com/2.0/"


class LastFmSource:
    name = "lastfm"

    def __init__(self, http, cache=None, limiter=None, api_key: str | None = None) -> None:
        self._http = http
        self._cache = cache
        self._limiter = limiter
        self._api_key = (api_key if api_key is not None else os.environ.get("LASTFM_API_KEY", "")).strip()

    def enabled(self) -> bool:
        return bool(self._api_key)

    def similar(self, artist: ArtistRef, limit: int = 20) -> list[Candidate]:
        if not self.enabled() or not artist.name:
            return []
        cache_key = f"similar:{artist.name_norm}"
        if self._cache is not None:
            cached = self._cache.get(self.name, cache_key)
            if cached is not None:
                return self._parse(cached)[:limit]

        if self._limiter is not None:
            self._limiter.wait(self.name)
        try:
            resp = self._http.get(
                BASE_URL,
                params={
                    "method": "artist.getsimilar",
                    "artist": artist.name,
                    "api_key": self._api_key,
                    "format": "json",
                    "limit": limit,
                    "autocorrect": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # rete/HTTP/JSON
            raise RecommendationSourceError(self.name, str(exc)) from exc

        if self._cache is not None:
            self._cache.set(self.name, cache_key, data)
        return self._parse(data)[:limit]

    @staticmethod
    def _parse(data: dict[str, Any]) -> list[Candidate]:
        block = data.get("similarartists") or {}
        items = block.get("artist") or []
        out: list[Candidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            try:
                match = float(item.get("match") or 0.0)
            except (TypeError, ValueError):
                match = 0.0
            out.append(
                Candidate(
                    name=name,
                    source="lastfm",
                    score=max(0.0, min(1.0, match)),
                    mbid=str(item.get("mbid") or "") or None,
                    reason="simile (Last.fm)",
                )
            )
        return out
