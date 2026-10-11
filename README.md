# ⚡ CrossWave Hybrid Player

**CrossWave Hybrid** unisce l'interfaccia di **CrossWave Player** con il motore di risoluzione disaccoppiato (**MediaResolver** su `yt-dlp`): ricerca multi-piattaforma, riproduzione in streaming, viste album/catalogo e raccomandazioni personalizzate ("Per te").

---

## 🌟 Caratteristiche principali

- 🎨 **UX/UI**:
  - Interfaccia web moderna con barra di riproduzione persistente, coda e cronologia.
  - App mono-utente locale (nessun login), dati in SQLite.
  - Playlist personalizzate, Web Radio e code.
  - **Vista album/raccolta** (album Bandcamp, playlist YouTube, set SoundCloud) con tracklist e play-all.
  - **Esplorazione cataloghi**: discografie di artisti/label Bandcamp e uscite dei canali/artisti YouTube.
  - **"Per te"**: suggerimenti precomputati dagli ascolti (engine locale, azzerabile).

- 🛡️ **MediaResolver disaccoppiato**:
  - Il parsing di `yt-dlp` gira in un **processo separato**: un blocco del parser non fa cadere il server Flask.
  - Cache risoluzioni TTL 72h, cache ricerche TTL 30 min, rate limit etico 1/5s per piattaforma.
  - Piattaforme: **YouTube, Bandcamp, SoundCloud, Mixcloud** (Vimeo riconosciuto ma senza ricerca).

---

## 🚀 Avvio rapido

```bash
python app.py
```

App su **[http://localhost:5002](http://localhost:5002)**.

---

## 🏗️ Architettura

```text
crosswave-testing/
├── app.py                  # Server Flask + REST API + controller del resolver
├── crosswave.db            # DB app (playlist, radio, ecc.)
├── resolver_cache.db       # Cache TTL 72h del MediaResolver
├── user.db                 # Cronologia ascolti + raccomandazioni "Per te"
├── player_engine/          # Motore (schema, resolver, cataloghi, storage, recommend)
│   ├── core/               # MediaObject, piattaforme, errori
│   ├── resolver/           # Worker isolato + ResolverService (IPC) + search/catalog
│   ├── storage/            # SQLite (WAL) + repo
│   └── recommend/          # Engine raccomandazioni precomputate
├── static/                 # CSS e JS modulare del frontend (SPA)
└── templates/              # Viste HTML (index + componenti)
```

---

## 🌐 Deploy

- **Vercel**: `vercel.json` (runtime Python). Il resolver gira in-process; i DB in `/tmp` sono effimeri (incluso `user.db`).
- **Docker**: `Dockerfile` + `docker-compose.yml` con volumi per i DB.
