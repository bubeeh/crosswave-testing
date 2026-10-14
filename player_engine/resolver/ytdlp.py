"""Helper condiviso per invocare yt-dlp (binario, script .py o modulo).

Un'unica implementazione della risoluzione del comando evita divergenze tra
worker (resolver) e searcher: `PLAYER_YTDLP_BIN` può puntare a un binario nel
PATH, a uno script `.py` o (default) a `yt-dlp`.
"""

from __future__ import annotations

import os
import shutil
import sys


def ytdlp_bin() -> str:
    """Percorso/nome del binario yt-dlp (override via PLAYER_YTDLP_BIN)."""
    return os.environ.get("PLAYER_YTDLP_BIN", "yt-dlp")


def ytdlp_cmd(args: list[str]) -> list[str]:
    """Comando yt-dlp: script .py → python, nel PATH → diretto, altrimenti modulo."""
    bin_ = ytdlp_bin()
    if bin_.endswith(".py"):
        return [sys.executable, bin_, *args]
    if shutil.which(bin_):
        return [bin_, *args]
    return [sys.executable, "-m", "yt_dlp", *args]
