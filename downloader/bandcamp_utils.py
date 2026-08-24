# -*- coding: utf-8 -*-
"""
Bandcamp Utility Module
Fornisce funzioni helper standardizzate per il rilevamento e lo scraping di
pagine catalogo (artisti/label) e singoli rilasci su Bandcamp.
"""

import urllib.request
import urllib.error
import re
import html
from urllib.parse import urljoin, urlparse
from pathlib import Path

def is_bandcamp_catalog_url(url):
    """
    Rileva se un URL corrisponde alla home o alla pagina music di una label/artista su Bandcamp.
    Esclude pagine di singoli album, tracce o feed.
    """
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if 'bandcamp.com' in netloc:
            path = parsed.path.strip('/')
            if netloc != 'bandcamp.com' and netloc != 'www.bandcamp.com':
                if not path.startswith('album') and not path.startswith('track') and not path.startswith('feed'):
                    return True
        return False
    except Exception:
        return False


def is_bandcamp_release_url(url):
    """
    Rileva se un URL corrisponde a un singolo album o una singola traccia su Bandcamp.
    """
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if 'bandcamp.com' in netloc:
            path = parsed.path.strip('/')
            if path.startswith('album') or path.startswith('track'):
                return True
        return False
    except Exception:
        return False


def get_bandcamp_catalog_details(url):
    """
    Estrae il nome dell'artista e tutti i link di album/brani usando la libreria Python yt_dlp.
    Questo rende l'app autosufficiente quando compilata in .exe (non richiede yt-dlp.exe nel PATH).
    """
    if not is_bandcamp_catalog_url(url):
        return None
        
    import yt_dlp
    
    try:
        ydl_opts = {
            'extract_flat': True,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
            
        if not data:
            return None
            
        title = data.get("title") or data.get("playlist_title") or "Unknown Artist"
        
        # Pulisci il titolo del catalogo
        if title.lower().startswith("discography of "):
            title = title[len("discography of "):]
            
        title = re.sub(r'[\\/*?:"<>|]', '_', title).strip()
        
        entries = data.get("entries", [])
        catalog_links = []
        for entry in entries:
            entry_url = entry.get("url")
            if entry_url and entry_url not in catalog_links:
                catalog_links.append(entry_url)
                
        return title, catalog_links
        
    except Exception:
        return None


def check_if_album_downloaded(dest_dir):
    """
    Verifica se la directory dell'album esiste e contiene già dei file audio.
    """
    if not dest_dir.exists() or not dest_dir.is_dir():
        return False
        
    audio_extensions = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.wma'}
    try:
        for file in dest_dir.iterdir():
            if file.is_file() and file.suffix.lower() in audio_extensions:
                return True
    except Exception:
        pass
    return False


def check_if_track_downloaded(dest_dir, track_title):
    """
    Verifica se il file specifico del brano esiste già nella directory dell'album.
    """
    if not dest_dir.exists() or not dest_dir.is_dir():
        return False
        
    track_title_clean = re.sub(r'[\\/*?:"<>|]', '_', track_title)
    audio_extensions = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.wma'}
    try:
        for ext in audio_extensions:
            if (dest_dir / f"{track_title_clean}{ext}").exists():
                return True
    except Exception:
        pass
    return False


def download_bandcamp_metadata_and_cover(url, base_dest_path, catalog_artist_label_name):
    """
    Scarica la copertina ad alta risoluzione (1200x1200px) ed estrae le informazioni
    sul rilascio (info e credits) salvandole in formato testuale (.txt) e immagine (.jpg).
    Restituisce una tupla (skipped, artist, album, dest_dir).
    """
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch metadata page {url}: {e}")
        return False, catalog_artist_label_name if catalog_artist_label_name else "Unknown Artist", "Unknown Release"
        
    artist = None
    track_title = None
    album_title = None
    album_url_path = None
    
    # 1. Rileva il titolo della pagina (che per le tracce contiene il nome del brano, per gli album il nome dell'album)
    og_title_match = re.search(r'<meta property="og:title" content="(.*?)"', html_content)
    if og_title_match:
        parts = og_title_match.group(1).split(', by ')
        if len(parts) == 2:
            track_title = html.unescape(parts[0].strip())
            artist = html.unescape(parts[1].strip())
            
    # Prova a cercare l'album_url_path nel JSON data-tralbum per scaricare la pagina dell'album principale
    tralbum_match = re.search(r'data-tralbum=([\'\u0022])(.*?)\1', html_content)
    if tralbum_match:
        try:
            import json
            tralbum_data = json.loads(html.unescape(tralbum_match.group(2)))
            album_url_path = tralbum_data.get("album_url")
        except Exception:
            pass

    # Se abbiamo un album_url_path (siamo in una traccia di un album), scarichiamo la pagina dell'album
    # per estrarre la copertina dell'album, la descrizione dell'album, i crediti dell'album e la tracklist completa!
    if album_url_path:
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            album_url_absolute = f"{parsed_url.scheme}://{parsed_url.netloc}{album_url_path}"
            
            req_album = urllib.request.Request(
                album_url_absolute, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req_album, timeout=10) as response:
                album_html = response.read().decode('utf-8')
            html_content = album_html
        except Exception as e:
            print(f"Failed to fetch parent album page {album_url_path}: {e}")

    # Ora eseguiamo il parsing sulla pagina dell'album (o sulla pagina della traccia se è un singolo stand-alone)
    # Rilevamento og:title dell'album/singolo
    og_album_match = re.search(r'<meta property="og:title" content="(.*?)"', html_content)
    if og_album_match:
        parts = og_album_match.group(1).split(', by ')
        if len(parts) == 2:
            album_title = html.unescape(parts[0].strip())
            artist = html.unescape(parts[1].strip())

    # Fallback per l'album_title se non rilevato
    if not album_title:
        # 1. Parsing di data-embed JSON (Altamente affidabile nei layout moderni di Bandcamp)
        embed_match = re.search(r'data-embed=([\'\u0022])(.*?)\1', html_content)
        if embed_match:
            try:
                import json
                embed_data = json.loads(html.unescape(embed_match.group(2)))
                val = embed_data.get("album_title")
                if val and val.lower() not in ("null", "undefined", "empty"):
                    album_title = val
            except Exception:
                pass

    # 2. Ricerca della classe fromAlbum nel codice HTML
    if not album_title:
        from_album_match = re.search(r'class=["\']fromAlbum["\'][^>]*>.*?<a[^>]*>(.*?)</a>', html_content, re.DOTALL | re.IGNORECASE)
        if from_album_match:
            album_title = html.unescape(from_album_match.group(1).strip())

    # 3. Parsing del tag JSON-LD (inAlbum)
    if not album_title:
        json_ld_match = re.search(r'"inAlbum"[^}]+"name"\s*:\s*"([^"]+)"', html_content, re.IGNORECASE)
        if json_ld_match:
            album_title = html.unescape(json_ld_match.group(1).strip())

    # 4. Ricerca del JS inline legacy album_title (con sensibilità a apici e virgolette)
    if not album_title:
        album_match = re.search(r'["\']?album_title["\']?\s*:\s*["\'](.*?)["\']', html_content)
        if album_match:
            val = html.unescape(album_match.group(1).strip())
            if val and val.lower() not in ("null", "undefined"):
                album_title = val
            
    if not artist:
        artist_match = re.search(r'artist\s*:\s*["\'](.*?)["\']', html_content)
        if artist_match:
            artist = html.unescape(artist_match.group(1).strip())
            
    # Determina l'album: se fa parte di un album, usa album_title, altrimenti track_title (per singoli stand-alone)
    album = album_title if album_title else track_title
    
    if not album or not artist:
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
        if title_match:
            title_text = html.unescape(title_match.group(1).strip())
            parts = title_text.split(' | ')
            if len(parts) >= 2:
                if not album:
                    album = parts[0].strip()
                if not artist:
                    artist = parts[1].strip()
            else:
                if not album:
                    album = title_text
                if not artist:
                    artist = catalog_artist_label_name
                 
    if not artist:
        artist = catalog_artist_label_name if catalog_artist_label_name else "Unknown Artist"
    if not album:
        album = "Unknown Release"
    if not track_title:
        track_title = album
        
    artist_clean = re.sub(r'[\\/*?:"<>|]', '_', artist)
    album_clean = re.sub(r'[\\/*?:"<>|]', '_', album)
    track_title_clean = re.sub(r'[\\/*?:"<>|]', '_', track_title)
    
    is_track = "/track/" in url
    is_single_track = is_track and not album_title

    # Nome cartella: Nome artista - Nome disco (o Nome artista - Nome singolo per tracce stand-alone)
    folder_name = f"{artist_clean} - {album_clean}"
    
    # Cartella di destinazione per la copertina e info.txt
    if catalog_artist_label_name:
        catalog_artist_label_name_clean = re.sub(r'[\\/*?:"<>|]', '_', catalog_artist_label_name)
        dest_dir = Path(base_dest_path) / catalog_artist_label_name_clean / folder_name
    else:
        dest_dir = Path(base_dest_path) / folder_name
        
    # Controlla se il brano specifico o l'album è già stato scaricato in locale
    is_track = "/track/" in url
    if is_track:
        if check_if_track_downloaded(dest_dir, track_title):
            return True, artist, album, dest_dir
    else:
        if check_if_album_downloaded(dest_dir):
            return True, artist, album, dest_dir
        
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Rilevamento Copertina
    cover_url = None
    cover_match = re.search(r'<link rel="image_src" href="(.*?)"', html_content)
    if cover_match:
        cover_url = cover_match.group(1)
    if not cover_url:
        og_image_match = re.search(r'<meta property="og:image" content="(.*?)"', html_content)
        if og_image_match:
            cover_url = og_image_match.group(1)
            
    if cover_url:
        # Forza risoluzione 1200x1200px (cambiando il suffisso in _10.ext)
        cover_url_high = re.sub(r'_[0-9]+\.(jpg|png|gif)$', r'_10.\1', cover_url)
        
        ext = ".jpg"
        ext_match = re.search(r'\.(jpg|png|gif)', cover_url.lower())
        if ext_match:
            ext = ext_match.group(0)
            
        cover_filename = f"{artist_clean} - {album_clean} (cover){ext}"
        cover_path = dest_dir / cover_filename
        
        # Scarica la copertina solo se non esiste già
        if not cover_path.exists():
            try:
                req_img = urllib.request.Request(
                    cover_url_high,
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req_img, timeout=10) as response:
                    img_data = response.read()
                with open(cover_path, 'wb') as f:
                    f.write(img_data)
            except Exception:
                try:
                    # Fallback se non esiste l'immagine a risoluzione massima
                    req_img = urllib.request.Request(
                        cover_url,
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    with urllib.request.urlopen(req_img, timeout=10) as response:
                        img_data = response.read()
                    with open(cover_path, 'wb') as f:
                        f.write(img_data)
                except Exception as e:
                    print(f"Failed to download cover art for {album}: {e}")
                
    # Estrazione descrizione ("about")
    about_text = ""
    about_match = re.search(r'<div[^>]*class=["\']tralbumData tralbum-about["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
    if not about_match:
        about_match = re.search(r'<div[^>]*class=["\'][^"\']*tralbum-about[^"\']*["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
    if about_match:
        about_text = re.sub(r'<br\s*/?>', '\n', about_match.group(1))
        about_text = re.sub(r'<[^>]*>', '', about_text)
        about_text = html.unescape(about_text).strip()
        
    # Estrazione crediti ("credits")
    credits_text = ""
    credits_match = re.search(r'<div[^>]*class=["\']tralbumData tralbum-credits["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
    if not credits_match:
        credits_match = re.search(r'<div[^>]*class=["\'][^"\']*tralbum-credits[^"\']*["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
    if credits_match:
        credits_text = re.sub(r'<br\s*/?>', '\n', credits_match.group(1))
        credits_text = re.sub(r'<[^>]*>', '', credits_text)
        credits_text = html.unescape(credits_text).strip()
        
    # Estrazione tracce (tracklist)
    tracklist_text = ""
    tracks = re.findall(r'<span[^>]*class=["\']track-title["\'][^>]*>(.*?)</span>', html_content)
    if tracks:
        tracklist_text = "\n".join(f"{idx+1}. {html.unescape(track).strip()}" for idx, track in enumerate(tracks))
    else:
        meta_desc_match = re.search(r'<meta name="description" content="([^"]+)"', html_content, re.DOTALL)
        if meta_desc_match:
            tracklist_text = html.unescape(meta_desc_match.group(1).strip())
            
    # Composizione file info.txt
    info_content = f"URL: {url}\nARTIST: {artist}\nALBUM: {album}\n\n"
    if about_text:
        info_content += f"--- INFO ---\n{about_text}\n\n"
    if credits_text:
        info_content += f"--- CREDITS ---\n{credits_text}\n\n"
    if tracklist_text:
        info_content += f"--- TRACKLIST ---\n{tracklist_text}\n"
        
    # Nome file info.txt unico per il disco o singolo
    info_filename = f"{artist_clean} - {album_clean} (info).txt"
    info_path = dest_dir / info_filename
    
    # Scrivi il file info solo se non esiste già
    if not info_path.exists():
        try:
            with open(info_path, 'w', encoding='utf-8') as f:
                f.write(info_content)
        except Exception as e:
            print(f"Failed to write info file for {album}: {e}")
        
    return False, artist, album, dest_dir


def search_bandcamp(query):
    """
    Cerca su Bandcamp usando l'API autocomplete interna e restituisce
    una lista di risultati standardizzati con titolo, artista, url, copertina, ecc.
    """
    import urllib.request
    import urllib.parse
    import json
    import sys
    
    url = f"https://bandcamp.com/api/fuzzysearch/1/app_autocomplete?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    
    results = []
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        items = data.get('results', []) or []
        for item in items:
            name = item.get('name', 'Unknown')
            band = item.get('band_name')
            item_type = item.get('type')
            item_url = item.get('url')
            img_url = item.get('img')
            if img_url and item_type in ('a', 't'):
                if '/img/' in img_url and not '/img/a' in img_url:
                    img_url = img_url.replace('/img/', '/img/a')
            
            if item_url:
                if item_url.count('https://') > 1:
                    parts = item_url.split('https://')
                    item_url = 'https://' + parts[-1]
                elif item_url.startswith('//'):
                    item_url = 'https:' + item_url
            
            if item_type == 'b':
                title = f"[Artista] {name}"
                release_type = "Artista"
            elif item_type == 'a':
                title = f"{band} - {name} [Album]" if band else f"{name} [Album]"
                release_type = "Album"
            elif item_type == 't':
                title = f"{band} - {name} [Traccia]" if band else f"{name} [Traccia]"
                release_type = "Traccia"
            else:
                title = f"{band} - {name}" if band else name
                release_type = "Rilascio"

            parts = title.split(" - ")
            artist = parts[0] if len(parts) > 1 else "Unknown"
            display_title = parts[1] if len(parts) > 1 else title

            # Rimuovi tag dai nomi display
            display_title = display_title.replace(" [Album]", "").replace(" [Traccia]", "")

            results.append({
                "title": display_title,
                "artist": artist,
                "type": release_type,
                "url": item_url,
                "source": "Bandcamp",
                "thumbnail": img_url
            })
    except Exception as e:
        print(f"Errore ricerca Bandcamp: {e}", file=sys.stderr)
        
    return results

