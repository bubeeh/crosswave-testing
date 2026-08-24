# PIANO DI RISTRUTTURAZIONE FRONTEND — CrossWave Hybrid

> **Stato**: da eseguire · **Target**: refactoring strutturale SPA (nessun cambiamento di funzionalità, nessun cambiamento API backend) · **Lingua UI**: italiana (i messaggi utente restano invariati).

> **AGGIORNAMENTO 23/08/2026**: la restructure è stata **eseguita** (18 moduli ES + partials + hash routing attivi).
> Dopo la restructure è stata aggiunta la feature **"YT: scegli audio o video"**:
> - `player/player.js` → `playTrackWithVideo()` (riga ~183) e rimozione auto-switch a `video-view` nel branch youtube di `playTrack`
> - `views/search.js` → bottone `vd-s` 🎬 in `createResultRow` (righe ~107/145) solo per tracce YT
> - `css/style.css` → regola hover `.track-row-action-btn.vd-s:hover` (~654)
> Le sezioni seguenti restano valide come riferimento; la mappa funzioni è aggiornata implicitamente.

---

## 1. CONTESTO E OBIETTIVO

L'app è un player musicale web a **pagina singola (SPA con tab)** servito da Flask/Jinja2.
Il frontend è concentrato in 3 file monolite:

| File | Righe | Contenuto |
|---|---|---|
| `templates/index.html` | 614 | tutte le 13 sezioni tab + sidebar + player bar + 5 modali + hidden players + script tag |
| `static/js/main.js` | 2847 | 78 funzioni in scope globale: player engine, ricerca, playlist, radio, downloads, home… |
| `static/css/style.css` | 1706 | tutto il CSS, ben commentato per sezioni |

**Obiettivo**: modularizzare senza cambiare comportamento, seguendo 3 mosse:

1. **Splittare `main.js` in moduli ES** per dominio (core, player, views).
2. **Estrarre da `index.html`** player bar, hidden players e modali in partials Jinja.
3. **Aggiungere hash routing** (`#/search`, `#/playlist/...`) per deep-link e back/forward del browser.

**Regola d'oro**: *comportamento attuale = legge*. Il refactoring NON deve cambiare logica, messaggi, ID HTML, endpoint API o stile. I bug pre-esistenti si elencano (sez. 2.3) ma **non si riparano** durante le fasi 1–4; vanno solo conservati. Le correzioni sono confinate nella **Fase 5 (opzionale)**.

---

## 2. STATO ATTUALE (baseline congelata)

### 2.1 Struttura file

```
templates/
├── index.html                       (614 righe — TUTTE le sezioni inline)
└── components/
    ├── view_mix_random.html         (100 righe — featured card mix + canali)
    ├── view_bandcamp.html           (43 righe — album detail view)
    ├── view_downloads.html          (30 righe)
    ├── view_youtube.html            (21 righe — video theater)
    ├── view_soundcloud.html         (15 righe — vista SC, MAI usata da JS)
    └── view_mixcloud.html           (19 righe)
static/js/
├── main.js                          (2847 righe — MONOLITE)
└── views/
    ├── downloads_view.js            (123 righe — ATTIVO, auto-init su DOMContentLoaded)
    ├── bandcamp_view.js             (66 righe — DUPLICATO SHADOWED, morto)
    ├── youtube_view.js              (21 righe — ATTIVO: renderYouTubeView)
    └── mixcloud_view.js             (26 righe — ATTIVO: renderMixcloudView)
static/css/
└── style.css                        (1706 righe)
```

### 2.2 Mappa righe `templates/index.html` (da ri-verificare all'atto dell'edit)

| Righe | Blocco |
|---|---|
| 1–26 | `<head>` (fonts, fontawesome, css, favicon) |
| 28–109 | `<aside class="sidebar">` — logo, nav (data-tab), playlist, user badge, sidebar track card |
| 111–112 | `<main class="main-content">` |
| 113–186 | `#tab-home` (dashboard) |
| 187–243 | `#tab-search` |
| 244–259 | `#tab-web-radio` |
| 260–288 | `#tab-queue-history` |
| 289–314 | `#tab-playlist-detail` |
| 315–325 | `#tab-favorites` |
| 326–336 | `#tab-watch-later` |
| 337–342 | `{% include %}` delle 6 view component (NON toccare) |
| 353–440 | `<footer class="player-bar">` → **estrarre in partial** |
| 442–459 | `#hidden-players-wrapper` (yt placeholder, sc iframe, bc audio) → **estrarre in partial** |
| 461–596 | 5 modali (create-playlist, add-to-playlist, album-tracks, add-radio, radio-detail) + `#toast-container` → **estrarre in partial** |
| 598–608 | script tag: SDK (defer) + views JS + main.js |

### 2.3 Bug pre-esistenti e codice morto (rilevati in analisi — NON riparare in fasi 1–4)

> Questi sono **shadowing di funzioni duplicate** (la definizione successiva vince in scope globale) e **codice orfano**. Il migratore deve **conservare il comportamento attuale** (cioè la definizione che oggi vince) e può eliminare la copia morta solo in Fase 5.

