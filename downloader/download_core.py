# -*- coding: utf-8 -*-
"""
Soundload Download Core Engine
Centralizza le funzionalità di download, rilevamento di FFmpeg e opzioni per yt-dlp.
"""

import os
import sys
import re
import shutil
import platform
import subprocess
from pathlib import Path

# Add project root to sys.path to ensure absolute package imports work
_root_dir = Path(__file__).parent.resolve()
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from enum import Enum
from dataclasses import dataclass

class DownloadMode(Enum):
    AUDIO = "audio"
    VIDEO = "video"

@dataclass
class DownloadOptions:
    dest_path: Path
    mode: DownloadMode = DownloadMode.AUDIO
    codec: str = "mp3"
    quality: str = "320"
    resolution: str = "1080p"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    subtitles: bool = False

    @classmethod
    def from_dict(cls, d: dict):
        dest_path = d.get("dest_path")
        mode = d.get("mode", "audio")
        quality = d.get("quality") or d.get("audio_quality", "320")
        if mode == "audio":
            codec = d.get("codec") or "mp3"
        else:
            codec = d.get("codec") or "mp4"
        resolution = d.get("resolution") or d.get("video_res", "1080p")
        
        default_dir = Path(__file__).parent.parent / "downloads"
        return cls(
            dest_path=Path(dest_path) if dest_path else default_dir,
            mode=DownloadMode.AUDIO if mode == "audio" else DownloadMode.VIDEO,
            codec=codec,
            quality=quality,
            resolution=resolution,
            embed_thumbnail=d.get("embed_thumbnail", True),
            embed_metadata=d.get("embed_metadata", True),
            subtitles=d.get("subtitles", False)
        )

def get_local_ffmpeg_path():
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return str(Path(ffmpeg_exe).parent)
    return None

def detect_ffmpeg():
    return get_local_ffmpeg_path() is not None

def get_default_download_dir():
    d = Path(__file__).parent.parent / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d

import yt_dlp


from bandcamp_utils import (
    is_bandcamp_catalog_url,
    is_bandcamp_release_url,
    get_bandcamp_catalog_details,
    download_bandcamp_metadata_and_cover,
    search_bandcamp,
)
from youtube_utils import search_youtube
from soundcloud_utils import search_soundcloud
from mixcloud_utils import search_mixcloud

