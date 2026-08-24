# -*- coding: utf-8 -*-
"""
YouTube Utility Module
Fornisce funzioni helper per interagire con YouTube (es. ricerca tramite yt-dlp).
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

def search_youtube(query: str, limit: int = 15) -> list:
    """
    Cerca su YouTube tramite yt-dlp e restituisce una lista di risultati standardizzati.
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
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = info.get('entries', []) or []
            for entry in entries:
                if entry:
                    thumb = _get_best_thumbnail(entry.get("thumbnails"))
                    if not thumb and entry.get('id'):
                        thumb = f"https://img.youtube.com/vi/{entry.get('id')}/hqdefault.jpg"
                    
                    results.append({
                        "title": entry.get("title", "Senza Titolo"),
                        "artist": entry.get("uploader") or entry.get("artist") or "Canale Sconosciuto",
                        "type": "Video",
                        "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
                        "source": "YouTube",
                        "thumbnail": thumb
                    })
    except Exception as e:
        print(f"Errore ricerca YouTube: {e}", file=sys.stderr)
        
    return results
