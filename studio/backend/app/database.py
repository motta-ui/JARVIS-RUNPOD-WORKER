import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA_VERSION = 4

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    category TEXT NOT NULL,          -- images, videos, audio, loras, references
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS gallery_items (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    job_id TEXT,
    kind TEXT NOT NULL,              -- image, video, audio
    file_path TEXT,
    thumbnail_path TEXT,
    prompt TEXT,
    engine TEXT,
    model TEXT,
    parameters TEXT,                 -- JSON string
    seed INTEGER,
    duration_seconds REAL,
    resolution TEXT,
    favorite INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    engine TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT,
    kind TEXT DEFAULT 'video',        -- video, image, audio, motion
    prompt TEXT,
    parameters TEXT,                 -- JSON string
    status TEXT NOT NULL DEFAULT 'QUEUED',
    progress REAL DEFAULT 0,
    output_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loras (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_path TEXT,
    engine TEXT,
    compatible_model TEXT,
    preview_path TEXT,
    description TEXT,
    strength REAL DEFAULT 1.0,
    active INTEGER DEFAULT 1,
    tags TEXT DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS engines (
    id TEXT PRIMARY KEY,
    name TEXT,
    capabilities TEXT,
    online INTEGER DEFAULT 0,
    detail TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS cloud_connection (
    id TEXT PRIMARY KEY,
    provider TEXT DEFAULT 'runpod',
    worker_url TEXT,
    worker_port INTEGER,
    worker_name TEXT,
    status TEXT DEFAULT 'OFFLINE',
    last_health_check TEXT,
    worker_info TEXT,
    last_error TEXT,
    updated_at TEXT
);
"""

# (from_version, [statements]) — applied in order. Each statement is wrapped so a
# column/table that already exists on an older installation never breaks it.
MIGRATIONS = [
    (1, [
        "ALTER TABLE jobs ADD COLUMN kind TEXT DEFAULT 'video'",
        "ALTER TABLE jobs ADD COLUMN started_at TEXT",
        "ALTER TABLE jobs ADD COLUMN completed_at TEXT",
        "ALTER TABLE gallery_items ADD COLUMN job_id TEXT",
        "ALTER TABLE gallery_items ADD COLUMN favorite INTEGER DEFAULT 0",
        "ALTER TABLE loras ADD COLUMN active INTEGER DEFAULT 1",
        "ALTER TABLE loras ADD COLUMN created_at TEXT",
    ]),
    (2, [
        "ALTER TABLE jobs ADD COLUMN preset_id TEXT",
        "ALTER TABLE jobs ADD COLUMN preset_name TEXT",
        "ALTER TABLE gallery_items ADD COLUMN preset_id TEXT",
        "ALTER TABLE gallery_items ADD COLUMN preset_name TEXT",
    ]),
    (3, [
        # token used to authenticate with the Cloud Worker (X-Jarvis-Token) —
        # write-only from the API's point of view, see cloud/worker_connection.py
        "ALTER TABLE cloud_connection ADD COLUMN worker_token TEXT",
        "ALTER TABLE jobs ADD COLUMN worker_job_id TEXT",
    ]),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _get_version(conn) -> int:
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    return row["version"] if row else 0


def _run_migrations(conn):
    version = _get_version(conn)
    for from_version, statements in MIGRATIONS:
        if version > from_version:
            continue
        for stmt in statements:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    raise
        version = from_version + 1
    if conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (max(version, SCHEMA_VERSION),))
    else:
        conn.execute("UPDATE schema_version SET version=?", (max(version, SCHEMA_VERSION),))


def init_db():
    with db_session() as conn:
        conn.executescript(BASE_SCHEMA)
        _run_migrations(conn)
        defaults = {
            "current_engine": "mock",
            "theme": "dark",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, json.dumps(v)),
            )


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()} if row else None
