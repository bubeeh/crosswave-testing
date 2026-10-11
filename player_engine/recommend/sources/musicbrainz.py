"""Fonte MusicBrainz: relazioni (collaboratori, membri) per la modalità "scena".

MusicBrainz richiede un User-Agent identificativo e max 1 richiesta/secondo.
Senza MBID dell'artista viene prima risolto via ricerca (`/artist?query=`).
Cache TTL lungo + rate limit dedicato (chiave "musicbrainz").
"""

from __future__ import annotations

import os
from typing import Any

from ...core.errors import RecommendationSourceError
from ..identity import ArtistRef, normalize_name
from .base import Candidate

BASE_URL = "https://musicbrainz.org/ws/2"
DEFAULT_UA = "CrossWave/0.1 (+https://github.com/bubeez/crosswave-testing)"

# Peso (0..1) per tipo di relazione artista-artista
_REL_SCORES: dict[str, float] = {
    "member of band": 0.9,
    "collaboration": 0.85,
    "is person": 0.6,
    "founder": 0.7,
    "subgroup": 0.7,
    "supporting musician": 0.6,
    "involved with": 0.5,
    "involved with (production)": 0.4,
    "conductor position": 0.3,
    "tribute": 0.3,
}


class MusicBrainzSource:
    name = "musicbrainz"

    def __init__(self, http, cache=None, limiter=None, user_agent: str | None = None) -> None:
        self._http = http
        self._cache = cache
        self._limiter = limiter
        self._ua = (user_agent or os.environ.get("MB_USER_AGENT") or DEFAULT_UA).strip()

    def enabled(self) -> bool:
        return True

    def similar(self, artist: ArtistRef, limit: int = 20) -> list[Candidate]:
        mbid = artist.mbid or self._resolve_mbid(artist)
        if not mbid:
            return []
        data = self._cached_request(
            f"rels:{mbid}", f"/artist/{mbid}",
            {"inc": "artist-rels", "fmt": "json"},
        )
        return self._parse_relations(data, artist)[:limit]

    # ------------------------------------------------------------------
    def _resolve_mbid(self, artist: ArtistRef) -> str | None:
        if not artist.name:
            return None
        cache_key = f"mbid:{artist.name_norm}"
        if self._cache is not None:
            cached = self._cache.get(self.name, cache_key)
            if cached is not None:
                return cached.get("mbid")
        data = self._request("/artist", {"query": artist.name, "fmt": "json", "limit": 5})
        mbid = self._best_mbid(data, artist.name_norm)
        if self._cache is not None:
            self._cache.set(self.name, cache_key, {"mbid": mbid})
        return mbid

    def _cached_request(self, cache_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._cache is not None:
            cached = self._cache.get(self.name, cache_key)
            if cached is not None:
                return cached
        data = self._request(path, params)
        if self._cache is not None:
            self._cache.set(self.name, cache_key, data)
        return data

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._limiter is not None:
            self._limiter.wait(self.name)  # 1 req/s: attende lo slot
        try:
            resp = self._http.get(
                BASE_URL + path,
                params=params,
                headers={"User-Agent": self._ua, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise RecommendationSourceError(self.name, str(exc)) from exc

    @staticmethod
    def _best_mbid(data: dict[str, Any], name_norm: str) -> str | None:
        best_id: str | None = None
        best_score = -1.0
        for a in data.get("artists") or []:
            if not isinstance(a, dict):
                continue
            norm = normalize_name(a.get("name"))
            if not norm or not name_norm:
                continue
            if norm == name_norm or name_norm in norm or norm in name_norm:
                try:
                    score = float(a.get("score") or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                if score > best_score:
                    best_score = score
                    best_id = str(a.get("id") or "") or None
        return best_id

    @staticmethod
    def _parse_relations(data: dict[str, Any], artist: ArtistRef) -> list[Candidate]:
        out: list[Candidate] = []
        for rel in data.get("relations") or []:
            if not isinstance(rel, dict) or rel.get("target-type") != "artist":
                continue
            target = rel.get("artist") or {}
            name = str(target.get("name") or "").strip()
            if not name:
                continue
            rtype = str(rel.get("type") or "related")
            score = _REL_SCORES.get(rtype, 0.4)
            if "colleague" in rtype or "collaboration" in rtype:
                reason = f"collabora con {artist.name}"
            elif rtype == "member of band":
                reason = f"membro di {artist.name}"
            else:
                reason = f"{rtype} · {artist.name}"
            out.append(
                Candidate(
                    name=name,
                    source="musicbrainz",
                    score=score,
                    mbid=str(target.get("id") or "") or None,
                    reason=reason,
                )
            )
        return out
