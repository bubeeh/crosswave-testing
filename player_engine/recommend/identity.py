"""Identità artista: normalizzazione nomi + risoluzione locale (senza rete).

La risoluzione a MusicBrainz (MBID) avviene in `recommend/sources/musicbrainz.py`
(Fase 1) e aggiorna la tabella `artists` tramite `ArtistRepo`. Qui restano la
normalizzazione pura (testabile con fixtures) e l'aggancio DB (alias + link).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Suffisso dei canali YouTube auto-generati: "Burial - Topic"
_TOPIC_SUFFIX = re.compile(r"\s*[-–—]\s*topic\s*$", flags=re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTISPACE = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Normalizza un nome artista per il matching (chiave `name_norm`).

    - rimuove il suffisso " - Topic";
    - rimuove accenti/diacritici (NFKD);
    - lowercase;
    - riduce punteggiatura/spazi a singoli spazi.
    """
    if not name:
        return ""
    s = _TOPIC_SUFFIX.sub("", str(name))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = _NON_ALNUM.sub(" ", s)
    return _MULTISPACE.sub(" ", s).strip()


@dataclass(frozen=True)
class ArtistRef:
    """Riferimento artista risolto localmente (leggero, serializzabile)."""

    name: str
    name_norm: str
    mbid: str | None = None
    artist_id: int | None = None


def canonical_ref(name: str, mbid: str | None = None, artist_id: int | None = None) -> ArtistRef:
    """Costruisce un ArtistRef senza toccare il DB (per test/uso puro)."""
    return ArtistRef(name=(name or "").strip(), name_norm=normalize_name(name),
                     mbid=mbid, artist_id=artist_id)


def resolve_local(repo, name: str, platform: str | None = None,
                  url: str | None = None, mbid: str | None = None) -> ArtistRef | None:
    """Risolve (o crea) l'artista nel DB locale e registra link/alias.

    `repo` è un `ArtistRepo`. Ritorna None se il nome non è normalizzabile.
    La risoluzione a MBID resta `unresolved` finché la fonte MusicBrainz
    (Fase 1) non la conferma.
    """
    name = (name or "").strip()
    norm = normalize_name(name)
    if not norm:
        return None
    artist_id = repo.upsert(name=name, name_norm=norm, mbid=mbid)
    if platform and url:
        repo.link(artist_id, platform, url)
    return ArtistRef(name=name, name_norm=norm, mbid=mbid, artist_id=artist_id)
