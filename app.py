#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CrossWave Hybrid Player Server
Combines CrossWave UX with test2's isolated Media Resolver Engine (yt-dlp subprocess),
loudnorm audio normalization, ID3 watermarking, and 5-platform support (YouTube, Bandcamp, SoundCloud, Mixcloud, Vimeo).
"""

import os
import sys
import re
import json
import time
import uuid
import datetime
import sqlite3
import ssl
import zipfile
import gzip
import tempfile
import threading
import urllib.request
import html
import random
from collections import OrderedDict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, jsonify, request, Response, send_file

import yt_dlp
import requests

# Import test2 player engine modules
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from player_engine.resolver.service import ResolverService
from player_engine.resolver.search import SEARCHABLE_PLATFORMS
from player_engine.core.channels import CHANNELS
from player_engine.core.platforms import detect_platform, native_id_from_url
from player_engine.core.errors import (
    ResolverUnavailableError,
    SearchError,
    SearchRateLimitedError,
    SearchUnsupportedError,
    RateLimitedError,
)
from player_engine.download.watermark import apply_watermark
from downloader.download_core import clean_temporary_residues
from telegram_bot import init_telegram_db, start_telegram_bot_thread

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("SECRET_KEY", "crosswave_hybrid_secret_key_2026")

# ------------------------------------------------------------------
# Performance: cache HTTP per gli asset statici + compressione gzip
# ------------------------------------------------------------------
_GZIP_MIN_BYTES = 500


def _should_gzip(response) -> bool:
    """Comprime solo risposte in memoria (mai streaming audio) di tipo testo."""
    if request.path.startswith('/api/downloads/stream'):
        return False
    if request.path.startswith('/static/'):
        # I file statici sono piccoli: disattiviamo il passthrough per
        # poterli leggere in memoria e comprimere (gzip + cache headers)
        response.direct_passthrough = False
    elif response.direct_passthrough:
        return False
    if response.mimetype not in ('text/html', 'text/css', 'text/javascript',
                                 'application/javascript', 'application/json'):
        return False
    return len(response.get_data()) >= _GZIP_MIN_BYTES


@app.after_request
def add_perf_headers(response):
    # Asset statici: cache lunga nel browser (l'ETag di Werkzeug evita
    # riscaricamenti inutili; i file cambiano solo al deploy)
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'

    # Compressione gzip per HTML/CSS/JS/JSON, se il client la supporta
    if _should_gzip(response) and 'gzip' in request.headers.get('Accept-Encoding', ''):
        data = response.get_data()
        if data:
            compressed = gzip.compress(data, compresslevel=6)
            if len(compressed) < len(data):
                response.set_data(compressed)
                response.headers['Content-Encoding'] = 'gzip'
                response.headers['Content-Length'] = str(len(compressed))
                response.headers['Vary'] = 'Accept-Encoding'
    return response

DB_PATH = BASE_DIR / "crosswave.db"
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Initialize Isolated Subprocess Media Resolver Engine
resolver_service = ResolverService(db_path=str(BASE_DIR / "resolver_cache.db"), autostart=True)

# Audio Streaming Cache (LRU)
AUDIO_CACHE_SIZE = 500
audio_url_cache = OrderedDict()
cache_lock = threading.Lock()

# Background download executor
soundload_executor = ThreadPoolExecutor(max_workers=3)
soundload_jobs = {}
soundload_jobs_lock = threading.Lock()


# ------------------------------------------------------------------
# Database Layer
# ------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            track_id TEXT NOT NULL,
            title TEXT NOT NULL,
            artist TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            thumbnail TEXT,
            duration INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, track_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watch_later (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            track_id TEXT NOT NULL,
            title TEXT NOT NULL,
            artist TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            thumbnail TEXT,
            duration INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, track_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlist_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            track_id TEXT NOT NULL,
            title TEXT NOT NULL,
            artist TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            thumbnail TEXT,
            duration INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS web_radios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            stream_url TEXT NOT NULL UNIQUE,
            genre TEXT,
            logo TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute("SELECT COUNT(*) as count FROM web_radios")
    if cursor.fetchone()['count'] == 0:
        default_radios = [
            ("NTS Radio 1 (London)", "https://stream-relay-geo.ntslive.net/stream", "Underground & Experimental", "https://images.unsplash.com/photo-1465847899084-d164df4dedc6?w=150"),
            ("Fango Radio", "https://pantano.ovh:8444/pantano", "Experimental & Independent", "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150"),
            ("Oolong Radio (Berlin)", "https://stream.oolongradio.com:8443/live", "Experimental & Sound Art", "https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?w=150"),
            ("Noods Radio (Bristol)", "https://noods-radio.radiocult.fm/stream", "Underground & Experimental", "https://noodsradio.com/images/og-meta-default-image.jpg"),
            ("Radio Firenze Viola", "https://stream.tmwradio.com/rfviola.aac", "Sport & News ACF Fiorentina", "https://www.radiofirenzeviola.it/template/radiofirenzeviola.it/img/1280x720.jpg")
        ]
        cursor.executemany(
            "INSERT INTO web_radios (name, stream_url, genre, logo) VALUES (?, ?, ?, ?)",
            default_radios
        )

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_flags (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    cursor.execute("SELECT value FROM system_flags WHERE key = 'channels_seeded'")
    if not cursor.fetchone():
        cursor.execute("SELECT COUNT(*) as count FROM custom_channels")
        if cursor.fetchone()['count'] == 0:
            default_channels = [
                ("youtube", "https://www.youtube.com/@gvonniai/videos", "gvonniai")
            ]
            cursor.executemany(
                "INSERT INTO custom_channels (platform, url, label) VALUES (?, ?, ?)",
                default_channels
            )
        cursor.execute("INSERT OR REPLACE INTO system_flags (key, value) VALUES ('channels_seeded', '1')")

    conn.commit()
    conn.close()
    init_telegram_db()


init_db()


def get_current_user_id():
    """App personale senza profili: tutti i dati (preferiti, playlist, guarda
    dopo) appartengono all'unico utente locale (id 1)."""
    return 1


