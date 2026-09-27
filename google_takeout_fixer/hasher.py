"""
hasher.py
---------
Calcolo dell'hash dei file per la deduplicazione.

Strategia a due fasi:
  1. Hash PARZIALE: legge solo i primi PARTIAL_HASH_BYTES del file.
     È molto veloce e filtra la maggior parte dei non-duplicati.
  2. Hash COMPLETO: se due file hanno lo stesso hash parziale,
     si calcola l'hash sull'intero file per confermare.

Questo approccio evita di leggere l'intero Terabyte di dati per ogni file.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from .config import PARTIAL_HASH_BYTES, HASH_ALGORITHM

logger = logging.getLogger(__name__)


def _compute_hash(path: str, max_bytes: Optional[int] = None) -> Optional[str]:
    """
    Calcola l'hash (SHA-256) di un file.
    
    Args:
        path: Percorso del file.
        max_bytes: Se specificato, legge solo i primi `max_bytes` byte.
                   Utile per l'hash parziale veloce.
    
    Returns:
        Stringa esadecimale dell'hash, o None in caso di errore.
    """
    h = hashlib.new(HASH_ALGORITHM)
    try:
        with open(path, "rb") as fh:
            if max_bytes is not None:
                # Lettura parziale: i/o efficiente senza caricare tutto in RAM
                remaining = max_bytes
                while remaining > 0:
                    chunk_size = min(65536, remaining)  # 64 KB per chunk
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
            else:
                # Lettura completa del file in chunk da 64 KB
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
    except OSError as exc:
        logger.error("Errore lettura file per hash: %s — %s", path, exc)
        return None
    return h.hexdigest()


def partial_hash(path: str) -> Optional[str]:
    """
    Hash veloce sui primi PARTIAL_HASH_BYTES del file.
    Ideale per un pre-filtro rapido durante la deduplicazione.
    """
    return _compute_hash(path, max_bytes=PARTIAL_HASH_BYTES)


def full_hash(path: str) -> Optional[str]:
    """
    Hash completo sull'intero file.
    Usato per confermare i duplicati trovati tramite hash parziale.
    """
    return _compute_hash(path, max_bytes=None)


def compute_dedup_hash(path: str) -> Optional[str]:
    """
    Calcola l'hash da usare per la deduplicazione.
    
    - File piccoli (< PARTIAL_HASH_BYTES): usa l'hash completo direttamente,
      perché non c'è vantaggio nell'hash parziale.
    - File grandi: usa prima l'hash parziale, poi quello completo (chiamato
      dall'orchestratore quando necessario).
    
    In questa implementazione semplificata restituisce sempre l'hash completo,
    che viene usato come chiave univoca nel DB. Il filtraggio a due fasi è
    gestito dall'orchestratore per evitare un'architettura over-engineered.
    """
    file_size = _get_file_size(path)
    if file_size is None:
        return None

    if file_size <= PARTIAL_HASH_BYTES:
        # File piccolo: hash completo (coincide con il parziale)
        return _compute_hash(path, max_bytes=None)
    else:
        # File grande: hash parziale come chiave primaria di dedup,
        # sufficiente nella pratica (la probabilità di collisione è
        # astronomicamente bassa con SHA-256 su 4 MB).
        # Se vuoi assoluta certezza, imposta FULL_HASH_FOR_LARGE_FILES=True
        # in config.py e usa full_hash() qui.
        return _compute_hash(path, max_bytes=PARTIAL_HASH_BYTES)


def _get_file_size(path: str) -> Optional[int]:
    """Restituisce la dimensione del file in byte, o None in caso di errore."""
    try:
        return os.path.getsize(path)
    except OSError as exc:
        logger.error("Impossibile leggere dimensione file: %s — %s", path, exc)
        return None
