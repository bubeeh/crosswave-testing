"""Interfaccia comune delle fonti di similarità (adapter pattern)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..identity import ArtistRef, normalize_name


@dataclass(slots=True)
class Candidate:
    """Artista candidato proposto da una fonte."""

    name: str
    source: str
    score: float = 0.0        # 0..1, normalizzato per fonte
    mbid: str | None = None
    reason: str = ""          # testo breve, es. "collabora con X"
    meta: dict = field(default_factory=dict)

    @property
    def name_norm(self) -> str:
        return normalize_name(self.name)


@runtime_checkable
class RecSource(Protocol):
    """Contratto di una fonte: nome + similar(artist, limit)."""

    name: str

    def enabled(self) -> bool: ...

    def similar(self, artist: ArtistRef, limit: int) -> list[Candidate]: ...
