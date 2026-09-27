"""
db_manager.py
-------------
Gestione del database SQLite per tracciare lo stato di elaborazione
di ogni file sorgente. Thread-safe grazie a un lock globale.

Schema della tabella `files`:
  - source_path  : percorso assoluto del file sorgente (chiave primaria)
  - file_hash    : hash SHA-256 del file (None se non ancora calcolato)
  - status       : 'pending' | 'processed' | 'duplicate' | 'error' | 'skipped'
  - dest_path    : percorso di destinazione finale (None se non ancora mosso)
  - json_path    : percorso del file JSON associato (None se non trovato)
  - error_msg    : messaggio di errore (None se nessun errore)
  - processed_at : timestamp ISO8601 dell'ultima modifica del record
"""

import sqlite3
import threading
import logging
import os
from datetime import datetime, timezone
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# Lock globale per serializzare le scritture sul DB da thread diversi
_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Connessione
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Apre (o crea) il database SQLite al percorso specificato.
    Attiva WAL mode per migliorare le performance in lettura concorrente.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Inizializzazione schema
# ---------------------------------------------------------------------------

def initialize_db(db_path: str) -> sqlite3.Connection:
    """
    Crea le tabelle necessarie se non esistono già.
    Restituisce la connessione aperta.
    """
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                source_path  TEXT PRIMARY KEY,
                file_hash    TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                dest_path    TEXT,
                json_path    TEXT,
                error_msg    TEXT,
                processed_at TEXT
            )
        """)
        # Indice sull'hash per velocizzare la ricerca duplicati
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_hash ON files (file_hash)
            WHERE file_hash IS NOT NULL
        """)
        # Indice sullo status per filtrare file già elaborati
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON files (status)
        """)

    logger.info("Database inizializzato: %s", db_path)
    return conn


# ---------------------------------------------------------------------------
# Inserimento / Aggiornamento record
# ---------------------------------------------------------------------------

def upsert_file(
    conn: sqlite3.Connection,
    source_path: str,
    file_hash: Optional[str] = None,
    status: str = "pending",
    dest_path: Optional[str] = None,
    json_path: Optional[str] = None,
    error_msg: Optional[str] = None,
) -> None:
    """
    Inserisce o aggiorna (upsert) il record corrispondente a source_path.
    Thread-safe: usa il lock globale _db_lock.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        with conn:
            conn.execute(
                """
                INSERT INTO files
                    (source_path, file_hash, status, dest_path, json_path, error_msg, processed_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    file_hash    = excluded.file_hash,
                    status       = excluded.status,
                    dest_path    = excluded.dest_path,
                    json_path    = excluded.json_path,
                    error_msg    = excluded.error_msg,
                    processed_at = excluded.processed_at
                """,
                (source_path, file_hash, status, dest_path, json_path, error_msg, now),
            )


def batch_upsert_files(
    conn: sqlite3.Connection,
    records: List[Tuple],
) -> None:
    """
    Inserisce o aggiorna una lista di record in un'unica transazione.
    Ogni record è una tupla:
        (source_path, file_hash, status, dest_path, json_path, error_msg)
    Thread-safe.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = [(*r, now) for r in records]
    with _db_lock:
        with conn:
            conn.executemany(
                """
                INSERT INTO files
                    (source_path, file_hash, status, dest_path, json_path, error_msg, processed_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    file_hash    = excluded.file_hash,
                    status       = excluded.status,
                    dest_path    = excluded.dest_path,
                    json_path    = excluded.json_path,
                    error_msg    = excluded.error_msg,
                    processed_at = excluded.processed_at
                """,
                rows,
            )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def get_file_record(
    conn: sqlite3.Connection, source_path: str
) -> Optional[sqlite3.Row]:
    """Recupera il record di un file dato il percorso sorgente."""
    cur = conn.execute(
        "SELECT * FROM files WHERE source_path = ?", (source_path,)
    )
    return cur.fetchone()


def is_already_processed(conn: sqlite3.Connection, source_path: str) -> bool:
    """
    Restituisce True se il file è già stato elaborato con successo
    (status = 'processed' oppure 'duplicate').
    """
    cur = conn.execute(
        "SELECT status FROM files WHERE source_path = ?", (source_path,)
    )
    row = cur.fetchone()
    if row is None:
        return False
    return row[0] in ("processed", "duplicate", "skipped")


def find_by_hash(
    conn: sqlite3.Connection, file_hash: str
) -> Optional[sqlite3.Row]:
    """
    Cerca un file già processato con lo stesso hash.
    Restituisce il primo record trovato con status='processed', o None.
    """
    cur = conn.execute(
        "SELECT * FROM files WHERE file_hash = ? AND status = 'processed' LIMIT 1",
        (file_hash,),
    )
    return cur.fetchone()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Restituisce un dizionario con i conteggi per ogni status."""
    cur = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM files GROUP BY status"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def get_pending_files(conn: sqlite3.Connection) -> List[str]:
    """Restituisce tutti i percorsi con status='pending' o 'error'."""
    cur = conn.execute(
        "SELECT source_path FROM files WHERE status IN ('pending', 'error')"
    )
    return [row[0] for row in cur.fetchall()]
