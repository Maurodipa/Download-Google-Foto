"""
scanner.py
----------
Scansione ricorsiva della cartella sorgente Google Takeout.

Responsabilità:
  1. Enumerare tutti i file multimediali (immagini + video) nella sorgente.
  2. Registrare i file non ancora tracciati nel DB con status='pending'.
  3. Restituire la lista dei file da elaborare (pending + error),
     escludendo quelli già completati (processed, duplicate, skipped).

La scansione è separata dall'elaborazione per due motivi:
  - Permette di fare una stima accurata della dimensione totale del lavoro
    prima di iniziare l'elaborazione vera e propria.
  - Semplifica la logica di resume: una seconda esecuzione non ri-scansiona
    i file già nel DB con status terminale.
"""

import logging
import os
from pathlib import Path
from typing import Iterator, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import MEDIA_EXTENSIONS, MAX_WORKERS, DB_COMMIT_BATCH
from .db_manager import (
    upsert_file,
    batch_upsert_files,
    is_already_processed,
)
from .path_utils import make_safe_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generatore di file multimediali
# ---------------------------------------------------------------------------

def iter_media_files(source_root: str) -> Iterator[str]:
    """
    Genera in modo lazy i percorsi assoluti di tutti i file multimediali
    trovati nella sorgente, percorrendo ricorsivamente le sottocartelle.
    
    Esclude automaticamente:
    - File con estensione .json (sidecar)
    - File con estensione .html (report Takeout)
    - File nascosti (che iniziano con '.')
    - La cartella di destinazione se si trova sotto quella sorgente
    
    Args:
        source_root: Percorso radice della cartella Takeout sorgente.
    
    Yields:
        Percorso assoluto (str) di ogni file multimediale trovato.
    """
    source_root = os.path.abspath(source_root)

    for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
        # Esclude cartelle nascoste in-place per evitare di scendere in esse
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
        ]

        for filename in filenames:
            # Esclude file nascosti
            if filename.startswith("."):
                continue

            ext = Path(filename).suffix.lower()

            # Considera solo le estensioni multimediali configurate
            if ext not in MEDIA_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, filename)
            yield full_path


# ---------------------------------------------------------------------------
# Pre-scansione e registrazione nel DB
# ---------------------------------------------------------------------------

def scan_and_register(
    source_root: str,
    conn,
) -> Tuple[int, int]:
    """
    Scansiona la sorgente e registra tutti i file multimediali nel DB.
    
    - I file già presenti nel DB non vengono toccati (preserva lo stato).
    - I nuovi file vengono inseriti con status='pending'.
    
    Args:
        source_root : Cartella radice Takeout sorgente.
        conn        : Connessione SQLite aperta.
    
    Returns:
        Tupla (total_found, newly_registered):
          - total_found     : quanti file multimediali esistono nella sorgente
          - newly_registered: quanti file sono stati aggiunti al DB ora
    """
    logger.info("Scansione sorgente: %s", source_root)

    total_found = 0
    newly_registered = 0
    batch: List[Tuple] = []  # buffer per batch_upsert

    for media_path in iter_media_files(source_root):
        total_found += 1

        # Controlla se è già nel DB (evita un upsert inutile)
        if is_already_processed(conn, media_path):
            continue

        # Aggiungi al batch di inserimento
        # (source_path, file_hash, status, dest_path, json_path, error_msg)
        batch.append((media_path, None, "pending", None, None, None))
        newly_registered += 1

        # Flush periodico per evitare di accumulare troppo in memoria
        if len(batch) >= DB_COMMIT_BATCH:
            batch_upsert_files(conn, batch)
            batch.clear()
            logger.debug(
                "Scansione in corso... trovati %d file (nuovi: %d)",
                total_found, newly_registered
            )

    # Flush dell'ultimo batch parziale
    if batch:
        batch_upsert_files(conn, batch)

    logger.info(
        "Scansione completata. File multimediali trovati: %d | Nuovi da elaborare: %d",
        total_found, newly_registered,
    )
    return total_found, newly_registered


# ---------------------------------------------------------------------------
# Recupero lista file da elaborare
# ---------------------------------------------------------------------------

def get_files_to_process(conn) -> List[str]:
    """
    Restituisce la lista di percorsi sorgente che devono ancora essere
    elaborati (status = 'pending' o 'error', ovvero retry automatico).
    
    Returns:
        Lista di percorsi assoluti da processare.
    """
    from .db_manager import get_pending_files
    files = get_pending_files(conn)
    logger.info("File da elaborare: %d", len(files))
    return files
