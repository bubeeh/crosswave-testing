# -*- coding: utf-8 -*-
"""
Mixcloud Utility Module
Fornisce funzioni helper per interagire con Mixcloud (es. ricerca tramite API ufficiale).
"""

import urllib.request
import urllib.parse
import json
import sys

def search_mixcloud(query: str) -> list:
    """
    Cerca su Mixcloud tramite le API pubbliche e restituisce una lista di risultati standardizzati.
    """
    results = []
    try:
        url = f"https://api.mixcloud.com/search/?q={urllib.parse.quote(query)}&type=cloudcast"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        items = data.get('data', []) or []
        for item in items:
            img = item.get("pictures", {}).get("large") or item.get("pictures", {}).get("medium") or item.get("pictures", {}).get("thumbnail")
            results.append({
                "title": item.get("name", "Senza Titolo"),
                "artist": item.get("user", {}).get("name") or item.get("user", {}).get("username") or "Uploader",
                "type": "DJ Mix",
                "url": item.get("url"),
                "source": "Mixcloud",
                "thumbnail": img
            })
    except Exception as e:
        print(f"Errore ricerca Mixcloud: {e}", file=sys.stderr)
        
    return results
