"""Fonte Discogs: stessa etichetta (roster) e stili/generi.

Richiede `DISCOGS_TOKEN` (auth). Senza token la fonte è disabilitata.
I titoli dei risultati Discogs sono spesso "Artista - Titolo": da lì si estrae
l'artista per proporre artisti della stessa etichetta. Degrado silenzioso.
"""

from __future__ import annotations

import os
from typing import Any

from ...core.errors import RecommendationSourceError
from ..identity import normalize_name
from .base import Candidate

BASE_URL = "https://api.discogs.com"
UA = "CrossWave/0.1 +https://github.com/bubeeh/crosswave-testing"


class DiscogsSource:
    name = "discogs"
    max_seeds = 5

    def __init__(self, http, cache=None, limiter=None, token: str | None = None) -> None:
        self._http = http
        self._cache = cache
        self._limiter = limiter
        self._token = (token if token is not None else os.environ.get("DISCOGS_TOKEN", "")).strip()

    def enabled(self) -> bool:
        return bool(self._token)

    def similar(self, artist, limit: int = 20) -> list[Candidate]:
        if not self.enabled() or not artist.name:
            return []
        try:
            releases = self._search(
                f"rel:{artist.name_norm}",
                {"artist": artist.name, "type": "release", "per_page": 25},
            )
        except Exception:
            return []

        labels: list[str] = []
        for r in releases:
            for lb in (r.get("label") or []):
                if lb and lb not in labels:
                    labels.append(lb)

        out: list[Candidate] = []
        seen: set[str] = set()
        for label in labels[:2]:
            try:
                by_label = self._search(
                    f"label:{normalize_name(label)}",
                    {"label": label, "type": "release", "per_page": 25},
                )
            except Exception:
                continue
            for r in by_label:
                name = self._artist_from_title(str(r.get("title") or ""))
                norm = normalize_name(name)
                if not norm or norm == artist.name_norm or norm in seen:
                    continue
                seen.add(norm)
                out.append(Candidate(
                    name=name,
                    source="discogs",
                    score=0.5,
                    reason=f"stessa etichetta: {label}",
                ))
                if len(out) >= limit:
                    return out
        return out

    # ------------------------------------------------------------------
    def _search(self, cache_key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if self._cache is not None:
            cached = self._cache.get(self.name, cache_key)
            if cached is not None:
                return cached.get("results") or []
        data = self._request("/database/search", params)
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        if self._cache is not None:
            self._cache.set(self.name, cache_key, {"results": results})
        return results

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._limiter is not None:
            self._limiter.wait(self.name)
        query = dict(params)
        try:
            resp = self._http.get(
                BASE_URL + path,
                params=query,
                headers={"User-Agent": UA, "Authorization": f"Discogs token={self._token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise RecommendationSourceError(self.name, str(exc)) from exc

    @staticmethod
    def _artist_from_title(title: str) -> str:
        if not title:
            return ""
        return title.split(" - ", 1)[0].strip()
