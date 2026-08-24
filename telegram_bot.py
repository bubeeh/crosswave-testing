#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CrossWave Hybrid Telegram Bot Worker
Silent capture of BANDCAMP links shared in group chats into CrossWave.
Provides on-demand group commands (/lista, /cerca, /label) without chat spam.

REQUISITI DI SETUP (fondamentali, vedi .env.example e TELEGRAM_PLAN.md):
  1. TELEGRAM_TOKEN deve essere impostato (variabile d'ambiente o file .env nella root del progetto).
     SENZA token il bot NON parte (stampato un avviso all'avvio).
  2. Group Privacy deve essere DISATTIVATA su @BotFather (Bot Settings → Group Privacy → Turn off)
     oppure il bot deve essere admin del gruppo: altrimenti Telegram NON inoltra al bot i
     messaggi normali del gruppo (solo comandi e menzioni) e la cattura silenziosa dei link
     non funzionerà mai.
  3. (Opzionale) TELEGRAM_ALLOWED_CHAT_IDS: lista di chat_id autorizzate separate da virgola.
     Se non impostata, il bot opera in qualunque chat in cui è aggiunto.
"""

import os
import re
import time
import json
import sqlite3
import threading
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "crosswave.db"


# ---------------------------------------------------------------------------
# Logging sicuro (evita UnicodeEncodeError su Windows)
# ---------------------------------------------------------------------------
def _log(msg):
    try:
        print(f"[TelegramBot] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = str(msg).encode('ascii', 'replace').decode('ascii')
        print(f"[TelegramBot] {safe}", flush=True)


# ---------------------------------------------------------------------------
# Configurazione (da variabili d'ambiente o file .env nella root del progetto)
# ---------------------------------------------------------------------------
def _load_dotenv():
    """Mini caricatore .env senza dipendenze esterne (Flask non lo fa da solo)."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
    except Exception as e:
        _log(f"Errore lettura .env: {e}")


_load_dotenv()

# Token da variabili d'ambiente o file .env
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

# Whitelist opzionale di chat_id (gruppi o DM) autorizzati
ALLOWED_CHAT_IDS = {
    cid.strip() for cid in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if cid.strip()
}

# Piattaforma abilitata per la cattura: SOLO Bandcamp (decisione 23/08/2026).
# Per riattivare altre piattaforme basta riallargare la regex
# (es. aggiungere youtube\.com|youtu\.be|soundcloud\.com|mixcloud\.com).
LINK_REGEX = re.compile(
    r'https?://(?:[a-zA-Z0-9-]+\.)?bandcamp\.com[^\s>"]+',
    re.IGNORECASE
)

# YouTube video id (per thumbnail di alta qualità senza scraping)
YT_ID_REGEX = re.compile(r'(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})', re.IGNORECASE)

# YouTube canale/profilo (URL di canale, non video)
YT_CHANNEL_REGEX = re.compile(r'youtube\.com/(?:@[\w.-]+|c/[\w.-]+|channel/[\w-]+|user/[\w.-]+)', re.IGNORECASE)

# Parametri di tracking da rimuovere dai link salvati (?si=, ?feature=, utm_*, ...)
TRACKING_PARAMS = {'si', 'feature', 'fbclid', 'igshid', 'spm', 'utm_source', 'utm_medium',
                   'utm_campaign', 'utm_term', 'utm_content', 't'}


def clean_share_url(url):
    """Rimuove i parametri di tracking (es. ?si=...) dal link prima del salvataggio."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        keep = {k: v[0] for k, v in parse_qs(parsed.query).items() if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(keep, doseq=True) if keep else ''
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


def is_chat_allowed(chat_id):
    """Se la whitelist è configurata, accetta solo le chat autorizzate."""
    if not ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in ALLOWED_CHAT_IDS


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_telegram_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telegram_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            artist TEXT,
            label TEXT,
            release_date TEXT,
            platform TEXT,
            thumbnail TEXT,
            sender_name TEXT,
            sender_username TEXT,
            chat_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Estrazione metadati
# ---------------------------------------------------------------------------
def _fetch_oembed(url, platform):
    """Prova l'endpoint oEmbed della piattaforma: leggero e affidabile."""
    oembed_endpoints = {
        'youtube': f'https://www.youtube.com/oembed?url={quote(url, safe="")}&format=json',
        'soundcloud': f'https://soundcloud.com/oembed?url={quote(url, safe="")}&format=json',
        'mixcloud': f'https://www.mixcloud.com/oembed/?url={quote(url, safe="")}&format=json',
    }
    endpoint = oembed_endpoints.get(platform)
    if not endpoint:
        return None
    try:
        res = requests.get(endpoint, timeout=8)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def extract_bandcamp_metadata(url):
    """Estrae metadati ricchi da Bandcamp (Titolo, Artista, Label, Data Uscita, Copertina)"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, 'html.parser')
        metadata = {
            'title': '',
            'artist': '',
            'label': '',
            'release_date': '',
            'thumbnail': '',
            'platform': 'bandcamp'
        }

        # 1. Parsing LD+JSON se presente
        ld_script = soup.find('script', type='application/ld+json')
        if ld_script and ld_script.string:
            try:
                ld_data = json.loads(ld_script.string)
                metadata['title'] = ld_data.get('name', '')
                if isinstance(ld_data.get('byArtist'), dict):
                    metadata['artist'] = ld_data['byArtist'].get('name', '')
                if isinstance(ld_data.get('publisher'), dict):
                    metadata['label'] = ld_data['publisher'].get('name', '')
                elif isinstance(ld_data.get('recordLabel'), dict):
                    metadata['label'] = ld_data['recordLabel'].get('name', '')
                metadata['release_date'] = str(ld_data.get('datePublished') or ld_data.get('dateModified') or '')[:10]
                if isinstance(ld_data.get('image'), str):
                    metadata['thumbnail'] = ld_data['image']
            except Exception:
                pass

        # 2. Fallbacks tramite OpenGraph meta tags
        if not metadata['title']:
            og_title = soup.find('meta', property='og:title')
            if og_title:
                metadata['title'] = og_title.get('content', '')

        if not metadata['thumbnail']:
            og_img = soup.find('meta', property='og:image')
            if og_img:
                metadata['thumbnail'] = og_img.get('content', '')

        if not metadata['artist']:
            og_site = soup.find('meta', property='og:site_name')
            if og_site:
                metadata['artist'] = og_site.get('content', '')

        # Pulizia etichetta/artista
        if not metadata['label']:
            metadata['label'] = metadata['artist'] or 'Self-Released'

        return metadata
    except Exception as e:
        _log(f"Errore parsing Bandcamp ({url}): {e}")
        return None


def extract_generic_metadata(url):
    """Metadati per YouTube / SoundCloud / Mixcloud: oEmbed prima, scraping og: come fallback."""
    platform = 'youtube'
    if 'soundcloud.com' in url:
        platform = 'soundcloud'
    elif 'mixcloud.com' in url:
        platform = 'mixcloud'
    elif 'bandcamp.com' in url:
        platform = 'bandcamp'

    metadata = {
        'title': url,
        'artist': platform.capitalize(),
        'label': 'Single Share',
        'release_date': time.strftime('%Y-%m-%d'),
        'thumbnail': '',
        'platform': platform
    }

    # 0. Canali/profili YouTube: niente oEmbed (accetta solo video) → nome leggibile dall'URL
    if platform == 'youtube':
        m_ch = YT_CHANNEL_REGEX.search(url)
        if m_ch:
            handle = m_ch.group(0).rsplit('/', 1)[-1].lstrip('@')
            metadata['title'] = f"Canale @{handle}"
            metadata['artist'] = 'YouTube Channel'
            return metadata

    # 1. oEmbed: titolo + autore + copertina in una richiesta leggera
    oembed = _fetch_oembed(url, platform)
    if oembed:
        if oembed.get('title'):
            metadata['title'] = oembed['title']
        if oembed.get('author_name'):
            metadata['artist'] = oembed['author_name']
        if oembed.get('thumbnail_url'):
            metadata['thumbnail'] = oembed['thumbnail_url']
    else:
        # 2. Fallback: scraping OpenGraph
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                og_title = soup.find('meta', property='og:title')
                og_img = soup.find('meta', property='og:image')
                if og_title:
                    metadata['title'] = og_title.get('content', url)
                if og_img:
                    metadata['thumbnail'] = og_img.get('content', '')
        except Exception:
            pass

    # 3. Per YouTube: thumbnail di alta qualità dal videoId (affidabile, senza scraping)
    if platform == 'youtube':
        m = YT_ID_REGEX.search(url)
        if m:
            metadata['thumbnail'] = f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"

    return metadata


# ---------------------------------------------------------------------------
# Persistenza
# ---------------------------------------------------------------------------
def save_telegram_share(url, metadata, sender_name, sender_username, chat_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO telegram_shares 
            (url, title, artist, label, release_date, platform, thumbnail, sender_name, sender_username, chat_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            url,
            metadata.get('title') or 'Senza Titolo',
            metadata.get('artist') or 'Artista Sconosciuto',
            metadata.get('label') or 'N/D',
            metadata.get('release_date') or '',
            metadata.get('platform') or 'web',
            metadata.get('thumbnail') or '',
            sender_name,
            sender_username,
            str(chat_id)
        ))
        conn.commit()
        _log(f"Salvato in CrossWave: '{metadata.get('title')}' da {sender_name}")
        return True
    except sqlite3.IntegrityError:
        _log(f"Link già salvato in precedenza: {url}")
        return False
    except Exception as e:
        _log(f"Errore salvataggio DB: {e}")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Comunicazione Telegram
# ---------------------------------------------------------------------------
def send_telegram_message(chat_id, text, reply_to_message_id=None):
    try:
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        if reply_to_message_id:
            payload['reply_to_message_id'] = reply_to_message_id
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=5)
    except Exception as e:
        _log(f"Errore invio messaggio: {e}")


# ---------------------------------------------------------------------------
# Comandi di gruppo
# ---------------------------------------------------------------------------
def handle_telegram_command(chat_id, command, args, message_id):
    cmd = command.lower()
    conn = get_db()
    cursor = conn.cursor()

    if cmd in ('/lista', '/list', '/latest'):
        cursor.execute('SELECT * FROM telegram_shares ORDER BY created_at DESC LIMIT 10')
        rows = cursor.fetchall()
        if not rows:
            send_telegram_message(chat_id, "📻 *Archivio CrossWave Vuoto*\nNessun brano ancora condiviso nel gruppo.", message_id)
            return

        lines = ["📻 *ARCHIVIO MUSICALE DEL GRUPPO (Ultime segnalazioni)*\n"]
        for idx, row in enumerate(rows, 1):
            sender = f"@{row['sender_username']}" if row['sender_username'] else row['sender_name']
            lines.append(f"{idx}. *{row['artist']}* — *{row['title']}*")
            lines.append(f"   🏷️ Label: _{row['label']}_ • 👤 da {sender}")
            lines.append(f"   🔗 [Apri Link]({row['url']})\n")

        lines.append("🎧 _Sfoglia la libreria completa su CrossWave Hybrid!_")
        send_telegram_message(chat_id, "\n".join(lines), message_id)

    elif cmd in ('/cerca', '/search'):
        query = " ".join(args).strip()
        if not query:
            send_telegram_message(chat_id, "💡 *Uso*: `/cerca <nome artista, brano o label>`", message_id)
            return
        cursor.execute('''
            SELECT * FROM telegram_shares 
            WHERE title LIKE ? OR artist LIKE ? OR label LIKE ? OR sender_name LIKE ?
            ORDER BY created_at DESC LIMIT 8
        ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
        rows = cursor.fetchall()
        if not rows:
            send_telegram_message(chat_id, f"🔍 Nessun risultato nell'archivio per *\"{query}\"*.", message_id)
            return

        lines = [f"🔍 *RISULTATI ARCHIVIO PER \"{query}\"*\n"]
        for idx, row in enumerate(rows, 1):
            sender = f"@{row['sender_username']}" if row['sender_username'] else row['sender_name']
            lines.append(f"{idx}. *{row['artist']}* — *{row['title']}* (Label: _{row['label']}_)")
            lines.append(f"   🔗 [Link]({row['url']}) • da {sender}\n")

        send_telegram_message(chat_id, "\n".join(lines), message_id)

    elif cmd == '/label':
        query = " ".join(args).strip()
        if not query:
            send_telegram_message(chat_id, "💡 *Uso*: `/label <nome etichetta>`", message_id)
            return
        cursor.execute('SELECT * FROM telegram_shares WHERE label LIKE ? ORDER BY created_at DESC LIMIT 10', (f'%{query}%',))
        rows = cursor.fetchall()
        if not rows:
            send_telegram_message(chat_id, f"🏷️ Nessuna release trovata per la label *\"{query}\"*.", message_id)
            return

        lines = [f"🏷️ *RELEASE PER LABEL \"{query}\"*\n"]
        for idx, row in enumerate(rows, 1):
            sender = f"@{row['sender_username']}" if row['sender_username'] else row['sender_name']
            lines.append(f"{idx}. *{row['artist']}* — *{row['title']}* (da {sender})")
            lines.append(f"   🔗 [Link]({row['url']})\n")

        send_telegram_message(chat_id, "\n".join(lines), message_id)

    elif cmd in ('/help', '/start'):
        msg = (
            "🤖 *CrossWave Music Collector Bot*\n\n"
            "Ascolto silenziosamente i link musicali (Bandcamp, YouTube, SoundCloud, Mixcloud) condivisi nel gruppo e li organizzo nella web app CrossWave.\n\n"
            "💬 *Comandi gruppo*:\n"
            "• `/lista` — Mostra le ultime 10 release condivise\n"
            "• `/cerca <query>` — Cerca tra i consigliati dagli amici\n"
            "• `/label <etichetta>` — Filtra le release per label"
        )
        send_telegram_message(chat_id, msg, message_id)

    conn.close()


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------
def telegram_bot_poll_loop():
    """Loop di polling HTTP long-polling continuo per il bot Telegram"""
    if not TELEGRAM_TOKEN:
        _log(f"[ATTENZIONE] TELEGRAM_TOKEN non configurato: bot DISATTIVATO. "
              "Crea il file .env (vedi .env.example) con il token di @BotFather.")
        return

    init_telegram_db()
    offset = 0
    _log(f"Worker avviato ed in ascolto (Modalità Silenziosa)...")
    if ALLOWED_CHAT_IDS:
        _log(f"Whitelist chat attiva: {', '.join(sorted(ALLOWED_CHAT_IDS))}")

    consecutive_errors = 0
    while True:
        try:
            url = f"{TELEGRAM_API_URL}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25)

            if res.status_code == 409:
                # Un altro poller usa lo stesso token (es. processo duplicato)
                _log(f"[ATTENZIONE] 409 Conflict: un altro processo sta facendo polling "
                      "sullo stesso token. Verifica che il bot parta una sola volta.")
                time.sleep(10)
                continue

            if res.status_code != 200:
                consecutive_errors += 1
                time.sleep(min(5 * consecutive_errors, 60))
                continue

            data = res.json()
            if not data.get('ok'):
                consecutive_errors += 1
                time.sleep(min(5 * consecutive_errors, 60))
                continue

            consecutive_errors = 0

            for update in data.get('result', []):
                offset = max(offset, update['update_id'] + 1)
                message = update.get('message') or update.get('edited_message')
                if not message:
                    continue

                chat_id = message['chat']['id']
                message_id = message['message_id']
                from_user = message.get('from', {})

                # Ignora i messaggi dei bot (evita loop con il bot stesso)
                if from_user.get('is_bot'):
                    continue

                # Whitelist chat
                if not is_chat_allowed(chat_id):
                    continue

                sender_name = from_user.get('first_name', 'Amico')
                if from_user.get('last_name'):
                    sender_name += f" {from_user.get('last_name')}"
                sender_username = from_user.get('username', '')

                # Gestisce sia il testo normale sia la caption di foto/video/link
                text = message.get('text') or message.get('caption') or ''

                # 1. Gestione comandi espliciti (/lista, /cerca, /label)
                if text.startswith('/'):
                    parts = text.split()
                    cmd = parts[0].split('@')[0]  # Gestisce /lista@bot_name
                    args = parts[1:]
                    handle_telegram_command(chat_id, cmd, args, message_id)
                    continue

                # 2. Cattura Silenziosa dei link (SOLO Bandcamp, vedi LINK_REGEX)
                found_links = LINK_REGEX.findall(text)
                for raw_link in found_links:
                    link = clean_share_url(raw_link)
                    _log(f"Trovato link da {sender_name}: {link}")
                    meta = extract_bandcamp_metadata(link)
                    if meta:
                        save_telegram_share(link, meta, sender_name, sender_username, chat_id)

        except Exception as e:
            consecutive_errors += 1
            _log(f"Eccezione poll: {e}")
            time.sleep(min(3 * consecutive_errors, 60))


def start_telegram_bot_thread():
    """Avvia il worker in un thread daemon (chiamato da app.py)."""
    if not TELEGRAM_TOKEN:
        _log(f"[ATTENZIONE] TELEGRAM_TOKEN non configurato: bot DISATTIVATO. "
              "Crea il file .env (vedi .env.example) con il token di @BotFather.")
        return None
    t = threading.Thread(target=telegram_bot_poll_loop, daemon=True)
    t.start()
    return t


if __name__ == '__main__':
    telegram_bot_poll_loop()
