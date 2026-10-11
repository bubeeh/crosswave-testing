"""Fonte YouTube: tracce correlate via Mix automatico (list=RD<id>).

Richiede il resolver isolato (yt-dlp): cerca un video per l'artista, poi ne
legge il Mix (`op: related`). Gli uploader dei correlati diventano candidati.
"""

from __future__ import annotations

from ...core.platforms import native_id_from_url
from ..identity import normalize_name
from .base import Candidate


class YouTubeSource:
    name = "youtube"
    max_seeds = 5  # fonte costosa (yt-dlp): limita i seed interrogati

    def __init__(self, resolver) -> None:
        self._resolver = resolver

    def enabled(self) -> bool:
        return self._resolver is not None

    def similar(self, artist, limit: int = 25) -> list[Candidate]:
        if not self.enabled() or not artist.name:
            return []
        try:
            seeds = self._resolver.search("youtube", artist.name)
        except Exception:
            return []

        video_id = None
        for r in seeds or []:
            vid = native_id_from_url("youtube", r.url)
            if vid:
                video_id = vid
                break
        if not video_id:
            return []

        try:
            related = self._resolver.related(video_id, limit)
        except Exception:
            return []

        out: list[Candidate] = []
        seen: set[str] = set()
        for r in related or []:
            name = str(getattr(r, "uploader", "") or "").strip()
            norm = normalize_name(name)
            if not norm or norm == artist.name_norm or norm in seen:
                continue
            seen.add(norm)
            out.append(Candidate(
                name=name,
                source="youtube",
                score=0.6,
                reason=f"correlato su YouTube a {artist.name}",
            ))
        return out
