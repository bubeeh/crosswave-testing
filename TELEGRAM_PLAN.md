# PIANO DI IMPLEMENTAZIONE INTEGRAZIONE TELEGRAM — CrossWave Hybrid

> **Stato**: implementato e fixato (23/08/2026) · **Obiettivo**: Integrazione Bot Telegram per l'acquisizione silenziosa di **link Bandcamp** (decisione: solo Bandcamp) con estrazione metadati (Artista, Titolo, Label, Release Date) ed erogazione su tabella UI CrossWave e comandi Telegram di gruppo.

> **FIX APPLICATI (vedi anche `.env.example` e `telegram_bot.py`)**:
> 1. **Token** rimosso dal codice: ora va in variabile d'ambiente `TELEGRAM_TOKEN` (file `.env`). Il vecchio token esposto è da considerarsi compromesso → rigenerarlo con @BotFather.
> 2. **Group Privacy**: prerequisito obbligatorio, da disattivare su @BotFather (Bot Settings → Group Privacy → Turn off) o bot admin del gruppo — senza, il bot non riceve i link.
> 3. **Doppio bot in debug**: `app.py` avvia il worker solo nel processo di lavoro del reloader (guardia `WERKZEUG_RUN_MAIN`).
> 4. **`beautifulsoup4` aggiunto a `requirements.txt`**.
> 5. **Metadati YT/SC/MC via oEmbed** (leggero e affidabile) con fallback og: e thumbnail YouTube HQ dal videoId.
> 6. **SQLite**: `timeout=10` + `PRAGMA busy_timeout=5000` sulle connessioni del bot.
> 7. **Whitelist chat opzionale** (`TELEGRAM_ALLOWED_CHAT_IDS`).
> 8. **Dettagli**: gestione `caption` (foto+link), skip messaggi dei bot, backoff progressivo su errori/409, filtro frontend corretto.

---

## 1. ARCHITETTURA E OBIETTIVI

### 1.1 Comportamento del Bot in Chat (Gruppo Telegram)
* **Modalità Silenziosa (Zero Spam)**: Quando un amico o l'utente incolla un link Bandcamp nel gruppo, il bot **non invia alcun messaggio di notifica automatico**. Cattura il link in background, estrae i metadati completi (*Titolo, Artista, Label, Data di uscita, Copertina, Sender*) e lo memorizza nel database.

> **Nota (23/08/2026)**: la cattura accetta **solo link Bandcamp** (`LINK_REGEX` in `telegram_bot.py`). YouTube/SoundCloud/Mixcloud vengono ignorati. Per riattivarli basta riallargare la regex.
* **Comandi su Richiesta degli Amici**:
  * `/lista` (o `/latest`): Risponde in chat con una lista formattata delle ultime 10 release condivise con indicazione di Artista, Titolo, Label e utente che l'ha proposta.
  * `/cerca <query>`: Cerca nell'archivio storico delle segnalazioni della chat.
  * `/label <nome>`: Filtra le release condivise per etichetta discografica.

### 1.2 Interfaccia Web CrossWave
* Nuova scheda **"Feed Telegram"** nella barra laterale con icona Telegram.
* Tabella interattiva avanzata:
  * **Copertina** | **Titolo & Artista** | **Label** | **Data Uscita** | **Condiviso da** | **Data Invio** | **Azioni** (*Play, Coda, Preferiti, Soundload*).
* Filtri rapidi per cerca testo, label e utente mittente.

---

## 2. MODELLO DATI (Database SQLite `crosswave.db`)

Creazione della tabella `telegram_shares`:

```sql
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
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. COMPONENTI DA CREARE / MODIFICARE

```
crosswave_hybrid/
├── telegram_bot.py                       # Worker thread Bot Telegram (Polling API)
├── app.py                                # DB init + REST API /api/telegram/feed + Avvio thread Bot
├── templates/
│   ├── index.html                        # Aggiunta pulsante sidebar + include view_telegram.html
│   └── components/
│       └── view_telegram.html            # Componente Jinja per il tab Feed Telegram
static/js/
├── core/router.js                        # Aggiunta rotta hash 'telegram': '#/telegram'
├── views/telegram.js                     # Modulo ES per il rendering e filtro della tabella Telegram
└── app.js                                # Import views/telegram.js + registrazione tab
```

---

## 4. PIANO DELLE FASI DI IMPLEMENTAZIONE

### FASE 1 — Database & API Backend (`app.py`)
1. Aggiungere la tabella `telegram_shares` in `init_db()` in `app.py`.
2. Creare gli endpoint REST:
   - `GET /api/telegram/feed`: restituisce la lista di tutti i brani/album condivisi ordinati per `created_at DESC`.
   - `DELETE /api/telegram/feed/<id>`: elimina un elemento dall'archivio.

### FASE 2 — Worker Bot Telegram (`telegram_bot.py`)
1. Implementare il worker bot in Python utilizzando la Telegram Bot HTTP API (`getUpdates` via `requests`), leggero, performante e privo di dipendenze pesanti.
2. **Token**: inserirlo SOLO nel file `.env` (variabile `TELEGRAM_TOKEN`), MAI nel codice. Il token precedentemente incollato in questo documento è da considerarsi compromesso e va rigenerato con @BotFather.
3. Riconoscimento dei link: estrazione di URL `bandcamp.com`, `youtube.com`, `soundcloud.com`, `mixcloud.com`.
4. Estrazione metadati arricchita per Bandcamp (scraping leggero di Label e Data di Rilascio dalla pagina dell'album/traccia) + integrazione con `resolver_service`.
5. Gestione comandi Telegram di gruppo (`/lista`, `/cerca`, `/label`).
6. Avvio del thread in background dentro `app.py`.

### FASE 3 — Componente Template HTML (`templates/components/view_telegram.html`)
1. Creare `<section class="tab-content" id="tab-telegram">`.
2. Strutturare l'header con contatore, campo di ricerca rapida e filtri.
3. Creare il contenitore per la tabella glassmorphic delle segnalazioni.

### FASE 4 — Modulo JS Frontend (`static/js/views/telegram.js` & `router.js`)
1. Creare `static/js/views/telegram.js` per il fetch di `/api/telegram/feed` e la creazione delle righe della tabella.
2. Aggiornare `static/js/core/router.js` includendo `'telegram': '#/telegram'`.
3. Registrare il tab in `static/js/app.js` e aggiungere il pulsante nella sidebar di `templates/index.html`.

### FASE 5 — Collaudo & Verification
1. Esecuzione check sintattici `node --check` e test d'integrazione Python.
2. Test chiamata API ed avvio del server Flask + Telegram Bot thread.

---

## 5. REGOLE ED ESECUZIONE
* Mantenere la modalità **silenziosa** in chat per i link in arrivo (nessun messaggio automatico inviato nel gruppo quando si incolla un link).
* Rispondere in chat solo all'invocazione esplicita dei comandi `/lista`, `/cerca`, `/label`.
