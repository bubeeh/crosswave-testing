"""Registro canali curati per la sezione "Mix Random" (mix/DJ set lunghi).

Fonte di verità per i canali: si aggiungono o tolgono canali SOLO qui.
Il resto del sistema (API, UI) legge da CHANNELS.

Regole operative:
  - YouTube: usare l'ID `/channel/<ID>` (gli handle @ falliscono con yt-dlp
    in questa versione). ID validati con `python -m player_engine.cli channels-verify`
    prima del commit.
  - Mixcloud: username dell'API pubblica (`api.mixcloud.com/<username>/cloudcasts/`).
  - SoundCloud: escluso per ora (il fetch flat dei profili non restituisce entry).
"""

from __future__ import annotations

# key = identificatore stabile (usato per escludere il canale corrente al click "Altro")
CHANNELS: tuple[dict[str, str], ...] = (
    {
        "key": "br_yt",
        "platform": "youtube",
        "id": "UCGBpxWJr9FNOcFYA5GkKrMg",
        "label": "Boiler Room",
    },
    {
        "key": "mixmag_yt",
        "platform": "youtube",
        "id": "UCQdCIrTpkhEH5Z8KPsn7NvQ",
        "label": "Mixmag Lab",
    },
    {
        "key": "mixmag_mc",
        "platform": "mixcloud",
        "id": "mixmag",
        "label": "Mixmag On Rotation",
    },
)
