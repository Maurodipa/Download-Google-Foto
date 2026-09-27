"""
processor.py
------------
Cuore dell'elaborazione: per ogni file multimediale sorgente esegue in sequenza:

  1. Calcolo dell'hash (deduplicazione)
  2. Ricerca del JSON sidecar e parsing dei metadati
  3. Iniezione metadati via ExifTool (su una COPIA in staging temporaneo)
  4. Spostamento/copia nella struttura Anno/Mese di destinazione
  5. Aggiornamento del record nel DB SQLite

Il processo viene eseguito in parallelo tramite ThreadPoolExecutor.
Le scritture sul DB sono thread-safe grazie al lock in db_manager.py.

IMPORTANTE: ExifTool modifica i file IN PLACE (con -overwrite_original).
Lo script opera su una copia del file nella destinazione, NON sul file
sorgente originale. L'originale non viene mai modificato.
"""

import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Tuple

from .config import MAX_WORKERS, COPY_FILES, DB_COMMIT_BATCH
from .db_manager import (
    upsert_file,
    batch_upsert_files,
    find_by_hash,
    get_stats,
)
from .hasher import compute_dedup_hash
from .json_matcher import find_json_for_media, parse_json_metadata
from .exiftool_wrapper import apply_metadata, check_exiftool
from .path_utils import build_dest_path, resolve_conflict, ensure_dir, make_safe_path

logger = logging.getLogger(__name__)

# Lock per le operazioni filesystem che non devono essere interleaved
_fs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Elaborazione di un singolo file
# ---------------------------------------------------------------------------

def process_single_file(
    source_path: str,
    dest_root: str,
    conn,
    exiftool_exe: str,
) -> Tuple[str, str, Optional[str], Optional[str], Optional[str]]:
    """
    Elabora un singolo file multimediale.
    
    Returns:
        Tupla (source_path, status, file_hash, dest_path, error_msg)
        dove status è: 'processed' | 'duplicate' | 'error' | 'skipped'
    """
    # --- Step 1: Calcolo hash per deduplicazione ---
    file_hash = compute_dedup_hash(source_path)
    if file_hash is None:
        return (source_path, "error", None, None, "Impossibile calcolare l'hash del file")

    # --- Step 2: Controlla se è un duplicato ---
    existing = find_by_hash(conn, file_hash)
    if existing is not None:
        # Accesso per indice posizionale (compatibile Python 3.14+)
        # Schema: source_path=0, file_hash=1, status=2, dest_path=3
        dest_info = existing[3] if existing[3] else "(destinazione sconosciuta)"
        logger.debug(
            "DUPLICATO ignorato: %s (già presente come %s)",
            os.path.basename(source_path),
            dest_info,
        )
        return (source_path, "duplicate", file_hash, None, None)


    # --- Step 3: Cerca il JSON sidecar ---
    json_path = find_json_for_media(source_path)
    metadata = {}
    if json_path:
        metadata = parse_json_metadata(json_path)
        logger.debug(
            "JSON trovato per %s: ts=%s lat=%s lon=%s",
            os.path.basename(source_path),
            metadata.get("timestamp"),
            metadata.get("latitude"),
            metadata.get("longitude"),
        )
    else:
        logger.warning("Nessun JSON per: %s", os.path.basename(source_path))

    # --- Step 4: Costruisci percorso di destinazione ---
    timestamp = metadata.get("timestamp", 0)
    filename = os.path.basename(source_path)
    dest_path = build_dest_path(dest_root, filename, timestamp)

    # Risolve conflitti di nomi (thread-safe con lock)
    with _fs_lock:
        dest_path = resolve_conflict(dest_path)
        ensure_dir(os.path.dirname(dest_path))

        # --- Step 5: Copia/sposta il file nella destinazione ---
        try:
            if COPY_FILES:
                shutil.copy2(make_safe_path(source_path), make_safe_path(dest_path))
            else:
                shutil.move(make_safe_path(source_path), make_safe_path(dest_path))
        except OSError as exc:
            return (source_path, "error", file_hash, None, f"Errore copia/move: {exc}")

    # --- Step 6: Inietta metadati con ExifTool nel file di DESTINAZIONE ---
    # (Operiamo sulla copia, mai sull'originale sorgente)
    if metadata and any([
        metadata.get("timestamp", 0) > 0,
        metadata.get("latitude") is not None,
        metadata.get("description"),
    ]):
        success = apply_metadata(dest_path, metadata, exiftool_exe)
        if not success:
            logger.warning(
                "ExifTool ha fallito su %s, file copiato ma senza metadati aggiornati",
                os.path.basename(dest_path),
            )
            # Non consideriamo un errore ExifTool come fallimento totale:
            # il file è comunque copiato nella destinazione.

    logger.info(
        "OK → %s/%s/%s",
        Path(dest_path).parent.parent.name,
        Path(dest_path).parent.name,
        Path(dest_path).name,
    )
    return (source_path, "processed", file_hash, dest_path, None)


