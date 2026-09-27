"""
path_utils.py
-------------
Utilità per la gestione sicura dei percorsi su tutti i sistemi operativi,
con particolare attenzione al limite MAX_PATH di Windows (260 caratteri)
e ai nomi file problematici generati da Google Takeout.
"""

import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import (
    WINDOWS_LONG_PATH_PREFIX,
    DEST_YEAR_FORMAT,
    DEST_MONTH_FORMAT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gestione MAX_PATH Windows
# ---------------------------------------------------------------------------

def make_safe_path(path: str) -> str:
    """
    Su Windows, antepone il prefisso UNC esteso "\\\\?\\" se il percorso
    supera i 259 caratteri utili (260 - 1 per il terminatore NULL).
    
    Questo consente di usare percorsi fino a ~32.767 caratteri.
    Requisito: il percorso deve essere ASSOLUTO.
    
    Su macOS/Linux è un no-op.
    """
    if sys.platform != "win32":
        return path

    # Normalizza i separatori a backslash (richiesto dal prefisso UNC)
    path = os.path.abspath(path).replace("/", "\\")

    if len(path) > 259 and not path.startswith(WINDOWS_LONG_PATH_PREFIX):
        path = WINDOWS_LONG_PATH_PREFIX + path

    return path


def safe_open(path: str, mode: str = "rb", **kwargs):
    """
    Apre un file usando make_safe_path per gestire i percorsi lunghi su Windows.
    Wrapper attorno a open() built-in.
    """
    return open(make_safe_path(path), mode, **kwargs)


# ---------------------------------------------------------------------------
# Sanitizzazione nomi file
# ---------------------------------------------------------------------------

# Caratteri non consentiti in nomi file su Windows
_WINDOWS_FORBIDDEN = r'[<>:"/\\|?*\x00-\x1f]'
# Nomi riservati su Windows (insensibili a maiuscolo)
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Rende sicuro un nome file su tutti i sistemi operativi:
      1. Normalizza unicode (NFC)
      2. Rimuove/sostituisce caratteri vietati su Windows
      3. Tronca se troppo lungo
      4. Sostituisce nomi riservati Windows
    
    Non modifica l'estensione del file.
    """
    # 1. Normalizzazione unicode
    name = unicodedata.normalize("NFC", name)

    # 2. Separa stem ed estensione per proteggere l'estensione.
    #    Nota: Path(".jpg").suffix == "" su Python perché pathlib interpreta
    #    i nomi che iniziano con punto come file nascosti (stem=".jpg", suffix="").
    #    Gestiamo questo caso con uno split manuale sull'ultimo punto.
    path = Path(name)
    ext = path.suffix   # include il punto, es. ".jpg" — può essere "" per ".jpg"
    stem = path.stem    # es. "IMG_1234"

    # Se pathlib non ha trovato un suffix ma il nome contiene un punto non iniziale,
    # tratta tutto dopo l'ultimo punto come estensione
    if not ext and "." in name:
        dot_idx = name.rfind(".")
        stem = name[:dot_idx] if dot_idx > 0 else ""
        ext = name[dot_idx:]   # es. ".jpg"

    # Rimuovi caratteri vietati su Windows dallo stem
    stem = re.sub(_WINDOWS_FORBIDDEN, "_", stem)
    # Rimuovi spazi/punti finali (Windows non li permette)
    stem = stem.rstrip(" .")

    # 3. Controlla nomi riservati
    if stem.upper() in _WINDOWS_RESERVED:
        stem = stem + "_file"

    # 4. Tronca preservando l'estensione
    max_stem = max_length - len(ext)
    if len(stem) > max_stem:
        stem = stem[:max_stem].rstrip(" .")

    if not stem:
        stem = "unnamed"

    return stem + ext


# ---------------------------------------------------------------------------
# Costruzione percorso di destinazione
# ---------------------------------------------------------------------------

def build_dest_path(
    dest_root: str,
    filename: str,
    timestamp: int,
) -> str:
    """
    Costruisce il percorso completo di destinazione per un file, organizzando
    per Anno/Mese.
    
    Struttura: <dest_root>/<YYYY>/<MM>/<filename_sanitizzato>
    
    Args:
        dest_root : Cartella radice di destinazione.
        filename  : Nome originale del file (con estensione).
        timestamp : Unix epoch della data di scatto. Se 0 o invalido,
                    usa la cartella "senza_data".
    
    Returns:
        Percorso assoluto di destinazione (senza garanzia di unicità,
        vedi resolve_conflicts()).
    """
    if timestamp and timestamp > 0:
        try:
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            year_dir = dt.strftime(DEST_YEAR_FORMAT)
            month_dir = dt.strftime(DEST_MONTH_FORMAT)
        except (OSError, ValueError, OverflowError):
            year_dir = "data_sconosciuta"
            month_dir = "00"
    else:
        year_dir = "data_sconosciuta"
        month_dir = "00"

    safe_name = sanitize_filename(filename)
    return os.path.join(dest_root, year_dir, month_dir, safe_name)


def resolve_conflict(dest_path: str) -> str:
    """
    Se il percorso di destinazione esiste già, aggiunge un suffisso numerico
    progressivo fino a trovare un nome libero.
    
    Esempio: foto.jpg → foto_001.jpg → foto_002.jpg → ...
    """
    if not os.path.exists(dest_path):
        return dest_path

    path = Path(dest_path)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1

    while True:
        candidate = parent / f"{stem}_{counter:03d}{suffix}"
        if not candidate.exists():
            return str(candidate)
        counter += 1
        if counter > 9999:
            # Failsafe: usa timestamp nanosecondi
            import time
            ts = int(time.time_ns())
            return str(parent / f"{stem}_{ts}{suffix}")


def ensure_dir(path: str) -> None:
    """
    Crea la directory (e tutte le parent) se non esiste già.
    Usa make_safe_path per supportare percorsi lunghi su Windows.
    """
    safe = make_safe_path(path)
    os.makedirs(safe, exist_ok=True)