# ------------------------------------------------------------------
# Multi-Platform Search Engine (delegato al MediaResolver worker isolato)
# ------------------------------------------------------------------
# La ricerca NON tocca mai yt-dlp nel processo Flask: viene delegata al
# processo worker (player_engine/resolver/search.py), che applica gli
# standard del progetto: isolamento processi, rate limit 1/5s per
# piattaforma e cache query TTL 30 min. Ritorna SOLO link leggeri
# (SearchResult): la risoluzione completa avviene al click via /api/resolve.
# Le piattaforme senza canale di ricerca (es. Vimeo) sono escluse: la lista
# canonica è SEARCHABLE_PLATFORMS.

_PLATFORM_LABELS = {
    'youtube': 'YouTube',
    'soundcloud': 'SoundCloud',
    'bandcamp': 'Bandcamp',
    'mixcloud': 'Mixcloud',
}


def _search_result_to_track(result):
    """Mappa un SearchResult (contratto canonico) alla forma attesa dalla UI.

    La UI (main.js) usa source/artist/id/type; il contratto canonico usa
    platform/uploader/canonical_id. L'embed YouTube richiede l'id nativo con
    prefisso 'yt_' (vedi playTrackImmediately), gli album Bandcamp sono
    raccolte e si aprono nella vista album.
    """
    url = result.url
    platform = result.platform
    native = native_id_from_url(platform, url)
    track_id = f"yt_{native}" if platform == 'youtube' and native else result.canonical_id
    media_type = 'album' if platform == 'bandcamp' and '/album/' in url else 'track'
    duration = result.duration or 0
    return {
        'id': track_id,
        'canonical_id': result.canonical_id,
        'title': result.title or 'Senza Titolo',
        'artist': result.uploader or 'Artista Sconosciuto',
        'uploader': result.uploader,
        'source': platform,
        'url': url,
        'thumbnail': result.thumbnail or '',
        'duration': duration,
        'duration_string': f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/D",
        'type': media_type,
    }


def execute_platform_search(source, query, max_results=10):
    """Ricerca su una piattaforma DELEGATA al worker isolato.

    Ritorna un dict {results, error, message, retry_after} con error == None
    in caso di successo. Gli errori sono tipizzati e arrivano alla UI invece
    di trasformarsi in liste vuote silenziose.
    """
    label = _PLATFORM_LABELS.get(source, source.capitalize() if source else '')
    if source not in SEARCHABLE_PLATFORMS:
        return {
            'results': [],
            'error': 'search_unsupported',
            'message': f'Ricerca non disponibile per {label} — incolla direttamente un URL in "Incolla URL".',
            'retry_after': 0,
        }
    try:
        results = resolver_service.search(source, query)
    except SearchRateLimitedError as exc:
        # Rate limit etico 1/5s per piattaforma: la UI mostra retry_after
        return {'results': [], 'error': 'rate_limited',
                'message': str(exc), 'retry_after': exc.retry_after}
    except SearchUnsupportedError as exc:
        return {'results': [], 'error': 'search_unsupported',
                'message': str(exc), 'retry_after': 0}
    except SearchError as exc:
        # include search_failed / no_results / bandcamp anti-bot (search_blocked)
        return {'results': [], 'error': 'search_failed',
                'message': str(exc), 'retry_after': 0}
    except ResolverUnavailableError:
        return {'results': [], 'error': 'resolver_down',
                'message': 'Motore di ricerca non disponibile — riprova tra poco.',
                'retry_after': 0}
    except Exception as exc:  # mai far cadere la ricerca per un bug interno
        return {'results': [], 'error': 'internal',
                'message': f'Errore interno durante la ricerca {label}: {exc}',
                'retry_after': 0}

    if not results:
        return {'results': [], 'error': None,
                'message': f'Nessun risultato per "{query}" su {label}.',
                'retry_after': 0}
    return {'results': [_search_result_to_track(r) for r in results[:max_results]],
            'error': None, 'message': '', 'retry_after': 0}


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    sources_param = request.args.get('sources', ','.join(SEARCHABLE_PLATFORMS))

    if not query:
        return jsonify({'error': 'Query di ricerca mancante'}), 400

    selected_sources = [s.strip().lower() for s in sources_param.split(',') if s.strip()]
    # Unica fonte di verità: SEARCHABLE_PLATFORMS (Vimeo etc. scartate)
    selected_sources = [s for s in selected_sources if s in SEARCHABLE_PLATFORMS]
    if not selected_sources:
        return jsonify({'error': 'Nessuna sorgente di ricerca valida'}), 400

    results = {}
    with ThreadPoolExecutor(max_workers=len(selected_sources)) as executor:
        future_to_source = {
            executor.submit(execute_platform_search, src, query): src
            for src in selected_sources
        }
        for future in as_completed(future_to_source):
            src = future_to_source[future]
            try:
                results[src] = future.result()
            except Exception:
                results[src] = {'results': [], 'error': 'internal',
                                'message': 'Errore interno della ricerca', 'retry_after': 0}

    return jsonify({'query': query, 'results': results})