1. **`openBandcampAlbumDetailView` definita 2 volte**:
   - `static/js/main.js:1292` (VINCENTE, usata da `handlePlayAction`)
   - `static/js/views/bandcamp_view.js:2` (MORTA, shadowed — file intero da eliminare in Fase 5)
2. **`sendToSoundload` definita 2 volte in main.js**:
   - riga ~480: POST a `/api/soundload/download` (endpoint INESISTENTE in app.py → MORTA)
   - riga 993: POST a `/api/soundload/enqueue` (VINCENTE, unica da migrare)
3. **`loadRandomMixIfNeeded` e `loadHomeMixRandom` definite 2 volte** (due implementazioni parallele del Mix Random):
   - **Versione A "grid"** (righe 619–740): `mixTabLoaded`, `currentMixChannelKey`, `loadRandomMix` che scrive su `#mix-random-grid`, `#mix-channel-banner`, `#mix-channel-label`, `#mix-channel-count`, `#mix-random-play-btn`, `#mix-random-more-btn` → **nessuno di questi elementi esiste nei template** (verificato con grep) → MORTA per shadowing.
   - **Versione B "featured card"** (righe 2696–2772): `currentRandomMixTrack`, `fetchRandomMix`, `loadChannelsList` → VINCENTE, unica da migrare.
   - Conseguenza attuale (bug live da conservare): la sezione Home "Mix Random" (`#home-mix-random-list`, ESISTE in index.html) **non viene mai popolata** e resta "Caricamento mix casuali...". `createMixCard` (riga 717) e `formatMixDuration` (riga 625) sono usati solo dalla versione A morta.
