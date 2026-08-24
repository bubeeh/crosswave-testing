"""Watermark ID3 sui download (riserva Yuki Nakamura + Fase 3 del piano).

Il watermark incapsula: hash utente (derivato da chiave locale, mai PII),
timestamp di download e URL sorgente. Formati supportati:
  - mp3      → ID3 (TXXX "player_watermark" + COMM leggibile + TCOP)
  - m4a/mp4  → MP4 tags ("\xa9cmt" comment)
  - flac/ogg → VorbisComment
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import WatermarkError

TXXX_KEY = "player_watermark"


def build_watermark_payload(user_hash: str, source_url: str, timestamp: str) -> dict:
    return {
        "user_hash": user_hash,
        "source_url": source_url,
        "downloaded_at": timestamp,
        "schema": "player-watermark/v1",
    }


def _apply_id3(path: Path, payload: dict, title: str) -> None:
    from mutagen.id3 import COMM, TCOP, TIT2, TXXX, ID3

    try:
        tags = ID3(path)
    except Exception:
        tags = ID3()
    tags.delall("TXXX")
    tags.add(TXXX(encoding=3, desc=TXXX_KEY, text=json.dumps(payload, ensure_ascii=False)))
    tags.delall("COMM")
    tags.add(
        COMM(
            encoding=3,
            lang="eng",
            desc="player",
            text=(
                f"File scaricato con Player Cross-Source — utente {payload['user_hash'][:8]} "
                f"— {payload['downloaded_at']} — sorgente {payload['source_url']}"
            ),
        )
    )
    tags.delall("TCOP")
    tags.add(TCOP(encoding=3, text=f"player-watermark:{payload['user_hash'][:8]}"))
    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=title[:200]))
    tags.save(path)


def _apply_mp4(path: Path, payload: dict) -> None:
    from mutagen.mp4 import MP4, MP4FreeForm

    tags = MP4(path)
    tags["\xa9cmt"] = [
        f"player-watermark {json.dumps(payload, ensure_ascii=False)}"
    ]
    tags["cprt"] = [f"player-watermark:{payload['user_hash'][:8]}"]
    tags["----:com.apple.iTunes:player_watermark"] = MP4FreeForm(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    tags.save(path)


def _apply_vorbis(path: Path, payload: dict) -> None:
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis

    data = json.dumps(payload, ensure_ascii=False)
    for cls in (FLAC, OggVorbis):
        try:
            tags = cls(path)
            tags[TXXX_KEY] = data
            tags["copyright"] = f"player-watermark:{payload['user_hash'][:8]}"
            tags.save(path)
            return
        except Exception:
            continue
    raise WatermarkError(str(path), "formato non supportato per watermark Vorbis")


def apply_watermark(file_path: str | Path, *, user_hash: str, source_url: str,
                    timestamp: str, title: str = "") -> str:
    """Applica il watermark al file e ritorna la stringa del payload."""
    path = Path(file_path)
    if not path.exists():
        raise WatermarkError(str(path), "file non trovato")
    payload = build_watermark_payload(user_hash, source_url, timestamp)
    ext = path.suffix.lower()
    try:
        if ext in (".mp3",):
            _apply_id3(path, payload, title)
        elif ext in (".m4a", ".mp4", ".m4b"):
            _apply_mp4(path, payload)
        elif ext in (".flac", ".ogg", ".opus"):
            _apply_vorbis(path, payload)
        else:
            # Video o formato non taggabile: sidecar JSON accanto al file
            sidecar = path.with_suffix(path.suffix + ".watermark.json")
            sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except WatermarkError:
        raise
    except Exception as exc:
        raise WatermarkError(str(path), f"fallito: {exc}") from exc
    return json.dumps(payload, ensure_ascii=False)


def read_watermark(file_path: str | Path) -> dict | None:
    """Legge il watermark da un file (per verifica nei test)."""
    path = Path(file_path)
    ext = path.suffix.lower()
    try:
        if ext in (".mp3",):
            from mutagen.id3 import ID3, TXXX

            tags = ID3(path)
            for frame in tags.getall("TXXX"):
                if frame.desc == TXXX_KEY:
                    return json.loads(frame.text[0])
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4FreeForm

            tags = MP4(path)
            for key, value in tags.items():
                if key.startswith("----") and isinstance(value, list) and value:
                    raw = bytes(value[0])
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except Exception:
                        continue
        elif ext in (".flac", ".ogg", ".opus"):
            from mutagen.flac import FLAC
            from mutagen.oggvorbis import OggVorbis

            for cls in (FLAC, OggVorbis):
                try:
                    tags = cls(path)
                    if TXXX_KEY in tags:
                        return json.loads(tags[TXXX_KEY][0])
                except Exception:
                    continue
    except Exception:
        return None
    return None
