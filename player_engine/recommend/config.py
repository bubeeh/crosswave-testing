"""Configurazione centralizzata del sistema di raccomandazione v2.

Tutti i pesi/soglie "magici" vivono QUI (non sparsi nel codice), così la
taratura post-test su ascolti reali è un'unica modifica.
"""

from __future__ import annotations

# --- Modalità ---
MODES: tuple[str, ...] = ("close", "scene", "mixed")
DEFAULT_MODE = "mixed"
DEFAULT_EXPLORE = 0.3

# --- Pesi degli eventi di ascolto (per il calcolo dei seed) ---
EVENT_TYPES: tuple[str, ...] = (
    "complete", "half", "partial", "skip", "replay", "like", "dislike", "seed",
)
EVENT_WEIGHTS: dict[str, float] = {
    "complete": 1.0,
    "half": 0.6,       # ascolto >= 50%
    "partial": 0.2,    # 15s .. 50%
    "skip": -0.3,      # < 15s
    "replay": 0.5,
    "like": 1.5,
    "dislike": -2.0,
    "seed": 1.5,       # seed manuale (cold start)
}

# Soglie per derivare l'event_type dai secondi/completion
SKIP_SECONDS = 15.0
HALF_RATIO = 0.5
COMPLETE_RATIO = 0.9

# Decadimento esponenziale del peso degli eventi
HALF_LIFE_DAYS = 30.0

# --- Selezione dei seed ---
SEED_TOP_N = 15
SEED_MIN_WEIGHT = 0.0

# --- Fusione delle fonti (Reciprocal Rank Fusion) ---
RRF_K = 60
# Pesi per fonte e modalità. Le fonti assenti da un dizionario vengono ignorate.
SOURCE_WEIGHTS: dict[str, dict[str, float]] = {
    "close": {
        "lastfm": 1.0, "soundcloud": 0.5, "youtube": 0.4,
        "musicbrainz": 0.4, "bandcamp": 0.3, "discogs": 0.3,
    },
    "scene": {
        "musicbrainz": 1.0, "bandcamp": 0.8, "discogs": 0.8,
        "lastfm": 0.4, "soundcloud": 0.4, "youtube": 0.4,
    },
    "mixed": {
        "lastfm": 0.7, "musicbrainz": 0.7, "soundcloud": 0.5,
        "bandcamp": 0.5, "youtube": 0.5, "discogs": 0.5,
    },
}

# --- Diversificazione ---
MAX_PER_SEED_TOP = 3        # max candidati dallo stesso seed nei primi N
MAX_PER_SEED_TOP_N = 20

# --- Cache TTL (giorni) per la similarità delle fonti ---
SIMILARITY_TTL_DAYS = 14.0