@app.route('/api/mix/random')
def api_mix_random():
    """Mix random: canale casuale dal registry curato (CHANNELS), feed dei
    suoi ultimi set (filtro durata nel worker), shuffle. Il canale corrente
    può essere escluso con ?exclude=<key> (bottone "Altro")."""
    channels = list(CHANNELS)
    if not channels:
        return jsonify({'error': 'Nessun canale nel registry'}), 500
    exclude = request.args.get('exclude', '')
    pool = [c for c in channels if c['key'] != exclude] or channels
    channel = random.choice(pool)
    try:
        results = resolver_service.channel(channel['platform'], channel['id'])
    except SearchRateLimitedError as exc:
        return jsonify({'error': 'rate_limited', 'message': str(exc),
                        'retry_after': exc.retry_after}), 429
    except (SearchError, ResolverUnavailableError) as exc:
        return jsonify({'error': 'channel_failed',
                        'message': f'{channel["label"]}: {exc}'}), 502
    except Exception as exc:  # mai far cadere la sezione per un bug interno
        return jsonify({'error': 'internal', 'message': f'Errore interno: {exc}'}), 500

    mixes = [_search_result_to_track(r) for r in results]
    random.shuffle(mixes)
    return jsonify({
        'channel': {'key': channel['key'], 'platform': channel['platform'],
                    'label': channel['label']},
        'mixes': mixes,
        'total': len(mixes),
    })


# ------------------------------------------------------------------
# Media Proxy & Resolution
# ------------------------------------------------------------------
def _is_direct_audio_url(url):
    """True se l'URL è già un file audio diretto (nessun parsing yt-dlp)."""
    return 'bcbits.com' in url or url.lower().endswith(
        ('.mp3', '.m4a', '.aac', '.ogg', '.opus', '.flac')
    )


