# ⚡ CrossWave Hybrid Player

**CrossWave Hybrid** combina l'interfaccia utente (UX/UI) elegante e ricca di funzionalità di **CrossWave Player** con il potente **motore di risoluzione disaccoppiato e download avanzato di `test2` (Player Cross-Source)**.

---

## 🌟 Caratteristiche Principali

- 🎨 **UX/UI CrossWave**:
  - Interfaccia web moderna con barra di riproduzione persistente, coda dinamica e copertine.
  - App mono-utente locale (nessun login o registrazione richiesta, dati salvati in SQLite `crosswave.db`).
  - Gestione di Preferiti ❤️, "Guarda Dopo" 🕒 e Playlist personalizzate 🎶.
  - Navigatore e riproduttore di file scaricati nella libreria locale.

- 🛡️ **Motore Disaccoppiato `test2` (MediaResolver Subprocess)**:
  - **Isolamento dei processi**: Il parsing di `yt-dlp` per estrarre metadati e stream audio viene eseguito in un **processo separato**. Un blocco o una modifica del parser su YouTube/Vimeo non farà mai crashare il server web Flask.
  - **Cache TTL 72 Ore**: Memorizzazione locale dei metadati per risposte di ricerca istantanee.
  - **5 Piattaforme Supportate**: YouTube, SoundCloud, Bandcamp, Mixcloud e **Vimeo**.
  - **Download Avanzati**: Pipe di estrazione con normalizzazione del volume **loudnorm** ed embedding di **watermark ID3** nei metadati (hash utente, timestamp, URL sorgente).

---

## 🚀 Avvio Rapido

```bash
cd 02_musica_multimedia/crosswave_hybrid
python app.py
```

L'applicazione sarà attiva su: **[http://localhost:5002](http://localhost:5002)**

---

## 🏗️ Architettura Ibrida

```text
crosswave_hybrid/
├── app.py                  # Server principale Flask + REST API + Controller Subprocess Resolver
├── crosswave.db            # Database SQLite (Utenti, Preferiti, Playlist, Guarda Dopo)
├── resolver_cache.db       # Database SQLite Cache TTL 72h per MediaResolver
├── player_engine/          # Motore estratto da test2
│   ├── core/               # MediaObject schema & platform detection (incluso Vimeo)
│   ├── resolver/           # Worker in processo OS separato + ResolverService IPC
│   └── download/           # Pipeline audio (loudnorm + watermark.py ID3)
├── downloader/             # Moduli accessori per pulizia residui temporanei
├── downloads/              # Cartella destinazione per le tracce MP3 scaricate
├── telegram_bot.py         # Worker Bot Telegram (cattura silenziosa link musicali dal gruppo)
├── static/                 # CSS e JS modulare del frontend CrossWave
└── templates/              # Viste HTML Jinja2 (index.html e componenti)
```

---

## 🤖 Integrazione Telegram (opzionale)

Il bot cattura **in silenzio** i **link Bandcamp** incollati nel gruppo e li mostra nella scheda **"Feed Telegram"** dell'app. In chat risponde
solo ai comandi `/lista`, `/cerca <query>`, `/label <etichetta>`.

**Setup in 4 passi:**

1. **Crea il bot** con @BotFather → ottieni il token.
2. **Disattiva la Group Privacy**: @BotFather → `/mybots` → il tuo bot → Bot Settings →
   Group Privacy → **Turn off** (obbligatorio: con la privacy attiva il bot non riceve i link).
3. **Configura il token**: copia `.env.example` in `.env` e inserisci `TELEGRAM_TOKEN`
   (il token non va mai messo nel codice). Opzionale: `TELEGRAM_ALLOWED_CHAT_IDS` per limitare
   le chat autorizzate.
4. **Avvia l'app** (`python app.py`): il worker parte da solo. Aggiungi il bot al gruppo.

Il bot non parte se `TELEGRAM_TOKEN` non è configurato (avviso in console).