# ---------- Costruzione Opzioni yt-dlp ----------
def build_ytdl_opts(options: DownloadOptions, item_id: str, progress_callback, log_callback) -> dict:
    dest_path = options.dest_path
    mode = options.mode
    
    outtmpl = {
        "default": str(dest_path / "%(title)s.%(ext)s"),
        "playlist": str(dest_path / "%(playlist_title)s" / "%(title)s.%(ext)s"),
    }
    
    class YtdlpLogger:
        def __init__(self, logger_cb):
            self.logger_cb = logger_cb
        def debug(self, msg):
            # Filtra messaggi di download rumorosi
            if "[download]" not in msg and "[Progress]" not in msg and msg.strip():
                self.logger_cb(msg)
        def info(self, msg):
            if msg.strip():
                self.logger_cb(msg)
        def warning(self, msg):
            if msg.strip():
                self.logger_cb(f"⚠️ Warning: {msg}")
        def error(self, msg):
            if msg.strip():
                self.logger_cb(f"❌ Errore: {msg}")

    def progress_hook(d):
        try:
            status = d.get("status")
            filename = os.path.basename(d.get("filename", "Download..."))
            
            if filename.endswith(".part"):
                filename = filename[:-5]
            elif filename.endswith(".ytdl"):
                filename = filename[:-5]

            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent_val = downloaded / total if total > 0 else 0.0
            
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            
            speed = d.get("speed")
            if speed:
                speed_kb = speed / 1024
                if speed_kb > 1024:
                    speed_str = f"{speed_kb/1024:.1f} MB/s"
                else:
                    speed_str = f"{speed_kb:.0f} KB/s"
            else:
                speed_str = "-- KB/s"

            eta = d.get("eta")
            if eta is not None:
                try:
                    mins, secs = divmod(int(eta), 60)
                    eta_str = f"{mins:02d}:{secs:02d}"
                except (ValueError, TypeError):
                    eta_str = "--:--"
            else:
                eta_str = "--:--"

            progress_data = {
                "id": item_id,
                "filename": filename,
                "percent_val": percent_val,
                "downloaded_mb": downloaded_mb,
                "total_mb": total_mb,
                "speed_str": speed_str,
                "eta_str": eta_str,
                "status": status,
                "raw_dict": d
            }
            progress_callback(progress_data)
        except Exception as e:
            print(f"Errore nel progress hook: {e}", file=sys.stderr)

    local_ffmpeg = get_local_ffmpeg_path()
    ffmpeg_loc = str(local_ffmpeg.parent) if local_ffmpeg.exists() else None

    ydl_opts = {
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "logger": YtdlpLogger(log_callback),
        "quiet": False,
        "no_warnings": False,
        "ignoreerrors": True,
    }
    if ffmpeg_loc:
        ydl_opts["ffmpeg_location"] = ffmpeg_loc

    ffmpeg_ok = detect_ffmpeg()
    if mode == DownloadMode.AUDIO:
        codec = options.codec
        quality = options.quality
        ydl_opts["format"] = "bestaudio/best"
        
        postprocessors = []
        if ffmpeg_ok:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality if codec == "mp3" else "0",
            })
            if options.embed_metadata:
                postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            if options.embed_thumbnail:
                ydl_opts["writethumbnail"] = True
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
        else:
            log_callback("⚠️ FFmpeg non rilevato. Scarico audio nativo senza conversione o tag metadati.")
            
        if postprocessors:
            ydl_opts["postprocessors"] = postprocessors
    else:
        res = options.resolution
        if ffmpeg_ok:
            if res == "best":
                ydl_opts["format"] = "bestvideo+bestaudio/best"
            else:
                height = res.replace("p", "")
                ydl_opts["format"] = f"bestvideo[height<={height}]+bestaudio/best"
            ydl_opts["merge_output_format"] = options.codec
        else:
            log_callback("⚠️ FFmpeg non rilevato. Scarico video pre-sincronizzato (risoluzione limitata).")
            ydl_opts["format"] = "best"
            
        postprocessors = []
        if ffmpeg_ok:
            if options.embed_metadata:
                postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            
            if options.subtitles:
                ydl_opts["writesubtitles"] = True
                ydl_opts["allsubtitles"] = False
                ydl_opts["subtitleslangs"] = ["it", "en"]
                postprocessors.append({"key": "FFmpegEmbedSubtitle"})
                
            if options.embed_thumbnail:
                ydl_opts["writethumbnail"] = True
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
            
        if postprocessors:
            ydl_opts["postprocessors"] = postprocessors
            
    return ydl_opts