4. **`playQuickUrl`** (riga 1180): mai chiamata, target `#quick-url-input` inesistente → MORTA.
5. **`openAlbumModal`** (riga 1360): mai chiamata (il modale `#album-tracks-modal` esiste con close/play-all cablati, ma nessuno lo apre) → MORTA.
6. **`renderRecentTracksList`** (riga 2087): chiamata da `addToHistory` e `loadHistoryFromStorage`, ma `#recent-tracks-list` non esiste → no-op con guard `if (!list) return` (conservare la guard).
7. **Elementi referenziati ma inesistenti** (le guard `if (el)` vanno CONSERVATE): `#home-greeting-time`, `#nav-btn-video`, `#quick-url-input`, `#recent-tracks-list`.
8. **`view_soundcloud.html`** esiste ma nessun JS la usa (niente `soundcloud_view.js`); `#sc-view-title`/`#sc-view-artist` mai scritti. Conservare il file (non rompere l'include), non aggiungere logica.
9. **`window.toggleChannelsPanel = scrollToChannelsPanel`** (riga 2758-2759): associazione *volutamente* "sbagliata" (assegna la funzione scroll, non il toggle) — il bottone `#toggle-channels-panel-btn` ha `onclick="scrollToChannelsPanel()"` inline nel template. **Conservare ESATTAMENTE** questa semantica.
10. **`local` source**: `pauseActive`/`resumeActive`/`seekToPercent` gestiscono `activePlayer === 'local'` ma il flusso riproduttivo di `playTrack` non ha un branch `local` (le tracce locali arrivano con `source: 'local'` e… `playTrack` cadrebbe nel ramo di default senza riprodurre nulla — comportamento attuale, conservarlo; `api/downloads/stream` esiste comunque).

---

## 3. DECISIONI ARCHITETTURALI

### 3.1 Cosa SI fa
- **SPA a moduli ES** (`<script type="module">`), niente più scope globale condiviso.
- **State singleton** in `core/state.js` per le variabili condivise tra moduli.
- **Router con registry** (`registerTab`) per evitare dipendenze circolari tra moduli.
- **Hash routing** solo per i tab raggiungibili dalla sidebar; i tab "dinamici" (video-view, album-detail, playlist-detail, soundcloud-view, mixcloud-view) restano navigabili via `switchTab` diretto **senza** cambiare hash (usare `history.replaceState` per non sporcare la history).
- **Partial Jinja** per player bar, hidden players, modali.
- **Swap atomico**: `main.js` viene sostituito da `app.js` in un unico commit/step, non svuotato gradualmente.

### 3.2 Cosa NON si fa
- ❌ Niente MPA (multi-page): il player persistente si fermerebbe a ogni navigazione.
- ❌ Niente modifiche a `app.py`, agli endpoint `/api/*`, al DB, ai template `view_*.html` (tranne i partial estratti da index.html).
- ❌ Niente rinominazioni di ID HTML, classi CSS o messaggi utente.
- ❌ Niente riorganizzazione CSS nelle fasi 1–4 (solo Fase 6 opzionale).
- ❌ Niente "fix" dei bug di sez. 2.3 prima della Fase 5.

---

## 4. STRUTTURA TARGET

```
static/js/
├── app.js                          # entry point: import dei moduli + bootstrap router
├── core/
│   ├── state.js                    # singleton con TUTTE le variabili globali attuali
│   ├── utils.js                    # showToast, formatTime, calculateTotalDuration, getPlatformGradient, escapeHtml
│   └── router.js                   # switchTab (registry), navigate, hashchange, binding nav-btn
├── player/
│   ├── player.js                   # orchestrazione playback + UI player bar (bindings)
│   ├── youtube.js                  # YT iframe API, theater view, polling progresso
│   ├── soundcloud.js               # (la riproduzione SC usa bcAudio+proxy: qui solo init/eventi se servono)
│   ├── bandcamp.js                 # bcAudio HTML5 + streaming proxy (init, play/pause/seek/volume)
│   ├── mixcloud.js                 # widget MC + renderMixcloudView (da views/mixcloud_view.js)
│   └── radio.js                    # radio metadata polling (start/stop)
└── views/
    ├── home.js                     # loadHomeDashboard + quick buttons home
    ├── search.js                   # executeSearch, createResultRow, handlePlayAction + binding ricerca
    ├── library.js                  # preferiti, watch-later, playlist, history, render queue + binding
    ├── radios.js                   # loadWebRadios, openRadioDetailModal + binding modale radio
    ├── mixrandom.js                # fetchRandomMix, loadChannelsList + binding tab mix random
    ├── album.js                    # openBandcampAlbumDetailView, loadAndAddAlbumToQueue, playAllAlbumTracks
    ├── downloads.js                # (copia di downloads_view.js)
    └── soundload.js                # sendToSoundload (solo versione /api/soundload/enqueue)
templates/
├── index.html                      # ridotto: head, sidebar, main (view + include), script tag
└── components/
    ├── player_bar.html             # footer righe 353–440
    ├── hidden_players.html         # righe 442–459
    └── modals.html                 # righe 461–596 (5 modali + toast container)
static/css/style.css                # INVARIATO (fasi 1–4)
```

---

## 5. MAPPA DI MIGRAZIONE (funzione → modulo)

> Numeri di riga riferiti alla baseline; ri-verificare con `grep -n "function X" static/js/main.js` prima di tagliare.

### 5.1 `core/state.js` — da main.js righe 1–22 + sparse

Copiare VERBATIM e convertire in oggetto singleton. Variabili:

```js
// main.js:2-22
queue, currentIndex, history, playlists, activePlayer, currentTrack,
ytPlayer, scWidget, mcWidget, bcAudio,
isPlaying, shuffleMode, repeatMode, currentVolume, ytProgressInterval
// sparse
radioMetadataInterval   (riga 1601)
preMuteVolume           (riga 1774)
pendingTrackToPlaylist  (riga 2326)
currentRandomMixTrack   (riga 2696)
```

```js
export const state = {
  queue: [], currentIndex: -1, history: [], playlists: {},
  activePlayer: null, currentTrack: null,
  ytPlayer: null, scWidget: null, mcWidget: null, bcAudio: null,
  isPlaying: false, shuffleMode: false, repeatMode: 'none', currentVolume: 80,
  ytProgressInterval: null, radioMetadataInterval: null, preMuteVolume: 80,
  pendingTrackToPlaylist: null, currentRandomMixTrack: null
};
```

**Regola di conversione obbligatoria**: ogni riferimento `x` diventa `state.x` (lettura e scrittura). Ogni `x = ...` diventa `state.x = ...`. Esempi già presenti nel codice: `queue = []`, `queue.push(track)`, `currentIndex++`, `shuffleMode = !shuffleMode`, `history.unshift(track)`, `playlists[name] = []`, `activePlayer = track.source`, `currentTrack = track`, `isPlaying = false`, `repeatMode = 'all'`, `currentVolume = val`, `bcAudio.src = ...` → `state.bcAudio.src = ...` (attenzione: NON trasformare `.src`!).

**NON migrare** (codice morto della Versione A, sez. 2.3.3): `mixTabLoaded`, `currentMixChannelKey`, `currentMixChannelLabel`, `currentMixes`, `homeMixChannelKey` (righe 619–623).

`downloadsPollInterval` resta **locale** a `views/downloads.js` (già così oggi).

### 5.2 `core/utils.js` — funzioni pure

| Funzione | Riga main.js |
|---|---|
| `showToast` | 2412 |
| `formatTime` | 2435 |
| `calculateTotalDuration` | 2444 |
| `getPlatformGradient` | 2454 |
| `escapeHtml` | 2462 |

Copia verbatim, aggiungi `export`.

### 5.3 `core/router.js` — routing + switchTab

Da main.js riga 513 (`switchTab`) + binding nav-btn (initUI righe 34–50) + binding `#btn-toggle-queue` (righe 362–371).

Contratto del modulo:

```js
// Registry per evitare cicli di import: le views NON vengono importate qui.
const tabRegistry = {};   // tabId -> { onEnter, onLeave }
export function registerTab(tabId, handlers) { tabRegistry[tabId] = handlers; }

export function switchTab(tabId) { /* comportamento attuale + onEnter/onLeave dal registry */ }

export function navigate(tabId) {
  // se il tab ha una rotta hash -> location.hash = rotta
  // altrimenti -> switchTab(tabId) + history.replaceState(...) (niente back sporco)
}

// hashchange listener -> parse hash -> switchTab + sync classi .nav-btn
// init: al DOMContentLoaded, applica l'hash iniziale (o 'home')
```

**Mappa rotte hash** (solo tab sidebar):
`home→#/home` (default), `search→#/search`, `favorites→#/favorites`, `watch-later→#/watch-later`, `downloads→#/downloads`, `web-radio→#/web-radio`, `mix-random→#/mix-random`, `queue-history→#/queue-history`. **Nessuna rotta** per: `video-view`, `album-detail`, `playlist-detail`, `soundcloud-view`, `mixcloud-view`.

**Sincronizzazione nav**: l'attuale initUI usa `data-tab` su `.nav-btn`; mantenere `querySelectorAll('.nav-btn')` e togglare `.active` in base al tab corrente (NON per id — `#nav-btn-video` e il bottone queue-history senza id non esistono).

**Comportamento switchTab da conservare** (righe 513–540): il vecchio if/else viene sostituito dai `registerTab` registrati dalle views al loro init:

| tab | onEnter | onLeave |
|---|---|---|
| home | `loadHomeDashboard` | — |
| downloads | `startDownloadsPolling` | `stopDownloadsPolling` |
| favorites | `loadFavorites` | — |
| watch-later | `loadWatchLater` | — |
| web-radio | `loadWebRadios` | — |
| mix-random | `loadRandomMixIfNeeded` | — |
| queue-history | `renderQueue(); renderHistory()` | — |
| (tutti gli altri) | — | `stopDownloadsPolling` (come l'else attuale) |

### 5.4 `player/player.js` — orchestrazione + UI player bar

| Funzione | Riga main.js |
|---|---|
| `initAudioPlayers` | 821 |
| `playTrack` | 1471 |
| `playTrackImmediately` | 1785 |
| `pauseAllPlayers` | 1628 |
| `togglePlayPause` | 1658 |
| `pauseActive` | 1668 |
| `resumeActive` | 1687 |
| `seekToPercent` | 1713 |
| `setVolume` | 1742 |
| `toggleMute` | 1775 |
| `setPlayingState` | 1801 |
| `updateProgressBar` | 1816 |
| `updateProgressFill` | 1828 |
| `handleTrackFinished` | 1969 |
| `nextTrack` | 1977 |
| `prevTrack` | 2010 |
| `addToQueue` | 1836 |
| `addPlaylistTracksToQueue` | 1841 |
| **bindings playback** (da initUI) | ctrl-play-pause, ctrl-prev, ctrl-next (307–310); shuffle/repeat (312–338); progress slider (340–350); volume slider + mute (352–360); `#btn-toggle-video` (450–459) |

**Refactoring interno consentito (e auspicato)**: i branch per-sorgente di `playTrack` (youtube/soundcloud/mixcloud/radio/bandcamp) e i rami per-sorgente di `pauseActive`/`resumeActive`/`seekToPercent`/`setVolume` **possono** delegare a funzioni degli adapter (es. `playYoutube(track)`, `pauseYoutube()`, `playBandcampStream(url, ref)`). NON devono cambiare la sequenza logica attuale né i messaggi toast.

Attenzione ai `state.` da applicare: `pauseAllPlayers` tocca `ytPlayer`, `scWidget`, `mcWidget`, `bcAudio` → `state.*`. `playTrack` aggiorna `#player-track-*`, `#sidebar-card-*`, `#player-track-badge`, chiama `addToHistory`, `updateActiveQueueItemRow`, `updateProgressBar`, `getPlatformGradient`, `renderMixcloudView` (import da mixcloud.js), `startRadioMetadataPolling` (import da radio.js).

### 5.5 Adapters player

**`player/youtube.js`** — da main.js:
| Funzione | Riga |
|---|---|
| `window.onYouTubeIframeAPIReady` | 928 (assegnare a TOP-LEVEL del modulo) |
| `onYoutubeStateChange` | 960 |
| `startYoutubeProgressPolling` | 974 |
| `stopYoutubeProgressPolling` | 985 |
| loader IIFE YT API | 2475–2490 (spostare QUI, DOPO l'assegnazione di `window.onYouTubeIframeAPIReady`) |
| `renderYouTubeView` (da `static/js/views/youtube_view.js`) | merge: la logica del theater (main-yt-iframe, video-placeholder, title/artist display) è già dentro `playTrack`; la funzione `renderYouTubeView` del file views diventa il branch youtube di playTrack o una funzione esportata chiamata da player.js. NON tenere entrambe le versioni. |

**`player/bandcamp.js`** — da main.js: branch bandcamp e soundcloud(proxy) di `playTrack` (righe ~1570–1600), rami bandcamp di pause/resume/seek/volume, init `bcAudio` dentro `initAudioPlayers` (righe 857–890: eventi play/pause/ended/timeupdate/error su bcAudio). Esporre: `initBcAudio()`, `playStream(url, ref)`, `pauseBc()`, `resumeBc()`, `seekBc(seconds)`, `setBcVolume(v)`.

**`player/mixcloud.js`** — da main.js `initAudioPlayers` parte Mixcloud (821–856) + **`renderMixcloudView` da `static/js/views/mixcloud_view.js`** (copia verbatim, aggiungi export; usa `state.mcWidget`). Esporre: `initMixcloud()`, `pauseMc()`, `resumeMc()`, `seekMc(percent)`, `setMcVolume(v)`.

**`player/soundcloud.js`** — da main.js `ensureSCPlayer` (890–959). Esporre `ensureSCPlayer()` (usato da player.js se mai necessario). Nota: oggi la riproduzione SC passa da `bcAudio` + `/api/proxy_audio` (vedi playTrack), `ensureSCPlayer` resta per compatibilità.

**`player/radio.js`** — da main.js: `startRadioMetadataPolling` (1609), `stopRadioMetadataPolling` (1602), variabile `radioMetadataInterval` (→ `state.radioMetadataInterval`).

### 5.6 Views

**`views/search.js`** — da main.js:
| Funzione | Riga |
|---|---|
| `executeSearch` | 1025 |
| `createResultRow` | 1102 |
| `handlePlayAction` | 1284 |
| `playQuickUrl` | 1180 → **NON migrare** (morta, sez. 2.3.4; eliminarla in Fase 5) |
| binding ricerca | initUI 52–76 (search-btn, search-input Enter) |
| binding filter pills | initUI 320–346 |

Dipendenze: `createResultRow` usa `addFavoriteTrack`, `addWatchLaterTrack`, `addToQueue`, `openAddToPlaylistModal`, `loadAndAddAlbumToQueue`, `sendToSoundload`, `handlePlayAction`, `escapeHtml`, `formatTime`, `showToast` → import da library.js, player.js, album.js, soundload.js, utils.js.

**`views/album.js`** — da main.js:
| Funzione | Riga |
|---|---|
| `openBandcampAlbumDetailView` | 1292 (l'UNICA — la copia in bandcamp_view.js è morta) |
| `loadAndAddAlbumToQueue` | 1430 |
| `playAllAlbumTracks` | 1448 |
| `openAlbumModal` | 1360 → **NON migrare** (morta) |
| binding `#album-modal-play-all` | initUI 473 |

**`views/library.js`** — da main.js (il modulo più grande):
| Funzione | Riga |
|---|---|
| `renderQueue`, `removeTrackFromQueue`, `clearQueue`, `updateActiveQueueItemRow` | 1857/1910/1936/1949 |
| `addToHistory`, `renderHistory`, `renderRecentTracksList`, `clearHistory` | 2026/2038/2087/2133 |
| `createNewPlaylist`, `renderPlaylists`, `deletePlaylist`, `openPlaylistDetail`, `renderPlaylistSongs`, `removeTrackFromPlaylist`, `openAddToPlaylistModal`, `addTrackToPlaylist` | 2142/2161/2196/2218/2256/2316/2328/2357 |
| `loadPlaylistsFromStorage`, `savePlaylistsToStorage`, `loadHistoryFromStorage`, `saveHistoryToStorage` | 2374/2389/2393/2407 |
| `addFavoriteTrack`, `loadFavorites`, `addWatchLaterTrack`, `loadWatchLater` | 2488/2507/2535/2554 |
| binding clear queue/history | initUI 373–375 |
| binding modali playlist | initUI 377–396 (open/close create-playlist, close add-to-playlist, close album-modal, save-playlist) |
| binding player bar fav/wl/playlist | initUI 399–448 (btn-player-soundload 399, btn-player-fav 411, btn-player-wl 422, btn-player-playlist 433) |

**`views/radios.js`** — da main.js:
| Funzione | Riga |
|---|---|
| `loadWebRadios` | 543 |
| `openRadioDetailModal` | 747 |
| binding modale add-radio | initUI 262–318 |
| binding close radio-detail-modal | initUI ~313–318 |

**`views/mixrandom.js`** — da main.js (SOLO Versione B attiva):
| Funzione | Riga |
|---|---|
| `fetchRandomMix` | 2698 |
| `loadRandomMixIfNeeded` (attiva) | 2761 |
| `loadHomeMixRandom` (attiva) | 2768 |
| `loadChannelsList` | 2777 |
| `scrollToChannelsPanel` | 2752 |
| `window.scrollToChannelsPanel = ...` e `window.toggleChannelsPanel = ...` | 2758–2759 (CONSERVARE identiche — vedi 2.3.9) |
| binding mix random tab + canali | initUI 137–244 |

**NON migrare** (Versione A morta): `formatMixDuration` (625), `createMixCard` (717), `loadRandomMix` (639), `loadRandomMixIfNeeded` (632), `loadHomeMixRandom` (694), variabili righe 619–623.

**`views/home.js`** — da main.js:
| Funzione | Riga |
|---|---|
| `loadHomeDashboard` | 2582 |
| binding home search + quick buttons | initUI 78–135 |
| binding `#home-view-all-radios-btn` e `#home-mix-random-btn` | initUI ~122–260 |

Dipendenze: `loadHomeDashboard` chiama `loadHomeMixRandom` (import da mixrandom.js), `createResultRow` (da search.js), `openRadioDetailModal` (da radios.js), `playTrack` (da player.js), `addFavoriteTrack`/`addWatchLaterTrack` (da library.js). Conservare la guard su `#home-greeting-time` (elemento inesistente).

**`views/downloads.js`** — copia verbatim di `static/js/views/downloads_view.js` (123 righe): `initDownloadsView`, `startDownloadsPolling`, `stopDownloadsPolling`, `fetchDownloadJobs`, `fetchLocalDownloadedFiles`, `downloadsPollInterval`, auto-init su DOMContentLoaded. `fetchLocalDownloadedFiles` usa `createResultRow` (import da search.js) e `escapeHtml` (utils.js). **NON duplicare con main.js** (main.js non ha queste funzioni — verificato, stanno solo nel file views).

**`views/soundload.js`** — da main.js: `sendToSoundload` riga 993 (solo versione `/api/soundload/enqueue`) + binding `#btn-player-soundload` (399–409) + binding `#btn-theater-download` (461–471). **Eliminare** la copia a riga ~480 (endpoint `/api/soundload/download` inesistente).

### 5.7 `app.js` — entry point

```js
// import di TUTTI i moduli (state, utils, router, player, adapter, views)
import './core/state.js';       // side-effect: definisce lo stato
import './core/router.js';
import './player/player.js';
import './player/youtube.js';   // assegna window.onYouTubeIframeAPIReady + carica SDK YT
import './player/bandcamp.js';
import './player/mixcloud.js';
import './player/soundcloud.js';
import './player/radio.js';
import './views/search.js';
import './views/library.js';
import './views/album.js';
import './views/radios.js';
import './views/mixrandom.js';
import './views/home.js';
import './views/downloads.js';
import './views/soundload.js';

// bootstrap: registrazione tab (router.registerTab), init da hash iniziale
```

Niente ordine di caricamento manuale: l'import risolve le dipendenze. Ogni modulo si auto-inizializza con `document.addEventListener('DOMContentLoaded', ...)` per i propri binding (pattern già usato da downloads_view.js). Il router fa il parse dell'hash iniziale e lo switchTab conseguente.

---

## 6. FASI DI IMPLEMENTAZIONE

### FASE 0 — Backup e baseline (obbligatoria, niente git nel progetto)

```bash
mkdir -p _backup_frontend
cp -r templates static _backup_frontend/
cp app.py _backup_frontend/ 2>/dev/null || true
```

Verifica che l'app parta e funzioni PRIMA di toccare nulla:
```bash
python app.py   # → http://localhost:5002
```
**Done**: app funzionante + cartella `_backup_frontend/` presente.

### FASE 1 — Moduli core

1. Creare `static/js/core/state.js` (sez. 5.1).
2. Creare `static/js/core/utils.js` (sez. 5.2) — copie verbatim + `export`.
3. Creare `static/js/core/router.js` (sez. 5.3) con `registerTab`/`switchTab`/`navigate` + hash routing. Per ora `switchTab` può conservare la logica if/else originale copiata da main.js (le registrazioni arriveranno in Fase 2).
4. **Verifica sintassi** su ogni file: `node --check <file>` (se node disponibile; altrimenti aprire in browser più avanti).
5. **NON modificare ancora** main.js né index.html.

**Done**: 3 nuovi file, nessun file esistente modificato, `node --check` pulito.

### FASE 2 — Moduli player

1. Creare `static/js/player/player.js`, `youtube.js`, `bandcamp.js`, `mixcloud.js`, `soundcloud.js`, `radio.js` copiando le funzioni della sez. 5.4–5.5 (verbatim, convertite a `state.x` e con `import/export`).
2. Applicare con cura la **regola di conversione `state.`** (sez. 5.1). Consiglio: dopo la copia, `grep -n "\bqueue\b\|\bcurrentIndex\b\|\bhistory\b\|..."` per trovare i riferimenti rimasti senza `state.`.
3. `node --check` su tutti i file.
4. **NON modificare** main.js né index.html.

**Done**: 6 nuovi file, check pulito.

### FASE 3 — Moduli views

1. Creare `static/js/views/search.js`, `library.js`, `album.js`, `radios.js`, `mixrandom.js`, `home.js`, `downloads.js` (copia di downloads_view.js), `soundload.js` (sez. 5.6).
2. **Registrare i tab** nel router: ogni view al proprio DOMContentLoaded chiama `registerTab('downloads', { onEnter: startDownloadsPolling, onLeave: stopDownloadsPolling })` ecc. (mappa in sez. 5.3).
3. **Conservare le guardie** `if (el)` per gli elementi inesistenti (2.3.7).
4. `node --check` su tutti i file.
5. **NON modificare** main.js né index.html.

**Done**: 8 nuovi file, check pulito.

### FASE 4 — Swap atomico + estrazione partials HTML

1. **HTML**: estrarre da `templates/index.html`:
   - righe 353–440 → `templates/components/player_bar.html` (sostituire con `{% include 'components/player_bar.html' %}`)
   - righe 442–459 → `templates/components/hidden_players.html`
   - righe 461–596 → `templates/components/modals.html` (include il `#toast-container`)
   - Verificare con `diff` visuale che l'HTML estratto sia identico (nessun tag perso).
2. **Script tag**: in `index.html`:
   - RIMUOVERE: `<script src=".../js/main.js">...` e i 4 tag `views/*.js`
   - AGGIUNGERE: `<script type="module" src="{{ url_for('static', filename='js/app.js') }}"></script>` (in coda, dopo gli SDK defer)
3. **Cache busting**: bump `?v=` su style.css e sul nuovo app.js (es. `?v=20260823_restructure`).
4. **Smoke test completo** (sez. 8) — qui si gioca tutto: eventuali `import` mancanti appaiono come errori console.
5. **Rollback possibile in 30 secondi**: ripristinare da `_backup_frontend/`.

**Done**: app funzionante con soli moduli ES; console senza errori; `main.js`, `views/downloads_view.js`, `views/bandcamp_view.js`, `views/youtube_view.js`, `views/mixcloud_view.js` **non più referenziati** (eliminarli SOLO a Fase 5 conclusa).

### FASE 5 — (opzionale) Fix noti e rimozione dead code

Da fare SOLO dopo la Fase 4 verificata, un fix alla volta con test al termine:

1. **Eliminare** `static/js/views/bandcamp_view.js` (duplicato shadowed).
2. **Eliminare** le funzioni morte non migrate: `playQuickUrl`, `openAlbumModal`, la Versione A del Mix Random (`loadRandomMix`, `createMixCard`, `formatMixDuration`, variabili 619–623), `renderRecentTracksList` **se** si decide di non ripristinare `#recent-tracks-list` (oggi è no-op).
3. **Fix candidato (decidere con l'utente prima):** popolare `#home-mix-random-list` (sezione Home Mix Random oggi morta) ripristinando il flusso della vecchia `loadHomeMixRandom` (694): `fetchRandomMix()` → card compact con `createMixCard(mix, label, true)`. Comporta reintrodurre `createMixCard` e `formatMixDuration` da main.js.
4. Ricontrollare che `window.scrollToChannelsPanel`/`window.toggleChannelsPanel` siano ancora esposti.

### FASE 6 — (opzionale) Split CSS

Mappa sezioni già disponibile in `style.css` (commenti `/* ... */`, righe: reset 1–71, glows 72–101, sidebar 102–295, mini-track 296–336, main 337–359, search 360–412, filter 413–458, results 459–499, track-row 500–654, playlists 655–667, playlist-detail 668–714, player-bar 715–793, controls 794–849, seek 850–923, utilities 924–994, modals 995–1121, album-modal 1122–1154, toast 1155–1194, helpers 1195–1214, responsive 1215–1251, video 1252–1325, album-view 1326–1438, fixes 1439–1463, home 1464–1540, quick-actions 1541–1558, downloads 1559–1666, hidden 1667–1671, forms 1672–1706).

Proposta: `css/base.css` (1–101), `css/layout.css` (102–359 + 1215–1251), `css/components.css` (resto). **NON modificare nessun selettore**, solo spostare blocchi. Aggiornare i `<link>` in index.html. Bump `?v=`. Test visivo completo.

---

## 7. REGOLE OBBLIGATORIE (per l'agente esecutore)

1. **Copia verbatim** i corpi delle funzioni; cambia SOLO: aggiunta di `export`/`import`, conversione `x → state.x`, split dei binding di `initUI` per modulo.
2. **Niente logica nuova**. Ogni `if`, messaggio, URL, classe CSS resta identico.
3. **Conversioni `state.` sistematiche** — è la fonte n.1 di bug. Dopo ogni copia: `grep -nE "\b(queue|history|playlists|currentIndex|currentTrack|activePlayer|isPlaying|shuffleMode|repeatMode|currentVolume|ytPlayer|scWidget|mcWidget|bcAudio|ytProgressInterval|radioMetadataInterval|preMuteVolume|pendingTrackToPlaylist|currentRandomMixTrack)\b" <file>` e correggere i riferimenti non prefissati.
4. **Dove NON applicare `state.`**: proprietà di oggetti traccia (es. `track.title`, `radio.id`), `job.*`, `data.*`, `tracks.*`, parametri locali.
5. **I moduli SI auto-inizializzano** con `document.addEventListener('DOMContentLoaded', ...)` in coda al file (pattern di downloads_view.js). Il router viene inizializzato da app.js.
6. **Export solo ciò che serve**: chi importa da altri moduli usa `import { x } from './x.js'` con percorsi RELATIVI al file.
7. **Callback e SDK su `window`** (solo questi, niente altro):
   - `window.onYouTubeIframeAPIReady` (youtube.js, top-level)
   - `window.scrollToChannelsPanel`, `window.toggleChannelsPanel` (mixrandom.js)
8. **Non toccare** `templates/components/view_*.html`, `app.py`, CSS (fino a Fase 6), i messaggi utente.
9. **Ogni fase termina con app avviabile** e, dalla Fase 4, con smoke test passato.
10. **Se un import manca o un simbolo non è trovato**: guardare l'errore console, correggere l'import, NON aggirare con `window.x = ...`.

---

## 8. VERIFICA E TEST

### 8.1 Check statici (dopo ogni fase)

```bash
node --check static/js/app.js && for f in static/js/core/*.js static/js/player/*.js static/js/views/*.js; do node --check "$f" || echo "FAIL $f"; done
# assenza di duplicati (fase 4+):
grep -rn "function openBandcampAlbumDetailView" static/js/          # → 1 sola occorrenza (album.js)
grep -rn "function sendToSoundload" static/js/                      # → 1 sola occorrenza (soundload.js)
grep -rn "function loadRandomMixIfNeeded" static/js/                # → 1 (mixrandom.js)
grep -rn "main.js" templates/index.html                             # → 0 occorrenze
```

### 8.2 Smoke test funzionale (dopo Fase 4 — checklist completa)

Avvio: `python app.py` → http://localhost:5002

1. **Home**: greeting, sezione Web Radio popolata, Preferiti, Watch Later (Mix Random resta placeholder — bug noto, ok).
2. **Ricerca**: cerca "lofi" → risultati da tutte le sorgenti; filtri per pillola; clic play su un risultato YT → switch a video-view e audio parte; pulsanti ❤️/🕒/coda/playlist/freccia download su una riga.
3. **Player bar**: play/pause, prev/next, shuffle, repeat (nessuna/una/tutte), seek, volume, mute, badge sorgente, card sidebar, aggiungi a preferiti/watch-later/playlist dal player.
4. **Queue & History**: aggiungi tracce in coda, rimuovi corrente, svuota coda, cronologia con storico, svuota cronologia; persistenza dopo refresh (localStorage).
5. **Preferiti / Watch Later**: popolati, count corretti, rimozione.
6. **Playlist**: crea (modale), apri da sidebar, riproduci tutto, elimina, aggiungi traccia dal player; persistenza dopo refresh.
7. **Downloads**: apri tab → polling attivo (fetch ogni 2s), avvia download da un brano (☁️), compare il job, file locali elencati; lascia il tab → polling fermo.
8. **Web Radio**: griglia, "Ascolta Live" (stream parte via bcAudio), info/palinsesto, aggiungi stazione custom, elimina (id>10).
9. **Mix Random**: featured card si popola, "Proponi un altro", "Riproduci Ora", "In Coda", "Preferiti", form canali (aggiungi/elimina, estrazione per canale).
10. **Album Bandcamp**: clic su un risultato album → album-detail view con tracce, Riproduci Tutto, Scarica con Soundload.
11. **Routing**: `#/search` al load → tab ricerca; clic nav → hash cambia; back/forward del browser → tab corrispondente; da video-view (no hash) → back torna al tab precedente senza passare da stati intermedi.
12. **Console**: zero errori; `window.scrollToChannelsPanel` definita; `window.onYouTubeIframeAPIReady` assegnata.

### 8.3 Doppio controllo regressioni (confronto pre/post)

- `templates/index.html`: diff del blocco estratti vs partials (deve essere identico).
- Messaggi toast: confrontare i testi prima/dopo (nessun messaggio cambiato).

---

## 9. RISCHI E ROLLBACK

| Rischio | Probabilità | Mitigazione |
|---|---|---|
| Import mancanti in fase 4 (errore console) | Media | Fase 4 è uno swap atomico: errori visibili subito, fix mirato sull'import |
| `state.` dimenticato → ReferenceError/variabile undefined | Media | Regola 3 + grep sistematico dopo ogni copia |
| Doppio binding (main.js + app.js attivi insieme) | Bassa | Swap atomico: main.js rimosso nello stesso step dell'attivazione di app.js |
| Cicli di import (router ↔ views) | Bassa | Registry `registerTab` nel router, views importano SOLO il router |
| Regressione grafica da partials HTML | Bassa | Diff verbatim del blocco estratto; test visivo |
| SDK non carichi prima dei moduli | Bassa | SDK restano `defer` e vengono letti via `window.SC`/`window.Mixcloud` solo quando serve (lazy) |

**Rollback**: ripristinare da `_backup_frontend/`:
```bash
rm -rf templates static && cp -r _backup_frontend/templates _backup_frontend/static ./
python app.py
```

---

## 10. ORDINE DI ESECUZIONE CONSIGLIATO

```
Fase 0 (backup + baseline) → Fase 1 (core) → Fase 2 (player) → Fase 3 (views)
→ Fase 4 (swap + partials + smoke test) → [Fase 5 fix opzionali] → [Fase 6 CSS]
```

Tempo stimato: Fasi 0–4 = giornata lavorativa; Fase 5–6 opzionali.