# ---------------------------------------------------------------------------
# Elaborazione parallela con ThreadPoolExecutor
# ---------------------------------------------------------------------------

def process_all_files(
    files_to_process: List[str],
    dest_root: str,
    conn,
    exiftool_exe: str,
    progress_callback=None,
) -> None:
    """
    Elabora tutti i file in parallelo usando un ThreadPoolExecutor.
    
    I risultati vengono accumulati in batch e scritti nel DB periodicamente
    per minimizzare il contention sul lock SQLite.
    
    Args:
        files_to_process  : Lista di percorsi sorgente da processare.
        dest_root         : Cartella radice di destinazione.
        conn              : Connessione SQLite.
        exiftool_exe      : Percorso dell'eseguibile ExifTool.
        progress_callback : Funzione opzionale chiamata dopo ogni file completato,
                            con firma (completed: int, total: int, status: str).
    """
    total = len(files_to_process)
    if total == 0:
        logger.info("Nessun file da elaborare.")
        return

    workers = MAX_WORKERS or os.cpu_count() or 4
    logger.info(
        "Avvio elaborazione parallela: %d file, %d worker thread", total, workers
    )

    completed = 0
    pending_db_records: List[Tuple] = []

    def _flush_db():
        nonlocal pending_db_records
        if pending_db_records:
            batch_upsert_files(conn, pending_db_records)
            pending_db_records = []

    start_time = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Sottomette tutti i task contemporaneamente
        future_to_path = {
            executor.submit(
                process_single_file,
                source_path, dest_root, conn, exiftool_exe
            ): source_path
            for source_path in files_to_process
        }

        for future in as_completed(future_to_path):
            source_path = future_to_path[future]
            completed += 1

            try:
                src, status, file_hash, dest_path, error_msg = future.result()
            except Exception as exc:
                # Eccezione non gestita nel worker: la traccia qui
                logger.exception("Eccezione non gestita per %s: %s", source_path, exc)
                src = source_path
                status = "error"
                file_hash = None
                dest_path = None
                error_msg = str(exc)

            # Recupera il json_path (può essere None)
            json_path = find_json_for_media(src) if status != "error" else None

            # Accoda il record per il batch update
            pending_db_records.append(
                (src, file_hash, status, dest_path, json_path, error_msg)
            )

            # Flush periodico sul DB
            if len(pending_db_records) >= DB_COMMIT_BATCH:
                _flush_db()

            # Callback di progresso
            if progress_callback:
                progress_callback(completed, total, status)

            # Log periodico ogni 100 file
            if completed % 100 == 0 or completed == total:
                elapsed = time.monotonic() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                logger.info(
                    "Progresso: %d/%d (%.1f%%) — %.1f file/s — ETA: %s",
                    completed, total,
                    completed / total * 100,
                    rate,
                    _format_eta(eta),
                )

    # Flush finale
    _flush_db()

    elapsed = time.monotonic() - start_time
    stats = get_stats(conn)
    logger.info("=" * 60)
    logger.info("ELABORAZIONE COMPLETATA in %s", _format_eta(elapsed))
    logger.info("  Processati con successo : %d", stats.get("processed", 0))
    logger.info("  Duplicati ignorati      : %d", stats.get("duplicate", 0))
    logger.info("  Errori                  : %d", stats.get("error", 0))
    logger.info("  Saltati                 : %d", stats.get("skipped", 0))
    logger.info("=" * 60)


def _format_eta(seconds: float) -> str:
    """Formatta i secondi in una stringa leggibile HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