def analyze_url_collection(url: str) -> dict:
    """
    Analizza un URL per capire se si tratta di una raccolta (playlist, album, catalogo).
    Restituisce un dizionario con:
    {"is_collection": bool, "title": str, "type": str, "items": [{"title": str, "url": str}]}
    """
    import yt_dlp
    from urllib.parse import urlparse
    from bandcamp_utils import is_bandcamp_catalog_url, get_bandcamp_catalog_details

    # 1. Caso Catalogo Bandcamp
    if is_bandcamp_catalog_url(url):
        details = get_bandcamp_catalog_details(url)
        if details:
            name, links = details
            if links:
                items = []
                for link in links:
                    url_path = urlparse(link).path
                    item_title = url_path.split("/")[-1].replace("-", " ").title()
                    items.append({"title": item_title, "url": link})
                return {
                    "is_collection": True,
                    "title": f"Catalogo di {name}",
                    "type": "catalogo",
                    "items": items
                }

    # 2. Caso Generico (playlist, album Bandcamp/SoundCloud/YouTube)
    try:
        ydl_opts = {
            'extract_flat': True,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        if info and ('entries' in info) and info['entries']:
            entries = info['entries']
            if len(entries) > 1:
                title = info.get("title") or "Raccolta"
                items = []
                for idx, entry in enumerate(entries):
                    if entry:
                        entry_title = entry.get("title") or f"Elemento {idx+1}"
                        entry_url = entry.get("url")
                        if not entry_url:
                            entry_id = entry.get("id")
                            if entry_id:
                                entry_url = f"https://www.youtube.com/watch?v={entry_id}"
                        if entry_url and not entry_url.startswith("http"):
                            if len(entry_url) == 11:
                                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
                            else:
                                parsed_orig = urlparse(url)
                                entry_url = f"{parsed_orig.scheme}://{parsed_orig.netloc}{entry_url}"
                                
                        if entry_url:
                            items.append({"title": entry_title, "url": entry_url})
                
                if len(items) > 1:
                    return {
                        "is_collection": True,
                        "title": title,
                        "type": "raccolta",
                        "items": items
                    }
    except Exception as e:
        print(f"Errore analisi raccolta: {e}")
        
    return {"is_collection": False, "title": "", "type": "", "items": []}

# ---------- Motore di Download Singolo ----------
def download_single_item_core(item_id: str,
                              url: str,
                              options: DownloadOptions,
                              log_callback,
                              progress_callback,
                              enqueue_callback) -> bool:
    """
    Esegue il download di un singolo URL (standard o Bandcamp).
    Restituisce True se ha successo, solleva un'eccezione in caso di errore.
    """
    # Rilevamento catalogo Bandcamp
    if is_bandcamp_catalog_url(url):
        log_callback(f"🔍 Rilevato URL catalogo Bandcamp: {url}")
        log_callback("⏳ Recupero informazioni sul catalogo...")
        details = get_bandcamp_catalog_details(url)
        if details:
            name, links = details
            if links:
                log_callback(f"✓ Trovato catalogo di '{name}' con {len(links)} elementi.")
                # Segnala all'interfaccia che questo elemento è stato espanso
                progress_callback({
                    "id": item_id,
                    "filename": f"Catalogo: {name}",
                    "percent_val": 1.0,
                    "downloaded_mb": 0.0,
                    "total_mb": 0.0,
                    "speed_str": "",
                    "eta_str": "",
                    "status": "expanded",
                    "title": f"Catalogo: {name} (Espanso in {len(links)} elementi)"
                })
                # Accoda i singoli link
                for idx, link in enumerate(links):
                    enqueue_callback(link, f"[{name}] Elemento {idx+1}/{len(links)}")
                return True
            else:
                log_callback("⚠️ Nessun elemento trovato nel catalogo. Tento download singolo.")
        else:
            log_callback("⚠️ Impossibile analizzare il catalogo. Tento download singolo.")

    # Rilevamento rilascio Bandcamp singolo
    if is_bandcamp_release_url(url):
        log_callback(f"   🔎 Analisi cache per: {url}")
        res_metadata = download_bandcamp_metadata_and_cover(url, options.dest_path, "")
        if res_metadata and len(res_metadata) == 3:
            skipped, artist, album = res_metadata
            album_clean = re.sub(r'[\\/*?:"<>|]', '_', album)
            dest_dir = options.dest_path / album_clean
        elif res_metadata and len(res_metadata) == 4:
            skipped, artist, album, dest_dir = res_metadata
        else:
            skipped, artist, album, dest_dir = False, "Unknown Artist", "Unknown Album", options.dest_path

        if skipped:
            log_callback(f"      ✓ Saltato: L'album '{album}' è già presente in locale.")
            progress_callback({
                "id": item_id,
                "filename": f"{artist} - {album}",
                "percent_val": 1.0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "speed_str": "",
                "eta_str": "",
                "status": "finished",
                "title": f"{artist} - {album} (Già presente)"
            })
            return True
        else:
            # Esegue download specifico Bandcamp in sottocartella
            bc_options = DownloadOptions(
                dest_path=dest_dir,
                mode=options.mode,
                codec=options.codec,
                quality=options.quality,
                resolution=options.resolution,
                embed_thumbnail=options.embed_thumbnail,
                embed_metadata=options.embed_metadata,
                subtitles=options.subtitles
            )
            ydl_opts = build_ytdl_opts(bc_options, item_id, progress_callback, log_callback)
            ydl_opts["outtmpl"] = str(dest_dir / "%(title)s.%(ext)s")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                exit_code = ydl.download([url])
                if exit_code != 0:
                    raise Exception("Il download ha restituito codice di errore non zero.")
                return True
    else:
        # URL standard
        ydl_opts = build_ytdl_opts(options, item_id, progress_callback, log_callback)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Scarica ed estrae le informazioni contemporaneamente
            info_dict = ydl.extract_info(url, download=True)
            if not info_dict:
                raise Exception("Impossibile recuperare le informazioni o completare il download.")
            
            # Se è in modalità audio, scrive il file info.txt standardizzato
            is_audio = options.mode == "audio" or (hasattr(options.mode, "value") and options.mode.value == "audio")
            if is_audio:
                try:
                    # Determina la cartella effettiva di salvataggio
                    filepath_str = ydl.prepare_filename(info_dict)
                    # Pulisce estensioni temporanee se presenti nel nome file preparato
                    filepath_str = re.sub(r'\.(part|ytdl|temp)$', '', filepath_str)
                    dest_file_dir = Path(filepath_str).parent
                    dest_file_dir.mkdir(parents=True, exist_ok=True)
                    write_audio_info_txt(info_dict, dest_file_dir, url)
                except Exception as err:
                    log_callback(f"⚠️ Errore durante la creazione del file info: {err}")
            return True

def write_audio_info_txt(info_dict: dict, dest_dir: Path, source_url: str):
    """
    Scrive un file info.txt standardizzato per i download audio.
    Il file inizia con l'URL della sorgente.
    """
    try:
        title = info_dict.get("title") or "Unknown Title"
        artist = info_dict.get("uploader") or info_dict.get("artist") or "Unknown Artist"
        album = info_dict.get("playlist_title") or info_dict.get("album") or ""
        
        upload_date = info_dict.get("upload_date") or ""
        year = upload_date[:4] if len(upload_date) >= 4 else ""
        
        description = info_dict.get("description") or ""
        
        content = f"URL: {source_url}\n"
        content += f"TITLE: {title}\n"
        content += f"ARTIST: {artist}\n"
        if album:
            content += f"ALBUM: {album}\n"
        if year:
            content += f"YEAR: {year}\n"
        content += "\n"
        
        if description:
            content += f"--- INFO ---\n{description.strip()}\n"
            
        title_clean = re.sub(r'[\\/*?:"<>|]', '_', title)
        info_path = dest_dir / f"{title_clean} (info).txt"
        
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Failed to write info file: {e}")

# ---------- Motore di Ricerca Centralizzato ----------
def search_sources_parallel(query: str, sources: list, limit: int = 15) -> list:
    """
    Esegue ricerche parallele in thread separati per tutte le fonti specificate.
    Restituisce una lista unificata di dizionari standardizzati:
    [{"title": ..., "artist": ..., "type": ..., "url": ..., "source": ..., "thumbnail": ...}]
    """
    import threading

    results = []
    lock = threading.Lock()
    threads = []

    def run_search(search_func, *args):
        try:
            res = search_func(*args)
            if res:
                with lock:
                    results.extend(res)
        except Exception as e:
            print(f"Errore durante l'esecuzione di {search_func.__name__}: {e}")

    # Avvia i thread in base alle fonti abilitate
    sources_lower = [s.lower() for s in sources]
    if "bandcamp" in sources_lower:
        t = threading.Thread(target=run_search, args=(search_bandcamp, query))
        threads.append(t)
        t.start()
    if "youtube" in sources_lower:
        t = threading.Thread(target=run_search, args=(search_youtube, query, limit))
        threads.append(t)
        t.start()
    if "soundcloud" in sources_lower:
        t = threading.Thread(target=run_search, args=(search_soundcloud, query, limit))
        threads.append(t)
        t.start()
    if "mixcloud" in sources_lower:
        t = threading.Thread(target=run_search, args=(search_mixcloud, query))
        threads.append(t)
        t.start()

    # Attendi il completamento di tutti i thread
    for t in threads:
        t.join()

    # Ordina per priorità statica: Bandcamp -> SoundCloud -> YouTube -> Mixcloud
    source_priority = {"bandcamp": 0, "soundcloud": 1, "youtube": 2, "mixcloud": 3}
    results.sort(key=lambda x: source_priority.get(x.get("source", "").lower(), 99))

    return results



def clean_temporary_residues(dest_path: Path) -> None:
    """Scansiona e cancella ricorsivamente file temporanei orfani (.part, .ytdl) nella cartella di download."""
    if not dest_path.exists():
        return
    try:
        for path in dest_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in [".part", ".ytdl", ".temp"]:
                try:
                    path.unlink()
                except Exception:
                    pass
    except Exception:
        pass

