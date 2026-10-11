-- Schema SQLite del player cross-source (v1).
-- Eseguito idempotentemente da storage/db.py::migrate.
-- Retention: history_aggregates 6 mesi, compliance_log 24 mesi.

CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

-- Cache risoluzioni con TTL 72h — riserva Aiko: zero-fetch al cold start
CREATE TABLE IF NOT EXISTS media_cache (
  canonical_id TEXT PRIMARY KEY,
  media_json TEXT NOT NULL,
  resolved_at TEXT NOT NULL,
  platform TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_cache_platform ON media_cache(platform);

-- Cache ricerche (TTL 30 min — le query cambiano, niente 72h)
CREATE TABLE IF NOT EXISTS search_cache (
  query_key TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  results_json TEXT NOT NULL,
  cached_at TEXT NOT NULL
);

-- Rate limiting persistente (1 richiesta / 5s per piattaforma — riserva Yuki)
CREATE TABLE IF NOT EXISTS rate_limits (
  platform TEXT PRIMARY KEY,
  last_request_ts REAL NOT NULL
);

-- Cronologia grezza degli ascolti/visioni (in produzione cifrata lato client;
-- qui tenuta per gli aggregati. La UI NON legge mai questa tabella.)
CREATE TABLE IF NOT EXISTS history_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  play_seconds REAL NOT NULL DEFAULT 0,
  watched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_media ON history_events(media_id);

-- Aggregati cronologia (retention 6 mesi). Unica fonte per le raccomandazioni.
CREATE TABLE IF NOT EXISTS history_aggregates (
  media_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  play_count INTEGER NOT NULL DEFAULT 0,
  total_seconds REAL NOT NULL DEFAULT 0,
  last_played TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  source_url TEXT NOT NULL DEFAULT '',
  uploader TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  thumbnail TEXT NOT NULL DEFAULT ''
);

-- Raccomandazioni PRECOMPUTATE: la home legge solo questa tabella,
-- mai la cronologia grezza (riserva Elena/Lucas).
CREATE TABLE IF NOT EXISTS recommendations (
  rank INTEGER PRIMARY KEY,
  media_id TEXT NOT NULL,
  score REAL NOT NULL,
  platform TEXT NOT NULL,
  title TEXT NOT NULL,
  thumbnail TEXT DEFAULT '',
  duration REAL DEFAULT 0,
  reason_tags TEXT NOT NULL DEFAULT '[]',
  source_url TEXT NOT NULL DEFAULT '',
  uploader TEXT NOT NULL DEFAULT '',
  computed_at TEXT NOT NULL
);

-- Preferiti
CREATE TABLE IF NOT EXISTS favorites (
  media_id TEXT PRIMARY KEY,
  media_json TEXT NOT NULL,
  added_at TEXT NOT NULL
);

-- Playlist
CREATE TABLE IF NOT EXISTS playlists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
  playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL,
  media_json TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY (playlist_id, media_id)
);

-- Coda di riproduzione persistente lato server (la coda UI speculare in IndexedDB)
CREATE TABLE IF NOT EXISTS queue (
  position INTEGER PRIMARY KEY,
  media_id TEXT NOT NULL,
  media_json TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0
);

-- Download worker a priorità
CREATE TABLE IF NOT EXISTS downloads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id TEXT NOT NULL,
  media_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  priority INTEGER NOT NULL DEFAULT 5,
  percent REAL NOT NULL DEFAULT 0,
  path TEXT DEFAULT '',
  watermark TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);

-- Impostazioni chiave/valore
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Guarda dopo (brief cliente: sezioni preferiti, guarda dopo, playlist)
CREATE TABLE IF NOT EXISTS watch_later (
  media_id TEXT PRIMARY KEY,
  media_json TEXT NOT NULL,
  added_at TEXT NOT NULL
);

-- Log di conformità: retention 24 mesi, esportabile, NON prunabile dalla UI
CREATE TABLE IF NOT EXISTS compliance_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  source_url TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT '',
  license TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compliance_ts ON compliance_log(ts);

-- ==========================================================================
-- Sistema di raccomandazione v2 (artisti + similarità da fonti esterne)
-- ==========================================================================

-- Identità artista: una riga per artista noto (nome normalizzato + eventuale MBID)
CREATE TABLE IF NOT EXISTS artists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mbid TEXT UNIQUE,
  name TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  resolve_status TEXT NOT NULL DEFAULT 'unresolved',  -- unresolved | resolved | ambiguous
  resolved_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artists_name_norm ON artists(name_norm);

-- Alias/varianti di nome → artista (per varianti, " - Topic", traslitterazioni)
CREATE TABLE IF NOT EXISTS artist_aliases (
  artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  alias_norm TEXT NOT NULL UNIQUE
);

-- Link piattaforma → URL (profilo/canale/traccia) associati all'artista
CREATE TABLE IF NOT EXISTS artist_links (
  artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  url TEXT NOT NULL,
  UNIQUE(platform, url)
);

-- Similarità tra artisti precomputata dalle fonti (Last.fm, MusicBrainz, ...)
CREATE TABLE IF NOT EXISTS artist_similarity (
  artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  similar_name_norm TEXT NOT NULL,
  similar_artist_id INTEGER REFERENCES artists(id),
  score REAL NOT NULL,
  source TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  PRIMARY KEY(artist_id, similar_name_norm, source)
);
CREATE INDEX IF NOT EXISTS idx_artist_similarity_name ON artist_similarity(similar_name_norm);

-- Tag/generi pesati per artista, per fonte
CREATE TABLE IF NOT EXISTS artist_tags (
  artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  PRIMARY KEY(artist_id, tag, source)
);

-- Feedback esplicito dell'utente sugli artisti
CREATE TABLE IF NOT EXISTS rec_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  artist_id INTEGER REFERENCES artists(id),
  artist_name_norm TEXT NOT NULL,
  action TEXT NOT NULL,   -- like | dislike | hide
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_feedback_norm ON rec_feedback(artist_name_norm);