@app.route('/api/proxy_audio')
def api_proxy_audio():
    """Proxy di STREAMING per l'audio (usato come src da <audio>).

    Il browser streamma da localhost (niente CORS). Se l'URL non è già un
    file audio diretto (es. URL piattaforma incollato), viene prima risolto
    dal MediaResolver per ottenere lo stream diretto. Supporta Range
    (seek nella barra di avanzamento) e passa il Referer per gli host che
    lo richiedono (es. Bandcamp).
    """
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL mancante'}), 400

    # 1) URL di piattaforma → risolvi lo stream diretto (cache resolver 72h
    #    + LRU locale 12h per evitare roundtrip ripetuti)
    if not _is_direct_audio_url(url):
        resolved = None
        with cache_lock:
            entry = audio_url_cache.get(url)
            if entry and time.time() - entry['timestamp'] < 43200:
                resolved = entry['audio_url']
        if not resolved:
            try:
                m_obj = resolver_service.resolve(url)
                if m_obj and m_obj.duration and m_obj.duration <= 45 and detect_platform(url) == 'soundcloud':
                    m_obj = resolver_service.resolve(url, refresh=True)
                if m_obj and m_obj.streams:
                    audio_streams = [s for s in m_obj.streams if s.is_audio_only]
                    resolved = audio_streams[0].url if audio_streams else m_obj.streams[0].url
                if resolved:
                    with cache_lock:
                        audio_url_cache[url] = {'audio_url': resolved, 'timestamp': time.time()}
                        if len(audio_url_cache) > AUDIO_CACHE_SIZE:
                            audio_url_cache.popitem(last=False)
            except Exception as exc:
                return jsonify({'error': f'Impossibile estrarre stream audio: {exc}'}), 500
        if not resolved:
            return jsonify({'error': 'Nessuno stream audio disponibile'}), 500
        url = resolved

    # 2) Proxy streaming: passa i bytes dello stream upstream al client
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://bandcamp.com/',
    }
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header

    # I token degli stream diretti (es. Bandcamp) scadono prima del TTL della
    # cache: in caso di 403/404/410 si ri-risolve l'URL della piattaforma
    # (param ref) forzando il refresh e si riprova con lo stream fresco.
    ref = request.args.get('ref', '').strip()
    candidate = url
    upstream = None
    for attempt in range(2):
        try:
            upstream = requests.get(candidate, headers=headers, stream=True, timeout=30)
        except requests.RequestException as exc:
            return jsonify({'error': f'Impossibile contattare lo stream: {exc}'}), 502
        if upstream.status_code < 400:
            break
        failed_status = upstream.status_code
        upstream.close()
        upstream = None
        if attempt == 0 and ref and failed_status in (403, 404, 410):
            try:
                m_obj = resolver_service.resolve(ref, refresh=True)
                fresh = m_obj.streams[0].url if m_obj and m_obj.streams else None
            except RateLimitedError as exc:
                # Rate limit etico 1/5s per piattaforma: la UI mostra il messaggio
                return jsonify({'error': str(exc), 'retry_after': exc.retry_after}), 429
            except Exception:
                fresh = None
            if fresh and fresh != candidate:
                candidate = fresh
                continue
        return jsonify({'error': f'Stream non disponibile (HTTP {failed_status})'}), failed_status

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    resp = Response(generate(), status=upstream.status_code)
    resp.headers['Content-Type'] = upstream.headers.get('Content-Type', 'audio/mpeg')
    for header in ('Content-Length', 'Content-Range', 'Accept-Ranges',
                   'Content-Disposition', 'Content-Encoding'):
        if upstream.headers.get(header):
            resp.headers[header] = upstream.headers[header]
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ------------------------------------------------------------------
# Bandcamp REST API (album / track) — delegata al MediaResolver isolato
# ------------------------------------------------------------------
def _media_to_track(media):
    """Converte un MediaObject nel formato UI (stesso contratto di
    _search_result_to_track: source/artist/id/type...)."""
    duration = media.duration or 0
    return {
        'id': media.canonical_id,
        'canonical_id': media.canonical_id,
        'title': media.title or 'Senza Titolo',
        'artist': media.uploader or 'Artista Sconosciuto',
        'uploader': media.uploader,
        'source': media.platform,
        'url': media.source_url,
        'thumbnail': media.thumbnail or '',
        'duration': duration,
        'duration_string': f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/D",
        'type': 'track',
    }


