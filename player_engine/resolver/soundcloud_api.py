"""Accesso pubblico all'API v2 di SoundCloud per le RACCOLTE (set/playlist).

La ricerca standard di yt-dlp (`scsearch`) restituisce solo tracce e il flat
di un set non espone i titoli delle tracce. Per avere le raccolte in ricerca
e la tracklist completa con titoli serve l'API v2 pubblica, autenticata con il
`client_id` che SoundCloud pubblica nei propri asset JS.

Il client_id viene recuperato una volta e memoizzato (TTL 6h); in caso di
401/403 viene rinfrescato automaticamente. Tutte le chiamate sono GET senza
credenziali utente: nessuna azione invasiva, solo lettura di dati pubblici.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 PlayerCrossSource/0.1"
)

_API_BASE = "https://api-v2.soundcloud.com"
_HTTP_TIMEOUT = 20.0
_CLIENT_ID_TTL = 6 * 3600.0

_client_id: str | None = None
_client_id_ts: float = 0.0
_client_lock = threading.Lock()


class SoundCloudApiError(RuntimeError):
    """Errore di accesso all'API v2 pubblica di SoundCloud."""


def _extract_client_id_from_js(script: str) -> str | None:
    m = re.search(r'client_id\s*:\s*"([0-9a-zA-Z]{32})"', script)
    return m.group(1) if m else None


def _scrape_client_id() -> str:
    """Rileva il client_id pubblico dalla home + asset JS di SoundCloud."""
    try:
        home = httpx.get(
            "https://soundcloud.com/",
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=_HTTP_TIMEOUT,
        ).text
    except Exception as exc:  # rete/anti-bot
        raise SoundCloudApiError(f"impossibile contattare SoundCloud: {exc}") from exc

    for src in reversed(re.findall(r'<script[^>]+src="([^"]+)"', home)):
        try:
            js = httpx.get(src, headers={"User-Agent": UA}, timeout=_HTTP_TIMEOUT).text
        except Exception:
            continue
        cid = _extract_client_id_from_js(js)
        if cid:
            return cid
    raise SoundCloudApiError("client_id SoundCloud non trovato negli asset")


def get_client_id(force: bool = False) -> str:
    """client_id pubblico memoizzato (TTL 6h). `force=True` lo rinfresca."""
    global _client_id, _client_id_ts
    with _client_lock:
        fresh = _client_id and (time.time() - _client_id_ts) < _CLIENT_ID_TTL
        if fresh and not force:
            return _client_id  # type: ignore[return-value]
        _client_id = _scrape_client_id()
        _client_id_ts = time.time()
        return _client_id


def _api_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET autenticata sull'API v2, con un refresh del client_id su 401/403."""
    for attempt in range(2):
        cid = get_client_id(force=attempt > 0)
        query = dict(params)
        query["client_id"] = cid
        try:
            resp = httpx.get(
                f"{_API_BASE}{endpoint}",
                params=query,
                headers={"User-Agent": UA},
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise SoundCloudApiError(f"richiesta SoundCloud fallita: {exc}") from exc
        if resp.status_code in (401, 403) and attempt == 0:
            continue
        resp.raise_for_status()
        return resp.json()
    raise SoundCloudApiError("autenticazione SoundCloud non riuscita")


def artwork_url(obj: dict[str, Any]) -> str:
    """Copertina dell'oggetto (fallback sull'avatar dell'utente), in alta risoluzione."""
    art = obj.get("artwork_url")
    if not art:
        user = obj.get("user")
        if isinstance(user, dict):
            art = user.get("avatar_url")
    if not art:
        return ""
    return str(art).replace("-large", "-t500x500")


def _uploader_name(obj: dict[str, Any], fallback: str = "") -> str:
    user = obj.get("user")
    if isinstance(user, dict):
        return str(user.get("username") or user.get("permalink") or fallback)
    return fallback


def playlist_to_raw(item: dict[str, Any], fallback_url: str = "") -> dict[str, Any]:
    """Converte un oggetto playlist/set dell'API v2 in JSON normalizzabile.

    Il risultato rispetta il contratto grezzo atteso dal Normalizer
    (`_type`, `entries`, `id`, `title`, ...): niente formati/stream, che
    vengono risolti per singola traccia al momento del play.
    """
    uploader = _uploader_name(item)
    tracks: list[dict[str, Any]] = []
    for t in item.get("tracks") or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        tracks.append(
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "uploader": _uploader_name(t, uploader),
                "duration": float(t.get("duration") or 0) / 1000.0,
                "thumbnail": artwork_url(t),
                "webpage_url": str(t.get("permalink_url") or ""),
                "_type": "track",
            }
        )
    return {
        "id": item.get("id"),
        "title": item.get("title") or "Raccolta SoundCloud",
        "uploader": uploader,
        "thumbnail": artwork_url(item),
        "description": str(item.get("description") or ""),
        "duration": float(item.get("duration") or 0) / 1000.0,
        "webpage_url": str(fallback_url or item.get("permalink_url") or ""),
        "_type": "playlist",
        "entries": tracks,
    }


