# -*- coding: utf-8 -*-
"""
SoundCloud Utility Module
Fornisce funzioni helper per interagire con SoundCloud (es. ricerca tramite yt-dlp).
"""

import yt_dlp
import sys

def _get_best_thumbnail(thumbnails):
    if not thumbnails:
        return None
    # Cerca un'immagine di medie dimensioni
    for t in thumbnails:
        if t.get("id") in ("t300x300", "large", "hq720", "hqdefault", "medium"):
            return t.get("url")
    return thumbnails[-1].get("url")

def search_soundcloud(query: str, limit: int = 15) -> list:
    """
    Cerca su SoundCloud tramite yt-dlp e restituisce una lista di risultati standardizzati.
    """
    results = []
    try:
        ydl_opts = {
            'extract_flat': True,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            entries = info.get('entries', []) or []
            for entry in entries:
                if entry:
                    thumb = _get_best_thumbnail(entry.get("thumbnails"))
                    results.append({
                        "title": entry.get("title", "Senza Titolo"),
                        "artist": entry.get("uploader") or entry.get("artist") or "Artista Sconosciuto",
                        "type": "Traccia",
                        "url": entry.get("url") or entry.get("webpage_url"),
                        "source": "SoundCloud",
                        "thumbnail": thumb
                    })
    except Exception as e:
        print(f"Errore ricerca SoundCloud: {e}", file=sys.stderr)
        
    return results