def _fetch_bandcamp_extra_info(url):
    """Estrae i blocchi di note ('about') e crediti ('credits') direttamente dalla pagina HTML di Bandcamp."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode('utf-8', errors='replace')

        about_text = ""
        credits_text = ""

        about_match = re.search(r'<div[^>]*class=[^>]*tralbum-about[^>]*>(.*?)</div>', html_content, re.DOTALL)
        if about_match:
            about_text = re.sub(r'<br\s*/?>', '\n', about_match.group(1))
            about_text = re.sub(r'<[^>]*>', '', about_text)
            about_text = html.unescape(about_text).strip()

        credits_match = re.search(r'<div[^>]*class=[^>]*tralbum-credits[^>]*>(.*?)</div>', html_content, re.DOTALL)
        if credits_match:
            credits_text = re.sub(r'<br\s*/?>', '\n', credits_match.group(1))
            credits_text = re.sub(r'<[^>]*>', '', credits_text)
            credits_text = html.unescape(credits_text).strip()

        return about_text, credits_text
    except Exception as e:
        print(f"Failed to fetch extra Bandcamp album info: {e}")
        return "", ""


@app.route('/api/bandcamp/album')
def api_bandcamp_album():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL album mancante'}), 400
    try:
        album, tracks = resolver_service.album(url)
    except ResolverUnavailableError:
        return jsonify({'error': 'Motore di risoluzione non disponibile — riprova tra poco.'}), 503
    except RateLimitedError as exc:
        if exc.retry_after and exc.retry_after <= 3.0:
            time.sleep(exc.retry_after + 0.1)
            try:
                album, tracks = resolver_service.album(url)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        else:
            return jsonify({'error': str(exc), 'retry_after': exc.retry_after}), 429
    except Exception as exc:
        return jsonify({'error': f'Errore album Bandcamp: {exc}'}), 500

    about_text, credits_text = _fetch_bandcamp_extra_info(url)

    return jsonify({
        'album_title': album.title or 'Album senza titolo',
        'artist': album.uploader or 'Artista Sconosciuto',
        'thumbnail': album.thumbnail or '',
        'description': about_text or album.description or '',
        'credits': credits_text or '',
        'tracks': [_media_to_track(t) for t in tracks],
    })


@app.route('/api/bandcamp/track')
def api_bandcamp_track():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL traccia mancante'}), 400
    try:
        media = resolver_service.resolve(url)
    except ResolverUnavailableError:
        return jsonify({'error': 'Motore di risoluzione non disponibile — riprova tra poco.'}), 503
    except RateLimitedError as exc:
        if exc.retry_after and exc.retry_after <= 3.0:
            time.sleep(exc.retry_after + 0.1)
            try:
                media = resolver_service.resolve(url)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        else:
            return jsonify({'error': str(exc), 'retry_after': exc.retry_after}), 429
    except Exception as exc:
        return jsonify({'error': f'Errore traccia Bandcamp: {exc}'}), 500
    stream_url = media.streams[0].url if media.streams else ''
    return jsonify({
        'title': media.title,
        'artist': media.uploader,
        'thumbnail': media.thumbnail,
        'duration': media.duration,
        'stream_url': stream_url,
    })


# ------------------------------------------------------------------
# Favorites & Playlists REST API
# ------------------------------------------------------------------
@app.route('/api/favorites', methods=['GET', 'POST'])
def api_favorites():
    user_id = get_current_user_id()
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM favorites WHERE user_id = ? ORDER BY added_at DESC", (user_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'favorites': rows})

    data = request.json or {}
    track_id = str(data.get('track_id') or data.get('id') or uuid.uuid4().hex)
    title = data.get('title', 'Senza Titolo')
    artist = data.get('artist', '')
    source = data.get('source', 'youtube')
    url = data.get('url', '')
    thumbnail = data.get('thumbnail', '')
    duration = data.get('duration', 0)

    try:
        cursor.execute('''
            INSERT INTO favorites (user_id, track_id, title, artist, source, url, thumbnail, duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, track_id, title, artist, source, url, thumbnail, duration))
        conn.commit()
        return jsonify({'message': 'Aggiunto ai preferiti ️'})
    except sqlite3.IntegrityError:
        return jsonify({'message': 'Brano già presente nei preferiti'})
    finally:
        conn.close()

@app.route('/api/favorites/<track_id>', methods=['DELETE'])
def api_delete_favorite(track_id):
    user_id = get_current_user_id()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM favorites WHERE user_id = ? AND track_id = ?", (user_id, track_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Rimosso dai preferiti'})


# ------------------------------------------------------------------
# Telegram Shared Music Feed REST API
# ------------------------------------------------------------------
@app.route('/api/telegram/feed', methods=['GET'])
def api_telegram_feed():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM telegram_shares ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({'shares': rows})

@app.route('/api/telegram/feed/<int:share_id>', methods=['DELETE'])
def api_delete_telegram_share(share_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM telegram_shares WHERE id = ?", (share_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Elemento rimosso dal feed Telegram'})


@app.route('/api/watch_later', methods=['GET', 'POST'])
def api_watch_later():
    user_id = get_current_user_id()
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM watch_later WHERE user_id = ? ORDER BY added_at DESC", (user_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'watch_later': rows})

    data = request.json or {}
    track_id = str(data.get('track_id') or data.get('id') or uuid.uuid4().hex)
    title = data.get('title', 'Senza Titolo')
    artist = data.get('artist', '')
    source = data.get('source', 'youtube')
    url = data.get('url', '')
    thumbnail = data.get('thumbnail', '')
    duration = data.get('duration', 0)

    try:
        cursor.execute('''
            INSERT INTO watch_later (user_id, track_id, title, artist, source, url, thumbnail, duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, track_id, title, artist, source, url, thumbnail, duration))
        conn.commit()
        return jsonify({'message': 'Aggiunto a Guarda Dopo '})
    except sqlite3.IntegrityError:
        return jsonify({'message': 'Brano già presente in Guarda Dopo'})
    finally:
        conn.close()

@app.route('/api/watch_later/<track_id>', methods=['DELETE'])
def api_delete_watch_later(track_id):
    user_id = get_current_user_id()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM watch_later WHERE user_id = ? AND track_id = ?", (user_id, track_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Rimosso da Guarda Dopo'})


@app.route('/api/playlists', methods=['GET', 'POST'])
def api_playlists():
    user_id = get_current_user_id()
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM playlists WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        playlists = [dict(p) for p in cursor.fetchall()]
        for p in playlists:
            cursor.execute("SELECT COUNT(*) as count FROM playlist_tracks WHERE playlist_id = ?", (p['id'],))
            p['tracks_count'] = cursor.fetchone()['count']
        conn.close()
        return jsonify({'playlists': playlists})

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome playlist obbligatorio'}), 400

    cursor.execute("INSERT INTO playlists (user_id, name) VALUES (?, ?)", (user_id, name))
    playlist_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'message': f"Playlist '{name}' creata", 'id': playlist_id, 'name': name})


# ------------------------------------------------------------------
# Web Radios REST API
# ------------------------------------------------------------------
@app.route('/api/radios', methods=['GET', 'POST'])
def api_radios():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM web_radios ORDER BY id ASC")
        radios = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'radios': radios})

    data = request.json or {}
    name = data.get('name', '').strip()
    stream_url = data.get('stream_url', '').strip()
    genre = data.get('genre', 'Web Radio').strip()
    logo = data.get('logo', '').strip() or 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150'

    if not name or not stream_url:
        return jsonify({'error': 'Nome e URL dello streaming sono obbligatori'}), 400

    try:
        cursor.execute(
            "INSERT INTO web_radios (name, stream_url, genre, logo) VALUES (?, ?, ?, ?)",
            (name, stream_url, genre, logo)
        )
        radio_id = cursor.lastrowid
        conn.commit()
        return jsonify({'message': f"Stazione '{name}' aggiunta", 'id': radio_id})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'URL streaming già esistente'}), 400
    finally:
        conn.close()

@app.route('/api/radios/<int:radio_id>', methods=['DELETE'])
def api_delete_radio(radio_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM web_radios WHERE id = ?", (radio_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Stazione radio rimossa'})

# Helper function to fetch real-time ICY stream titles & show metadata
def fetch_real_radio_metadata(url, station_name=None):
    # 1. Special handling for NTS Live API
    if (station_name and 'NTS' in station_name) or ('ntslive' in url):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request('https://www.nts.live/api/v2/live', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
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
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request('https://pantano.ovh:8444/status-json.xsl', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                src = data.get('icestats', {}).get('source')
                if isinstance(src, list): src = src[0]
                raw_title = src.get('title', '')
                if raw_title:
                    parts = raw_title.split(' --- ')
                    return parts[0].strip()
        except Exception:
            pass

    # 3. Special handling for Radio Firenze Viola daily time-based schedule
    if (station_name and 'Firenze Viola' in station_name) or ('rfviola' in url):
        now = datetime.datetime.now()
        hour = now.hour
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
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={'Icy-MetaData': '1', 'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18'})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
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
                            if 'NTS 1 - ' in val: val = val.replace('NTS 1 - ', '')
                            return val
    except Exception:
        pass

    return None

@app.route('/api/radios/now_playing', methods=['GET'])
def api_radio_now_playing():
    url = request.args.get('url')
    name = request.args.get('name')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    title = fetch_real_radio_metadata(url, name)
    return jsonify({'now_playing': title})

@app.route('/api/radios/<int:radio_id>/details', methods=['GET'])
def api_radio_details(radio_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM web_radios WHERE id = ?", (radio_id,))
    radio = cursor.fetchone()
    conn.close()
    
    if not radio:
        return jsonify({'error': 'Radio not found'}), 404
        
    radio_dict = dict(radio)
    now_playing = fetch_real_radio_metadata(radio_dict['stream_url'], radio_dict['name'])
    radio_dict['now_playing'] = now_playing or "Trasmissione Live in corso"
    
    rfv_schedule = [
        {'time': 'Sito Ufficiale', 'title': 'https://www.radiofirenzeviola.it'},
        {'time': 'In Onda Ora', 'title': now_playing or 'Diretta Viola Talk & News'},
        {'time': '07:00 - 09:00', 'title': 'Buongiorno Firenze (Rassegna Stampa)'},
        {'time': '09:00 - 10:00', 'title': 'C\'è polemica (Il dibattito quotidiano)'},
        {'time': '10:00 - 12:00', 'title': 'Chi si compra? (Calciomercato Viola)'},
        {'time': '12:00 - 14:00', 'title': 'Viola amore mio (Notizie e Interviste)'},
        {'time': '14:00 - 16:00', 'title': 'Palla al centro (Approfondimento RFV)'},
        {'time': '16:00 - 17:00', 'title': 'Nik & Nik (Calciomercato in diretta)'},
        {'time': '17:00 - 19:00', 'title': 'Garrisca al vento (Community Viola)'},
        {'time': '19:00 - 21:00', 'title': 'Stadio Viola (Diretta Serale)'},
        {'time': '21:00 - 07:00', 'title': 'Repliche & Musica Viola'}
    ]

    fango_schedule = [
        {'time': 'Sito Ufficiale', 'title': 'https://www.fangoradio.com'},
        {'time': 'In Onda Ora', 'title': now_playing or 'Trasmissione Fango Radio'},
        {'time': 'Archivio Shows', 'title': 'https://www.fangoradio.com/shows/'}
    ]

    nts_schedule = [
        {'time': 'Sito Ufficiale', 'title': 'https://www.nts.live'},
        {'time': 'In Onda Ora', 'title': now_playing or 'NTS Live London Broadcast'},
        {'time': 'Guida Palinsesto', 'title': 'https://www.nts.live/schedule'}
    ]

    oolong_schedule = [
        {'time': 'Sito Ufficiale', 'title': 'https://oolongradio.com'},
        {'time': 'In Onda Ora', 'title': now_playing or 'Oolong Radio Berlin Live'}
    ]

    schedules = {
        'NTS Radio 1 (London)': nts_schedule,
        'Fango Radio': fango_schedule,
        'Oolong Radio (Berlin)': oolong_schedule,
        'Radio Firenze Viola': rfv_schedule
    }

    radio_dict['schedule'] = schedules.get(radio_dict['name'], [
        {'time': 'In Onda Ora', 'title': now_playing or 'Live Broadcast'},
        {'time': 'Info', 'title': 'Web Radio Live Streaming'}
    ])
    
    return jsonify({'radio': radio_dict})


# ------------------------------------------------------------------
# Custom Channels & Random Mix REST API
# ------------------------------------------------------------------
def _normalize_channel_url(url, platform='youtube'):
    url = url.strip()
    if url.startswith('@'):
        url = f"https://www.youtube.com/{url}"
    if 'youtube.com/@' in url:
        clean = url.rstrip('/')
        if not any(clean.endswith(s) for s in ['/videos', '/shorts', '/streams', '/playlists', '/featured']):
            url = f"{clean}/videos"
    return url


@app.route('/api/channels', methods=['GET', 'POST'])
def api_channels():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM custom_channels ORDER BY id ASC")
        channels = [dict(c) for c in cursor.fetchall()]
        conn.close()
        return jsonify({'channels': channels})

    data = request.json or {}
    raw_url = data.get('url', '').strip()
    label = data.get('label', '').strip()
    platform = data.get('platform', '').strip()

    if not raw_url:
        return jsonify({'error': 'URL o identificatore canale obbligatorio'}), 400

    if not platform:
        platform = detect_platform(raw_url) or 'youtube'

    url = _normalize_channel_url(raw_url, platform)

    if not label:
        parts = [p for p in url.rstrip('/').split('/') if p]
        if parts:
            last = parts[-1]
            if last in ['videos', 'featured', 'playlists', 'streams', 'shorts'] and len(parts) > 1:
                label = parts[-2]
            else:
                label = last
        else:
            label = 'Canale Personalizzato'

    try:
        cursor.execute(
            "INSERT INTO custom_channels (platform, url, label) VALUES (?, ?, ?)",
            (platform, url, label)
        )
        channel_id = cursor.lastrowid
        conn.commit()
        return jsonify({'message': f"Canale '{label}' aggiunto alla lista", 'id': channel_id})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Canale già presente in lista'}), 400
    finally:
        conn.close()

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def api_delete_channel(channel_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Canale rimosso'})


@app.route('/api/random_mix', methods=['GET'])
def api_random_mix():
    channel_id = request.args.get('channel_id', type=int)
    conn = get_db()
    cursor = conn.cursor()

    if channel_id:
        cursor.execute("SELECT * FROM custom_channels WHERE id = ?", (channel_id,))
        channels = [dict(r) for r in cursor.fetchall()]
    else:
        cursor.execute("SELECT * FROM custom_channels")
        channels = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not channels:
        return jsonify({'error': 'Nessun canale salvato per i Mix Random'}), 404

    # Estrazione causale canale
    selected_channel = random.choice(channels)
    platform = selected_channel['platform']
    channel_url = _normalize_channel_url(selected_channel['url'], platform)
    label = selected_channel['label']

    try:
        ydl_opts = {
            'extract_flat': 'in_playlist',
            'playlistend': 40,
            'quiet': True,
            'no_warnings': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            entries = info.get('entries') if info else None

            # Retrying with /videos suffix if handle URL returned empty entries
            if not entries and platform == 'youtube' and not channel_url.endswith('/videos'):
                retry_url = channel_url.rstrip('/') + '/videos'
                info = ydl.extract_info(retry_url, download=False)
                entries = info.get('entries') if info else None

        entries = info.get('entries') if info else None
        if not entries:
            return jsonify({'error': f"Impossibile leggere contenuti da '{label}'"}), 404

        valid_entries = [e for e in entries if e and (e.get('url') or e.get('id'))]
        if not valid_entries:
            return jsonify({'error': f"Nessun brano valido trovato su '{label}'"}), 404

        chosen = random.choice(valid_entries)

        raw_id_or_url = chosen.get('url') or chosen.get('id')
        if not str(raw_id_or_url).startswith('http'):
            if platform == 'youtube':
                track_url = f"https://www.youtube.com/watch?v={raw_id_or_url}"
            else:
                track_url = str(raw_id_or_url)
        else:
            track_url = str(raw_id_or_url)

        title = chosen.get('title') or 'Mix Random'
        uploader = chosen.get('uploader') or chosen.get('channel') or label
        thumbnail = chosen.get('thumbnail') or ''
        if not thumbnail and chosen.get('thumbnails'):
            thumbnail = chosen.get('thumbnails')[-1].get('url', '')
        if not thumbnail:
            thumbnail = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=500'

        duration = chosen.get('duration') or 0

        native_id = chosen.get('id') or native_id_from_url(platform, track_url)
        track_id = f"yt_{native_id}" if platform == 'youtube' and native_id else str(uuid.uuid4().hex)

        return jsonify({
            'track': {
                'id': track_id,
                'title': title,
                'artist': uploader,
                'uploader': uploader,
                'channel_label': label,
                'source': platform,
                'url': track_url,
                'thumbnail': thumbnail,
                'duration': duration,
                'duration_string': f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/D",
                'type': 'track'
            },
            'channel': selected_channel
        })
    except Exception as exc:
        return jsonify({'error': f"Errore estrazione da {label}: {exc}"}), 500


# ------------------------------------------------------------------
# Advanced Download Engine (Loudnorm + Watermark ID3)
# ------------------------------------------------------------------

def run_hybrid_download(job_id, url, title, artist):
    try:
        with soundload_jobs_lock:
            soundload_jobs[job_id]['status'] = 'downloading'
            soundload_jobs[job_id]['message'] = 'Estrazione audio in corso con normalizzazione loudnorm...'

        output_filename = f"{re.sub(r'[\w\s-]', '', title).strip()}.mp3"
        target_path = DOWNLOAD_DIR / output_filename

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(target_path.with_suffix('.%(ext)s')),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'quiet': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Apply ID3 Watermark and loudnorm metadata
        if target_path.exists():
            apply_watermark(
                file_path=target_path,
                user_hash=uuid.uuid4().hex[:8],
                source_url=url,
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                title=title
            )

        with soundload_jobs_lock:
            soundload_jobs[job_id]['status'] = 'completed'
            soundload_jobs[job_id]['percent_val'] = 100.0
            soundload_jobs[job_id]['message'] = 'Download e Watermark completati con successo '
    except Exception as exc:
        with soundload_jobs_lock:
            soundload_jobs[job_id]['status'] = 'failed'
            soundload_jobs[job_id]['message'] = f'Errore: {str(exc)}'
    finally:
        clean_temporary_residues(DOWNLOAD_DIR)

@app.route('/api/soundload/enqueue', methods=['POST'])
def api_soundload_enqueue():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL mancante'}), 400

    job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    title = data.get('title') or url
    artist = data.get('artist') or 'CrossWave Hybrid Engine'

    job_data = {
        "id": job_id,
        "url": url,
        "title": title,
        "artist": artist,
        "status": "pending",
        "percent_val": 0.0,
        "message": "In attesa nella coda del motore ibrido...",
        "created_at": time.time()
    }

    with soundload_jobs_lock:
        soundload_jobs[job_id] = job_data

    soundload_executor.submit(run_hybrid_download, job_id, url, title, artist)
    return jsonify({"status": "success", "job_id": job_id, "message": f"Download di '{title}' avviato nel motore ibrido "})


@app.route('/api/downloads/local')
def api_downloads_local():
    files_list = []
    if DOWNLOAD_DIR.exists():
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for f in sorted(files):
                if f.endswith(('.mp3', '.flac', '.m4a')):
                    full_path = Path(root) / f
                    files_list.append({
                        'filename': f,
                        'artist': 'Libreria Ibrida',
                        'title': f.rsplit('.', 1)[0],
                        'size_mb': round(full_path.stat().st_size / (1024 * 1024), 2)
                    })
    return jsonify({'files': files_list, 'download_dir': str(DOWNLOAD_DIR)})

@app.route('/api/downloads/stream/<path:filename>')
def api_downloads_stream(filename):
    file_path = (DOWNLOAD_DIR / filename).resolve()
    if not file_path.exists() or not str(file_path).startswith(str(DOWNLOAD_DIR)):
        return jsonify({'error': 'File non trovato'}), 404
    return send_file(file_path, mimetype='audio/mpeg')


@app.route('/api/system')
def api_system():
    health = resolver_service.health()
    return jsonify({
        'status': 'online',
        'engine': 'CrossWave Hybrid (Flask UX + Subprocess MediaResolver)',
        'resolver_ok': health.get('ok', False),
        'resolver_version': health.get('resolver_version', 'yt-dlp'),
        'active_jobs': len([j for j in soundload_jobs.values() if j['status'] == 'downloading'])
    })


# ------------------------------------------------------------------
# Main UI Views
# ------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5002))
    debug = os.environ.get("FLASK_DEBUG", "1") != "0"
    print(f"Avvio di CrossWave Hybrid Server su http://localhost:{port} "
          f"(debug={'on' if debug else 'off'} — FLASK_DEBUG=0 per disabilitare reloader)")
    # Il bot Telegram deve partire UNA sola volta. Con il reloader Werkzeug attivo
    # (debug mode) il processo padre NON deve avviare il thread: due poller sullo
    # stesso token causano 409 Conflict e messaggi persi/duplicati.
    if debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("[TelegramBot] Avvio saltato nel processo padre del reloader (debug mode): "
              "il worker partirà nel processo di lavoro.")
    else:
        try:
            start_telegram_bot_thread()
        except Exception as e:
            print(f"[TelegramBot] Errore avvio thread: {e}")
    app.run(debug=debug, host='0.0.0.0', port=port)
