"""Ranking cross-platform dei risultati di ricerca (modulo puro, senza I/O).

Unifica i risultati che arrivano da piattaforme diverse in un'unica lista
ordinata per rilevanza, invece di concatenarli a blocchi per sorgente:

  1. RRF (Reciprocal Rank Fusion): ogni risultato eredita il rank che aveva
     nella propria piattaforma → `platform_weight / (RRF_K + rank)`. Così i
     primi risultati di ogni sorgente emergono insieme (niente blocco YT in
     testa solo perché YT è la prima sorgente interrogata).
  2. Rilevanza testuale: overlap tra i token significativi della query e
     `title + uploader`, con bonus per la frase esatta.
  3. Bonus di tipo/canale: raccolta (album/playlist/set), canale Topic,
     canale verificato.
  4. Dedup cross-platform: la stessa traccia su piattaforme diverse viene
     tenuta una sola volta (vince il punteggio più alto).
  5. Diversità: nella testa della lista si alternano le piattaforme, con un
     decadimento del punteggio per ogni estrazione consecutiva dalla stessa
     sorgente. La rilevanza resta dominante, ma nessuna piattaforma
     monopolizza i primi risultati.

Tutti i "numeri magici" vivono QUI: la taratura è un'unica modifica.
"""

from __future__ import annotations

import re

from ..core.platforms import is_collection_url
from ..core.schema import SearchResult

# --- Fusione posizionale (RRF) ---
RRF_K = 60
# Quanto il rank interno alla piattaforma pesa rispetto alla rilevanza testo.
# Il termine RRF grezzo è ~1/(K+rank): lo scaliamo per renderlo confrontabile
# con la rilevanza testuale (0..1).
RRF_SCALE = 30.0
W_RRF = 1.0
W_TEXT = 1.0

# Priorità di piattaforma (1.0 = neutra). Leggermente più alta dove il catalogo
# è "musicale" per natura; comunque surclassata dalla rilevanza testuale.
PLATFORM_WEIGHTS: dict[str, float] = {
    "youtube": 1.0,
    "bandcamp": 1.0,
    "soundcloud": 1.0,
    "mixcloud": 0.9,
}

# --- Bonus di tipo/canale ---
BONUS_ALBUM = 0.15
BONUS_TOPIC = 0.10
BONUS_VERIFIED = 0.05
BONUS_PHRASE = 0.30

# --- Diversità / mixing cross-platform ---
TOP_WINDOW = 10            # quanti risultati "di testa" alternare tra sorgenti
PLATFORM_DECAY = 0.5       # ogni estrazione consecutiva dalla stessa sorgente pesa ×0.5

# Parole non significative per il match canale/query.
_STOPWORDS = {
    "official", "video", "audio", "music", "lyrics", "topic", "feat",
    "featuring", "hd", "hq", "full", "album", "live", "remix", "version", "edit",
}


def rank_results(per_platform: dict[str, list[SearchResult]], query: str) -> list[SearchResult]:
    """Fonde i risultati per-piattaforma in un'unica lista ordinata.

    `per_platform` mappa piattaforma → lista già ordinata per rilevanza
    interna. Ritorna una lista piatta, deduplicata e alternata tra sorgenti.
    """
    scored: list[tuple[float, int, SearchResult]] = []
    seq = 0
    for results in (per_platform or {}).values():
        for rank, result in enumerate(results or [], start=1):
            scored.append((_score(result, rank, query), seq, result))
            seq += 1

    # Sort stabile: a parità di punteggio vince l'ordine di arrivo (seq), a sua
    # volta deterministico perché per_platform è ordinato.
    scored.sort(key=lambda item: (-item[0], item[1]))

    deduped: list[tuple[float, SearchResult]] = []
    seen: set[str] = set()
    for score_value, _seq, result in scored:
        key = _dedup_key(result)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((score_value, result))

    return _mix(deduped)


# --------------------------------------------------------------------------
# Punteggio
# --------------------------------------------------------------------------
def _score(result: SearchResult, rank: int, query: str) -> float:
    weight = PLATFORM_WEIGHTS.get(result.platform, 1.0)
    rrf = weight / (RRF_K + rank)
    text = _text_relevance(query, result)
    return W_TEXT * text + W_RRF * rrf * RRF_SCALE + _bonus(result)


def _text_relevance(query: str, result: SearchResult) -> float:
    tokens = _query_tokens(query)
    if not tokens:
        return 0.0
    hay = f"{result.title} {result.uploader}".lower()
    matched = sum(1 for t in tokens if t in hay)
    score = matched / len(tokens)
    phrase = query.strip().lower()
    if phrase and phrase in hay:
        score += BONUS_PHRASE
    return score


def _bonus(result: SearchResult) -> float:
    bonus = 0.0
    if is_collection_url(result.platform, result.url):
        bonus += BONUS_ALBUM
    if result.is_topic:
        bonus += BONUS_TOPIC
    if result.channel_is_verified and not result.is_topic:
        bonus += BONUS_VERIFIED
    return bonus


# --------------------------------------------------------------------------
# Dedup & mixing
# --------------------------------------------------------------------------
def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _dedup_key(result: SearchResult) -> str:
    title = _normalize_key(result.title)
    uploader = _normalize_key(result.uploader)
    if uploader:
        return f"{title}|{uploader}"
    # uploader assente: dedup solo entro la stessa piattaforma (meno aggressivo)
    return f"{title}|{result.platform}"


def _mix(deduped: list[tuple[float, SearchResult]]) -> list[SearchResult]:
    """Alterna le sorgenti nella testa, poi ordine di punteggio per il resto.

    Nella testa si sceglie a ogni passo la piattaforma col miglior punteggio
    "effettivo" (punteggio × decadimento per estrazione consecutiva): così
    resta rilevanza-primo ma nessuna sorgente monopolizza i primi risultati.
    Oltre `TOP_WINDOW` i risultati tornano nell'ordine di punteggio.
    """
    queues: dict[str, list[tuple[float, SearchResult]]] = {}
    for score_value, result in deduped:
        queues.setdefault(result.platform, []).append((score_value, result))

    pointers = {platform: 0 for platform in queues}
    counts = {platform: 0 for platform in queues}
    head: list[SearchResult] = []

    def effective(platform: str) -> float:
        score_value, _ = queues[platform][pointers[platform]]
        return score_value * (PLATFORM_DECAY ** counts[platform])

    while len(head) < TOP_WINDOW:
        best_platform = None
        best_eff = float("-inf")
        for platform, items in queues.items():
            if pointers[platform] >= len(items):
                continue
            eff = effective(platform)
            if eff > best_eff:
                best_eff = eff
                best_platform = platform
        if best_platform is None:
            break
        _, result = queues[best_platform][pointers[best_platform]]
        pointers[best_platform] += 1
        counts[best_platform] += 1
        head.append(result)

    head_ids = {id(r) for r in head}
    tail = [result for _score_value, result in deduped if id(result) not in head_ids]
    return head + tail


def _query_tokens(query: str) -> list[str]:
    """Token significativi (>=3 char, senza stopword) per il match query."""
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]
