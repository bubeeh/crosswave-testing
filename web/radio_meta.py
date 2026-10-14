"""Metadati "now playing" delle Web Radio + palinsesti informativi.

Estratto da app.py: isolamento della logica di rete (ICY/NTS/Fango/RFV) dalla
definizione delle rotte Flask. Cache TTL 45s per non martellare lo stream.
"""

from __future__ import annotations

import datetime
import json
import re
import ssl
import threading
import time
import urllib.request

_RADIO_META_CACHE: dict[str, dict] = {}
_RADIO_META_LOCK = threading.Lock()
_RADIO_META_TTL = 45.0  # seconds


def fetch_real_radio_metadata(url: str, station_name: str | None = None):
    cache_key = f"{url}||{station_name or ''}"
    now_ts = time.time()
    with _RADIO_META_LOCK:
        cached = _RADIO_META_CACHE.get(cache_key)
        if cached and (now_ts - cached['ts'] < _RADIO_META_TTL):
            return cached['title']

    result = _fetch_real_radio_metadata_uncached(url, station_name)

    if result:
        with _RADIO_META_LOCK:
            _RADIO_META_CACHE[cache_key] = {'title': result, 'ts': now_ts}

    return result


def _insecure_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_real_radio_metadata_uncached(url: str, station_name: str | None = None):
    # 1. Special handling for NTS Live API
    if (station_name and 'NTS' in station_name) or ('ntslive' in url):
        try:
            req = urllib.request.Request('https://www.nts.live/api/v2/live', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, context=_insecure_context(), timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                ch1 = data['results'][0]
                now = ch1['now']['embeds']['details']
                name = now.get('name')
                title = now.get('title')
                desc = now.get('description', '')
                loc = now.get('location_long', '')
                show_title = name or title or desc or "NTS Live Broadcast"
                return f"{show_title} ({loc})" if loc else show_title
        except Exception:
            pass

    # 2. Special handling for Fango Radio status JSON
    if (station_name and 'Fango' in station_name) or ('pantano.ovh' in url):
        try:
            req = urllib.request.Request('https://pantano.ovh:8444/status-json.xsl', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=_insecure_context(), timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                src = data.get('icestats', {}).get('source')
                if isinstance(src, list):
                    src = src[0]
                raw_title = src.get('title', '')
                if raw_title:
                    parts = raw_title.split(' --- ')
                    return parts[0].strip()
        except Exception:
            pass

    # 3. Special handling for Radio Firenze Viola daily time-based schedule
    if (station_name and 'Firenze Viola' in station_name) or ('rfviola' in url):
        hour = datetime.datetime.now().hour
        if 7 <= hour < 9: return "Buongiorno Firenze (Rassegna Stampa)"
        elif 9 <= hour < 10: return "C'è polemica (Il dibattito quotidiano)"
        elif 10 <= hour < 12: return "Chi si compra? (Calciomercato Viola)"
        elif 12 <= hour < 14: return "Viola amore mio (Notizie e Interviste)"
        elif 14 <= hour < 16: return "Palla al centro (Approfondimento RFV)"
        elif 16 <= hour < 17: return "Nik & Nik (Calciomercato in diretta)"
        elif 17 <= hour < 19: return "Garrisca al vento (Community Viola)"
        elif 19 <= hour < 21: return "Stadio Viola (Diretta Serale)"
        else: return "Repliche & Musica Viola"

    # 4. Standard ICY Stream Title Extraction for NTS, Oolong, etc.
    try:
        req = urllib.request.Request(url, headers={'Icy-MetaData': '1', 'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18'})
        with urllib.request.urlopen(req, context=_insecure_context(), timeout=8) as resp:
            metaint_hdr = resp.headers.get('icy-metaint')
            if metaint_hdr:
                metaint = int(metaint_hdr)
                resp.read(metaint)
                meta_byte = resp.read(1)
                if meta_byte:
                    meta_len = ord(meta_byte) * 16
                    if meta_len > 0:
                        meta_raw = resp.read(meta_len).decode('utf-8', errors='ignore')
                        m = re.search(r"StreamTitle='([^']*)';", meta_raw)
                        if m and m.group(1).strip():
                            val = m.group(1).strip()
                            if 'NTS 1 - ' in val:
                                val = val.replace('NTS 1 - ', '')
                            return val
    except Exception:
        pass

    return None


def radio_schedule(station_name: str, now_playing: str | None) -> list[dict]:
    """Palinsesto informativo della stazione (fallback generico se sconosciuta)."""
    if station_name == 'Radio Firenze Viola':
        return [
            {'time': 'Sito Ufficiale', 'title': 'https://www.radiofirenzeviola.it'},
            {'time': 'In Onda Ora', 'title': now_playing or 'Diretta Viola Talk & News'},
            {'time': '07:00 - 09:00', 'title': 'Buongiorno Firenze (Rassegna Stampa)'},
            {'time': '09:00 - 10:00', 'title': "C'è polemica (Il dibattito quotidiano)"},
            {'time': '10:00 - 12:00', 'title': 'Chi si compra? (Calciomercato Viola)'},
            {'time': '12:00 - 14:00', 'title': 'Viola amore mio (Notizie e Interviste)'},
            {'time': '14:00 - 16:00', 'title': 'Palla al centro (Approfondimento RFV)'},
            {'time': '16:00 - 17:00', 'title': 'Nik & Nik (Calciomercato in diretta)'},
            {'time': '17:00 - 19:00', 'title': 'Garrisca al vento (Community Viola)'},
            {'time': '19:00 - 21:00', 'title': 'Stadio Viola (Diretta Serale)'},
            {'time': '21:00 - 07:00', 'title': 'Repliche & Musica Viola'},
        ]
    if station_name == 'Fango Radio':
        return [
            {'time': 'Sito Ufficiale', 'title': 'https://www.fangoradio.com'},
            {'time': 'In Onda Ora', 'title': now_playing or 'Trasmissione Fango Radio'},
            {'time': 'Archivio Shows', 'title': 'https://www.fangoradio.com/shows/'},
        ]
    if station_name == 'NTS Radio 1 (London)':
        return [
            {'time': 'Sito Ufficiale', 'title': 'https://www.nts.live'},
            {'time': 'In Onda Ora', 'title': now_playing or 'NTS Live London Broadcast'},
            {'time': 'Guida Palinsesto', 'title': 'https://www.nts.live/schedule'},
        ]
    if station_name == 'Oolong Radio (Berlin)':
        return [
            {'time': 'Sito Ufficiale', 'title': 'https://oolongradio.com'},
            {'time': 'In Onda Ora', 'title': now_playing or 'Oolong Radio Berlin Live'},
        ]
    return [
        {'time': 'In Onda Ora', 'title': now_playing or 'Live Broadcast'},
        {'time': 'Info', 'title': 'Web Radio Live Streaming'},
    ]