def search_playlists(query: str, limit: int = 25) -> list[dict[str, Any]]:
    """Set/playlist pubblici che matchano la query (oggetti API v2 grezzi)."""
    data = _api_get(
        "/search/playlists",
        {"q": query, "limit": min(limit, 200), "linked_partitioning": 1, "offset": 0},
    )
    return [item for item in (data.get("collection") or []) if isinstance(item, dict)]


def search_tracks(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Tracce pubbliche che matchano la query (oggetti API v2 grezzi)."""
    data = _api_get(
        "/search/tracks",
        {"q": query, "limit": min(limit, 200), "linked_partitioning": 1, "offset": 0},
    )
    return [item for item in (data.get("collection") or []) if isinstance(item, dict)]


def related_tracks(track_id: str | int, limit: int = 20) -> list[dict[str, Any]]:
    """Tracce correlate a una traccia SoundCloud (API v2 /tracks/<id>/related)."""
    data = _api_get(
        f"/tracks/{track_id}/related",
        {"limit": min(limit, 50), "linked_partitioning": 1, "offset": 0},
    )
    return [item for item in (data.get("collection") or []) if isinstance(item, dict)]


def _fetch_tracks_by_ids(ids: list[str]) -> list[dict[str, Any]]:
    """Idrata in batch (max 50 per chiamata) le tracce "stub" di un set.

    L'API `/resolve` restituisce solo le prime ~5 tracce complete; le altre
    sono stub `{id, kind, policy}` senza titolo. `/tracks?ids=` le completa.
    """
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = _api_get("/tracks", {"ids": ",".join(chunk)})
        if isinstance(data, list):
            out.extend(t for t in data if isinstance(t, dict))
    return out


def resolve_playlist(url: str) -> dict[str, Any] | None:
    """Risolve un URL di set SoundCloud nel suo oggetto playlist completo.

    Idrata le tracce stub in modo che la tracklist abbia titoli/durate per
    TUTTE le tracce. Ritorna None se l'URL non è una playlist/set.
    """
    data = _api_get("/resolve", {"url": url})
    if not isinstance(data, dict) or data.get("kind") not in ("playlist", "album"):
        return None

    tracks = data.get("tracks") or []
    stub_ids = [
        str(t["id"]) for t in tracks
        if isinstance(t, dict) and t.get("id") and not t.get("title")
    ]
    if stub_ids:
        by_id = {str(t.get("id")): t for t in _fetch_tracks_by_ids(stub_ids)}
        hydrated: list[dict[str, Any]] = []
        for t in tracks:
            if not isinstance(t, dict):
                continue
            full = by_id.get(str(t.get("id"))) if not t.get("title") else t
            if full:
                hydrated.append(full)
        data["tracks"] = hydrated
    return data
