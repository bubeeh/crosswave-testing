#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CrossWave Hybrid Player Server
Combines CrossWave UX with test2's isolated Media Resolver Engine (yt-dlp subprocess),
loudnorm audio normalization, ID3 watermarking, and 5-platform support (YouTube, Bandcamp, SoundCloud, Mixcloud, Vimeo).
"""

import datetime
import gzip
import html
import json
import os
import re
import sqlite3
import ssl
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import httpx
import requests
from flask import Flask, Response, jsonify, render_template, request

# Import test2 player engine modules
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from player_engine.core.errors import (
    RateLimitedError,
    ResolverUnavailableError,
    SearchError,
    SearchRateLimitedError,
    SearchUnsupportedError,
)
from player_engine.core.platforms import PLATFORMS, detect_platform, is_collection_url, native_id_from_url
from player_engine.core.schema import MediaObject, MediaType, compute_canonical_id
from player_engine.recommend import config as rec_config
from player_engine.recommend import identity
from player_engine.recommend.events import infer_event_type
from player_engine.recommend.sources import (
    BandcampSource,
    DiscogsSource,
    LastFmSource,
    MusicBrainzSource,
    SoundCloudSource,
    YouTubeSource,
)
from player_engine.recommend.worker import RecommendationEngine
from player_engine.resolver.rate_limit import RateLimiter
from player_engine.resolver.search import SEARCHABLE_PLATFORMS
from player_engine.resolver.service import ResolverService
from player_engine.storage.db import init_db as init_player_db
from player_engine.storage.repos import (
    ArtistRepo,
    FeedbackRepo,
    HistoryRepo,
    RateLimitRepo,
    SourceCacheRepo,
)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("SECRET_KEY", "crosswave_hybrid_secret_key_2026")

# ------------------------------------------------------------------
# Performance: cache HTTP per gli asset statici + compressione gzip
# ------------------------------------------------------------------
_GZIP_MIN_BYTES = 500

# Content-Security-Policy: hardening pragmatico. `'unsafe-inline'` è necessario
# perché l'app usa handler inline (onerror/onload) e stili inline; il resto è
# ristretto (object/base/form/frame/connect). Le estensioni del browser però
# possono comunque iniettare script (non eliminabili via CSP).
_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'self'; "
    "script-src 'self' 'unsafe-inline' "
    "https://www.youtube.com https://s.ytimg.com https://www.gstatic.com "
    "https://w.soundcloud.com https://widget.mixcloud.com "
    "https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' "
    "https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob: https:; "
    "connect-src 'self'; "
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com "
    "https://w.soundcloud.com https://www.mixcloud.com "
    "https://player-widget.mixcloud.com"
)


def _should_gzip(response) -> bool:
    """Comprime solo risposte in memoria (mai streaming audio) di tipo testo."""
    if request.path.startswith('/api/proxy_audio'):
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

    # L'HTML non va mai messo in cache (il Service Worker fa network-first,
    # ma anche l'HTTP cache del browser eviterebbe l'aggiornamento dei token ?v=)
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        response.headers['Content-Security-Policy'] = _CSP

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

IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

if IS_VERCEL:
    DATA_DIR = Path("/tmp")
    import shutil
    for db_name in ["crosswave.db", "resolver_cache.db"]:
        src_db = BASE_DIR / db_name
        dst_db = DATA_DIR / db_name
        if src_db.exists() and not dst_db.exists():
            try:
                shutil.copy2(src_db, dst_db)
            except Exception as e:
                print(f"Failed copying {db_name} to /tmp: {e}")
else:
    DATA_DIR = BASE_DIR

DB_PATH = DATA_DIR / "crosswave.db"
RESOLVER_DB_PATH = DATA_DIR / "resolver_cache.db"
# Override per i test (CROSSWAVE_USER_DB): evita di toccare il DB reale.
USER_DB_PATH = Path(os.environ.get("CROSSWAVE_USER_DB") or (DATA_DIR / "user.db"))

# Initialize Isolated Subprocess Media Resolver Engine (in-process for Vercel).
# CROSSWAVE_SKIP_RESOLVER=1 evita di avviare il worker (solo per i test).
_resolver_autostart = (not IS_VERCEL) and os.environ.get("CROSSWAVE_SKIP_RESOLVER") != "1"
resolver_service = ResolverService(db_path=str(RESOLVER_DB_PATH), autostart=_resolver_autostart)

# Audio Streaming Cache (LRU)
AUDIO_CACHE_SIZE = 500
audio_url_cache = OrderedDict()
cache_lock = threading.Lock()

# Libreria utente locale: cronologia ascolti + raccomandazioni "Per te".
# DB separato (user.db) così la cache del resolver resta isolata.
user_conn = init_player_db(str(USER_DB_PATH))
history_repo = HistoryRepo(user_conn)
artist_repo = ArtistRepo(user_conn)
feedback_repo = FeedbackRepo(user_conn)
recommender = RecommendationEngine(user_conn)
user_db_lock = threading.Lock()

# Fonti esterne di similarità (HTTP pulito, consentito nel processo Flask).
# Degradano silenziosamente se disabilitate (es. senza LASTFM_API_KEY).
_source_cache = SourceCacheRepo(user_conn, ttl_days=rec_config.SIMILARITY_TTL_DAYS)
_source_http = httpx.Client(timeout=15.0)
rec_sources = [
    LastFmSource(
        _source_http,
        cache=_source_cache,
        limiter=RateLimiter(RateLimitRepo(user_conn), interval=0.25),
        api_key=os.environ.get("LASTFM_API_KEY"),
    ),
    MusicBrainzSource(
        _source_http,
        cache=_source_cache,
        limiter=RateLimiter(RateLimitRepo(user_conn), interval=1.0),
        user_agent=os.environ.get("MB_USER_AGENT"),
    ),
    # Fase 2 — fonti di nicchia (degradano silenziosamente se non disponibili)
    SoundCloudSource(),
    BandcampSource(),
    YouTubeSource(resolver_service),
    DiscogsSource(
        _source_http,
        cache=_source_cache,
        limiter=RateLimiter(RateLimitRepo(user_conn), interval=1.0),
        token=os.environ.get("DISCOGS_TOKEN"),
    ),
]


# ------------------------------------------------------------------
# Database Layer
# ------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Rimuovi le vecchie tabelle non più utilizzate
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS favorites")
        cursor.execute("DROP TABLE IF EXISTS favorites_new")
        cursor.execute("DROP TABLE IF EXISTS watch_later")
        cursor.execute("DROP TABLE IF EXISTS watch_later_new")

        # Migrazione/creazione tabella playlists senza user_id
        cursor.execute("PRAGMA table_info(playlists)")
        cols = [col[1] for col in cursor.fetchall()]
        if 'user_id' in cols:
            cursor.execute('''
                CREATE TABLE playlists_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                INSERT INTO playlists_new (id, name, created_at)
                SELECT id, name, created_at FROM playlists
            ''')
            cursor.execute("DROP TABLE playlists")
            cursor.execute("ALTER TABLE playlists_new RENAME TO playlists")
        elif not cols:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                ("NTS Radio 1 (London)", "https://stream-relay-geo.ntslive.net/stream", "Underground & Experimental", "/static/icons/placeholder.svg"),
                ("Fango Radio", "https://pantano.ovh:8444/pantano", "Experimental & Independent", "/static/icons/placeholder.svg"),
                ("Oolong Radio (Berlin)", "https://stream.oolongradio.com:8443/live", "Experimental & Sound Art", "/static/icons/placeholder.svg"),
                ("Noods Radio (Bristol)", "https://noods-radio.radiocult.fm/stream", "Underground & Experimental", "https://noodsradio.com/images/og-meta-default-image.jpg"),
                ("Radio Firenze Viola", "https://stream.tmwradio.com/rfviola.aac", "Sport & News ACF Fiorentina", "https://www.radiofirenzeviola.it/template/radiofirenzeviola.it/img/1280x720.jpg")
            ]
            cursor.executemany(
                "INSERT INTO web_radios (name, stream_url, genre, logo) VALUES (?, ?, ?, ?)",
                default_radios
            )

        # Migrazione: sostituisci i vecchi logo placeholder remoti (Unsplash)
        # con il placeholder locale (niente dipendenze esterne / niente loop).
        cursor.execute(
            "UPDATE web_radios SET logo='/static/icons/placeholder.svg' "
            "WHERE logo LIKE '%images.unsplash.com%'"
        )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: init_db encountered an exception (likely Vercel read-only DB): {e}")


init_db()


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


def _ui_track_id(platform, url, canonical_id):
    """Id per la UI: l'embed YouTube richiede l'id nativo con prefisso 'yt_'
    (vedi playTrack in player.js), le altre piattaforme usano il canonical_id."""
    native = native_id_from_url(platform, url)
    if platform == 'youtube' and native:
        return f"yt_{native}"
    return canonical_id


def _ui_media_type(platform, url):
    """'album' per le raccolte (Bandcamp album, YouTube playlist, SoundCloud
    set): si aprono nella vista dettaglio con tracklist. Altrimenti 'track'."""
    return 'album' if is_collection_url(platform, url) else 'track'


def _search_result_to_track(result):
    """Mappa un SearchResult (contratto canonico) alla forma attesa dalla UI.

    La UI usa source/artist/id/type; il contratto canonico usa
    platform/uploader/canonical_id. Le raccolte (Bandcamp album, YouTube
    playlist, SoundCloud set) sono marcate type='album' e si aprono nella
    vista dettaglio con tracklist e play-all.
    """
    url = result.url
    platform = result.platform
    duration = result.duration or 0
    return {
        'id': _ui_track_id(platform, url, result.canonical_id),
        'canonical_id': result.canonical_id,
        'title': result.title or 'Senza Titolo',
        'artist': result.uploader or 'Artista Sconosciuto',
        'uploader': result.uploader,
        'source': platform,
        'url': url,
        'thumbnail': result.thumbnail or '',
        'duration': duration,
        'duration_string': f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/D",
        'type': _ui_media_type(platform, url),
        'verified': bool(getattr(result, 'channel_is_verified', False)),
        'is_topic': bool(getattr(result, 'is_topic', False)),
        'catalog_url': getattr(result, 'catalog_url', '') or '',
        'catalog_name': (getattr(result, 'uploader', '') or ''),
    }


def execute_platform_search(source: str, query: str, max_results: int = 50) -> dict:
    """Esegue la ricerca su una singola piattaforma in isolamento.

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


