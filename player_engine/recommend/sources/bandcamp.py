"""Fonte Bandcamp: stessa etichetta/collezione (roster).

Trova il profilo Bandcamp dell'artista (fuzzysearch) e ne legge il catalogo
(`resolver/catalog.py`); gli artisti delle release diventano candidati
(utile per le label). Fragile: tollera i blocchi anti-bot con degrado silenzioso.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ..identity import normalize_name
from .base import Candidate

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrossWave/0.1"
SEARCH_URL = "https://bandcamp.com/api/fuzzysearch/1/app_autocomplete"


def _default_search(query: str) -> list[dict]:
    import httpx

    resp = httpx.get(SEARCH_URL, params={"q": query}, headers={"User-Agent": UA},
                     timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.json().get("results") or []


def _default_catalog(profile_url: str):
    from ...resolver.catalog import build_catalog

    return build_catalog("bandcamp", profile_url)


class BandcampSource:
    name = "bandcamp"
    max_seeds = 6

    def __init__(self, search_fn=None, catalog_fn=None) -> None:
        self._search_fn = search_fn or _default_search
        self._catalog_fn = catalog_fn or _default_catalog

    def enabled(self) -> bool:
        return True

    def similar(self, artist, limit: int = 20) -> list[Candidate]:
        if not artist.name:
            return []
        try:
            results = self._search_fn(artist.name)
        except Exception:
            return []

        profile = None
        band_name = ""
        for item in results or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if "/album/" in url or "/track/" in url:
                p = urlparse(url)
                if p.scheme and p.netloc:
                    profile = f"{p.scheme}://{p.netloc}"
                    band_name = str(item.get("band_name") or item.get("name") or "")
                break
        if not profile:
            return []

        try:
            catalog = self._catalog_fn(profile)
        except Exception:
            return []

        label_name = str(getattr(catalog, "name", "") or band_name or profile)
        out: list[Candidate] = []
        seen: set[str] = set()
        for section in getattr(catalog, "sections", []) or []:
            for item in getattr(section, "items", []) or []:
                name = str(getattr(item, "uploader", "") or "").strip()
                norm = normalize_name(name)
                if not norm or norm == artist.name_norm or norm in seen:
                    continue
                seen.add(norm)
                out.append(Candidate(
                    name=name,
                    source="bandcamp",
                    score=0.5,
                    reason=f"stessa etichetta/collezione: {label_name}",
                ))
                if len(out) >= limit:
                    return out
        return out