# ------------------------------------------------------------------
# Media Proxy & Resolution
# ------------------------------------------------------------------
def _is_direct_audio_url(url):
    """True se l'URL è già un file audio diretto (nessun parsing yt-dlp)."""
    return 'bcbits.com' in url or url.lower().endswith(
        ('.mp3', '.m4a', '.aac', '.ogg', '.opus', '.flac')
    )


@app.route('/api/resolve_track')
def api_resolve_track():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL mancante'}), 400
    try:
        media = resolver_service.resolve(url)
        yt_id = None
        for tag in media.tags:
            if tag.startswith('yt_fallback:'):
                yt_id = tag.split('yt_fallback:')[-1]
                break

        if not yt_id and media.platform == 'youtube':
            yt_id = native_id_from_url('youtube', media.source_url)

        audio_streams = [s for s in media.streams if s.is_audio_only]
        stream_url = audio_streams[0].url if audio_streams else (media.streams[0].url if media.streams else None)

        return jsonify({
            'title': media.title,
            'artist': media.uploader,
            'duration': media.duration,
            'platform': media.platform,
            'yt_id': yt_id,
            'stream_url': stream_url,
            'is_fallback': bool(yt_id)
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


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
    #    + LRU locale 2h per evitare token CDN scaduti)
    if not _is_direct_audio_url(url):
        resolved = None
        with cache_lock:
            entry = audio_url_cache.get(url)
            if entry and time.time() - entry['timestamp'] < 7200:
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
            upstream = requests.get(candidate, headers=headers, stream=True, timeout=12)
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
def _media_catalog_url(media):
    """Profilo catalogo derivabile da un MediaObject (solo Bandcamp: host)."""
    if media.platform == 'bandcamp' and media.source_url:
        p = urlparse(media.source_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    return ''


def _media_to_track(media):
    """Converte un MediaObject nel formato UI (stesso contratto di
    _search_result_to_track: source/artist/id/type...)."""
    duration = media.duration or 0
    return {
        'id': _ui_track_id(media.platform, media.source_url, media.canonical_id),
        'canonical_id': media.canonical_id,
        'title': media.title or 'Senza Titolo',
        'artist': media.uploader or 'Artista Sconosciuto',
        'uploader': media.uploader,
        'source': media.platform,
        'url': media.source_url,
        'thumbnail': media.thumbnail or '',
        'duration': duration,
        'duration_string': f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/D",
        'type': _ui_media_type(media.platform, media.source_url),
        'catalog_url': _media_catalog_url(media),
        'catalog_name': media.uploader or '',
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


@app.route('/api/collection')
def api_collection():
    """Vista raccolta generica: album Bandcamp, playlist YouTube, set SoundCloud.

    Un unico endpoint per tutte le piattaforme: il worker risolve la raccolta
    (Bandcamp: estrazione completa; YouTube: flat; SoundCloud: API v2) e
    restituisce meta + tracklist già pronti per la vista album e il play-all.
    Per Bandcamp arricchisce con note/crediti dalla pagina.
    """
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL della raccolta mancante'}), 400

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
        return jsonify({'error': f'Errore nel caricamento della raccolta: {exc}'}), 500

    platform = album.platform
    about_text, credits_text = "", ""
    if platform == 'bandcamp':
        about_text, credits_text = _fetch_bandcamp_extra_info(url)

    collection_type = {'bandcamp': 'album', 'youtube': 'playlist', 'soundcloud': 'set'}.get(platform, 'collection')
    return jsonify({
        'album_title': album.title or 'Raccolta senza titolo',
        'artist': album.uploader or 'Artista Sconosciuto',
        'thumbnail': album.thumbnail or '',
        'description': about_text or album.description or '',
        'credits': credits_text or '',
        'platform': platform,
        'collection_type': collection_type,
        'tracks': [_media_to_track(t) for t in tracks],
    })


@app.route('/api/catalog')
def api_catalog():
    """Esplorazione catalogo: discografia di un artista/label Bandcamp o
    le uscite/playlist/upload di un canale YouTube (vista catalogo)."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL del catalogo mancante'}), 400

    platform = (request.args.get('platform') or '').strip() or (detect_platform(url) or '')
    if platform not in ('bandcamp', 'youtube'):
        return jsonify({'error': 'Esplorazione cataloghi disponibile per Bandcamp e YouTube.'}), 400

    topic_hint = request.args.get('topic') in ('1', 'true', 'yes')
    try:
        catalog = resolver_service.catalog(platform, url, topic_hint=topic_hint)
    except ResolverUnavailableError:
        return jsonify({'error': 'Motore di risoluzione non disponibile — riprova tra poco.'}), 503
    except Exception as exc:
        return jsonify({'error': f'Errore nel caricamento del catalogo: {exc}'}), 500

    return jsonify({'catalog': catalog})


@app.route('/api/related')
def api_related():
    """Tracce suggerite per il brano corrente (player desktop "Suggeriti").

    YouTube: usa il Mix del video (`op: related`). Altrimenti (o come fallback)
    cerca su YouTube a partire da artista/titolo. Ritorna link leggeri UI.
    """
    url = request.args.get('url', '').strip()
    source = (request.args.get('source') or '').strip().lower()
    title = request.args.get('title', '').strip()
    artist = request.args.get('artist', '').strip()
    try:
        limit = min(20, max(1, int(request.args.get('limit', 10))))
    except (TypeError, ValueError):
        limit = 10

    items = []
    if (source == 'youtube' or detect_platform(url) == 'youtube') and url:
        video_id = native_id_from_url('youtube', url)
        if video_id:
            try:
                results = resolver_service.related(video_id, limit)
                items = [_search_result_to_track(r) for r in results]
            except Exception:
                items = []

    if not items:
        query = artist or title
        if query:
            try:
                results = resolver_service.search('youtube', query)
                items = [_search_result_to_track(r) for r in results[:limit]]
            except Exception:
                items = []

    return jsonify({'items': items})


# ------------------------------------------------------------------
# Favorites & Playlists REST API
# ------------------------------------------------------------------
@app.route('/api/playlists', methods=['GET', 'POST'])
def api_playlists():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM playlists ORDER BY created_at DESC")
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

    cursor.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
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
    logo = data.get('logo', '').strip() or '/static/icons/placeholder.svg'

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

# Web Radio ICY Metadata TTL Cache (45 seconds)
_RADIO_META_CACHE = {}
_RADIO_META_LOCK = threading.Lock()
_RADIO_META_TTL = 45.0  # seconds

def fetch_real_radio_metadata(url, station_name=None):
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

def _fetch_real_radio_metadata_uncached(url, station_name=None):
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


@app.route('/api/system')
def api_system():
    health = resolver_service.health()
    return jsonify({
        'status': 'online',
        'engine': 'CrossWave Hybrid (Flask UX + Subprocess MediaResolver)',
        'resolver_ok': health.get('ok', False),
        'resolver_version': health.get('resolver_version', 'yt-dlp'),
    })


# ------------------------------------------------------------------
# "Per te": cronologia ascolti + raccomandazioni precomputate
# ------------------------------------------------------------------
def _media_from_ui_track(track):
    """Costruisce un MediaObject minimale dal payload UI (senza ri-risolvere)."""
    track = track or {}
    url = str(track.get('url') or '').strip()
    platform = str(track.get('source') or track.get('platform') or '').strip().lower()
    if platform not in PLATFORMS:
        platform = detect_platform(url) or platform
    if not url or platform not in PLATFORMS:
        return None
    uploader = str(track.get('artist') or track.get('uploader') or '')
    tags = [platform]
    if uploader:
        tags.append(f"artist:{uploader}")
    return MediaObject(
        canonical_id=track.get('canonical_id') or compute_canonical_id(platform, None, url),
        platform=platform,
        source_url=url,
        title=str(track.get('title') or 'Senza Titolo'),
        uploader=uploader,
        duration=float(track.get('duration') or 0.0),
        thumbnail=str(track.get('thumbnail') or ''),
        media_type=MediaType.VIDEO if platform in ('youtube', 'vimeo') else MediaType.AUDIO,
        tags=tags,
    )


@app.route('/api/play', methods=['POST'])
def api_play():
    """Registra un evento di ascolto esteso e aggiorna le raccomandazioni.

    Retrocompatibile: {track, seconds} resta valido. Campi opzionali:
    completion (0..1), event_type (complete|half|partial|skip|replay|...), artist.
    """
    data = request.json or {}
    try:
        seconds = float(data.get('seconds') or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return jsonify({'error': 'seconds non valido'}), 400

    track = data.get('track') or {}
    media = _media_from_ui_track(track)
    if media is None:
        return jsonify({'error': 'Traccia non valida'}), 400

    try:
        completion = max(0.0, min(1.0, float(data.get('completion') or 0)))
    except (TypeError, ValueError):
        completion = 0.0
    event_type = infer_event_type(seconds, completion, data.get('event_type'))
    artist_name = str(data.get('artist') or track.get('artist') or track.get('uploader') or '').strip()

    try:
        with user_db_lock:
            artist_id = None
            if artist_name:
                ref = identity.resolve_local(artist_repo, artist_name,
                                             platform=media.platform, url=media.source_url)
                artist_id = ref.artist_id if ref else None
            history_repo.record_event(media, seconds, event_type=event_type,
                                      completion=completion, artist_id=artist_id)
            recommender.recompute()
    except Exception as exc:
        return jsonify({'error': f"Impossibile registrare l'ascolto: {exc}"}), 500
    return jsonify({'status': 'ok', 'event_type': event_type})


@app.route('/api/recommendations', methods=['GET'])
def api_recommendations():
    """Artisti consigliati: mode=close|scene|mixed, explore=0..1, limit."""
    mode = (request.args.get('mode') or rec_config.DEFAULT_MODE).strip().lower()
    if mode not in rec_config.MODES:
        mode = rec_config.DEFAULT_MODE
    try:
        explore = float(request.args.get('explore', rec_config.DEFAULT_EXPLORE))
    except (TypeError, ValueError):
        explore = rec_config.DEFAULT_EXPLORE
    try:
        limit = min(50, max(1, int(request.args.get('limit', 30))))
    except (TypeError, ValueError):
        limit = 30
    with user_db_lock:
        items = recommender.recommend(mode=mode, explore=explore, limit=limit, sources=rec_sources)
    return jsonify({'items': items, 'mode': mode})


@app.route('/api/recommendations/feedback', methods=['POST'])
def api_recommendations_feedback():
    """Feedback esplicito su un artista: like | dislike | hide."""
    data = request.json or {}
    artist = str(data.get('artist') or '').strip()
    action = str(data.get('action') or '').strip().lower()
    if not artist or action not in ('like', 'dislike', 'hide'):
        return jsonify({'error': 'artist e action (like|dislike|hide) obbligatori'}), 400
    try:
        with user_db_lock:
            ref = identity.resolve_local(artist_repo, artist)
            feedback_repo.add(ref.name_norm, action, ref.artist_id if ref else None)
            if action in ('dislike', 'hide'):
                recommender.recompute()
    except Exception as exc:
        return jsonify({'error': f'Impossibile salvare il feedback: {exc}'}), 500
    return jsonify({'status': 'ok'})


@app.route('/api/recommendations/seeds', methods=['POST'])
def api_recommendations_seeds():
    """Seed manuali per il cold start: {artists: [nome, ...]}."""
    data = request.json or {}
    names = data.get('artists')
    if not isinstance(names, list):
        return jsonify({'error': 'artists deve essere una lista di nomi'}), 400
    stored: list[str] = []
    try:
        with user_db_lock:
            for raw in names[:50]:
                name = str(raw or '').strip()
                if not name:
                    continue
                ref = identity.resolve_local(artist_repo, name)
                if ref:
                    feedback_repo.add(ref.name_norm, 'seed', ref.artist_id)
                    stored.append(ref.name_norm)
    except Exception as exc:
        return jsonify({'error': f'Impossibile salvare i seed: {exc}'}), 500
    return jsonify({'status': 'ok', 'seeds': stored})


@app.route('/api/recommendations/forget', methods=['POST'])
def api_recommendations_forget():
    """Privacy: azzera cronologia estesa, raccomandazioni e feedback.

    La cache di similarità (artists/artist_similarity) NON viene toccata:
    non contiene dati personali.
    """
    with user_db_lock:
        history_repo.forget_all()
        feedback_repo.clear()
    return jsonify({'status': 'ok'})


# ------------------------------------------------------------------
# Main UI Views
# ------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/sw.js')
def service_worker():
    # Servito dalla root per permettere al Service Worker di controllare l'intero origin.
    resp = app.send_static_file('sw.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5002))
    debug = os.environ.get("FLASK_DEBUG", "1") != "0"
    print(f"Avvio di CrossWave Hybrid Server su http://localhost:{port} "
          f"(debug={'on' if debug else 'off'} — FLASK_DEBUG=0 per disabilitare reloader)")
    app.run(debug=debug, host='0.0.0.0', port=port)
