"""
exiftool_wrapper.py
-------------------
Interfaccia Python per il binario esterno ExifTool (Phil Harvey).
Usa subprocess per richiamare ExifTool in modalità batch, iniettando
metadati (data di scatto, GPS, descrizione) direttamente nei file media.

Perché subprocess invece di pyexiftool?
  - pyexiftool non è mantenuto attivamente e ha problemi su Windows
  - subprocess ci dà il pieno controllo su encoding, timeout e argomenti
  - ExifTool in modalità "-stay_open" (pipe) è già molto veloce

Nota: ExifTool deve essere installato e raggiungibile nel PATH di sistema.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from .config import EXIFTOOL_TIMEOUT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rilevamento ExifTool
# ---------------------------------------------------------------------------

def find_exiftool() -> Optional[str]:
    """
    Cerca l'eseguibile ExifTool nel PATH di sistema.
    Su Windows controlla anche il percorso comune di installazione.
    
    Returns:
        Percorso assoluto dell'eseguibile, o None se non trovato.
    """
    # Cerca nel PATH standard
    exe = shutil.which("exiftool")
    if exe:
        return exe

    # Percorsi alternativi comuni su Windows
    if sys.platform == "win32":
        common_paths = [
            r"C:\Windows\exiftool.exe",
            r"C:\Program Files\ExifTool\exiftool.exe",
            r"C:\Tools\exiftool.exe",
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p

    return None


def check_exiftool() -> str:
    """
    Verifica che ExifTool sia disponibile. Solleva RuntimeError se non lo è.
    Restituisce il percorso dell'eseguibile trovato.
    """
    exe = find_exiftool()
    if exe is None:
        raise RuntimeError(
            "ExifTool non trovato nel PATH. "
            "Consulta il README per le istruzioni di installazione."
        )
    # Verifica versione
    try:
        result = subprocess.run(
            [exe, "-ver"],
            capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip()
        logger.info("ExifTool trovato: %s (versione %s)", exe, version)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ExifTool non risponde (timeout).")
    return exe


# ---------------------------------------------------------------------------
# Formattazione argomenti
# ---------------------------------------------------------------------------

def _epoch_to_exiftool_date(epoch: int) -> str:
    """
    Converte un timestamp Unix (epoch) nella stringa di data
    nel formato atteso da ExifTool: YYYY:MM:DD HH:MM:SS
    
    ExifTool accetta anche il fuso orario (es. +01:00) ma per semplicità
    si usa UTC e si lascia a ExifTool la normalizzazione.
    """
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def _build_exiftool_args(
    media_path: str,
    metadata: Dict[str, Any],
    exiftool_exe: str,
) -> List[str]:
    """
    Costruisce la lista di argomenti per una singola invocazione di ExifTool
    su un file multimediale.

    Tag scritti:
      - DateTimeOriginal, CreateDate, TrackCreateDate, MediaCreateDate (video)
      - GPSLatitude, GPSLongitude, GPSAltitude + relativi Ref
      - Description / ImageDescription / Comment
      - Title / XPTitle
    
    L'opzione "-overwrite_original" evita la creazione di file "_original"
    di backup (risparmia spazio su disco).
    L'opzione "-preserve" mantiene i timestamp del filesystem invariati,
    utile se si vuole usare il timestamp originale del file come fallback.
    """
    args = [
        exiftool_exe,
        "-overwrite_original",  # sovrascrive senza creare backup
        "-preserve",            # mantiene mtime/atime del filesystem
        "-m",                   # ignora errori minori (tag non supportati)
        "-q",                   # output silenzioso (solo errori)
    ]

    timestamp = metadata.get("timestamp", 0)
    if timestamp and timestamp > 0:
        date_str = _epoch_to_exiftool_date(timestamp)
        # Tag EXIF standard per le immagini
        args += [
            f"-DateTimeOriginal={date_str}",
            f"-CreateDate={date_str}",
            f"-ModifyDate={date_str}",
            # Tag specifici per i video (QuickTime/MP4)
            f"-TrackCreateDate={date_str}",
            f"-TrackModifyDate={date_str}",
            f"-MediaCreateDate={date_str}",
            f"-MediaModifyDate={date_str}",
        ]

    lat = metadata.get("latitude")
    lon = metadata.get("longitude")
    alt = metadata.get("altitude")

    if lat is not None and lon is not None:
        # ExifTool vuole latitudine/longitudine come valori assoluti + Ref
        lat_ref = "N" if lat >= 0 else "S"
        lon_ref = "E" if lon >= 0 else "W"
        args += [
            f"-GPSLatitude={abs(lat)}",
            f"-GPSLatitudeRef={lat_ref}",
            f"-GPSLongitude={abs(lon)}",
            f"-GPSLongitudeRef={lon_ref}",
        ]
        if alt is not None:
            alt_ref = 0 if alt >= 0 else 1  # 0=above sea level, 1=below
            args += [
                f"-GPSAltitude={abs(alt)}",
                f"-GPSAltitudeRef={alt_ref}",
            ]

    description = metadata.get("description")
    if description:
        # Tronca a 2000 caratteri per evitare problemi con tag EXIF limitati
        desc_short = description[:2000]
        args += [
            f"-Description={desc_short}",
            f"-ImageDescription={desc_short}",
            f"-Comment={desc_short}",
        ]

    title = metadata.get("title")
    if title:
        args += [
            f"-Title={title}",
        ]

    # Percorso del file in fondo (convenzione ExifTool)
    args.append(media_path)
    return args


# ---------------------------------------------------------------------------
# Esecuzione ExifTool
# ---------------------------------------------------------------------------

def apply_metadata(
    media_path: str,
    metadata: Dict[str, Any],
    exiftool_exe: str,
) -> bool:
    """
    Inietta i metadati estratti dal JSON nel file multimediale usando ExifTool.
    
    Args:
        media_path   : Percorso assoluto del file da modificare.
        metadata     : Dizionario con timestamp, lat, lon, alt, description, title.
        exiftool_exe : Percorso dell'eseguibile ExifTool.
    
    Returns:
        True se ExifTool ha completato senza errori fatali, False altrimenti.
    """
    # Se non c'è nulla da scrivere, salta la chiamata (ottimizzazione)
    has_date = metadata.get("timestamp", 0) > 0
    has_gps = metadata.get("latitude") is not None
    has_desc = bool(metadata.get("description"))
    has_title = bool(metadata.get("title"))

    if not any([has_date, has_gps, has_desc, has_title]):
        logger.debug("Nessun metadato da scrivere per: %s", media_path)
        return True  # Niente da fare, ma non è un errore

    args = _build_exiftool_args(media_path, metadata, exiftool_exe)

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXIFTOOL_TIMEOUT,
        )
        if proc.returncode != 0:
            # ExifTool restituisce 1 se ci sono errori/warning ma ha comunque
            # elaborato il file; stderr contiene i dettagli
            stderr = proc.stderr.strip()
            if "Error" in stderr or "not defined" in stderr:
                logger.error(
                    "ExifTool errore su %s: %s", media_path, stderr[:500]
                )
                return False
            else:
                # Warning non fatali (es. tag non supportato per questo formato)
                logger.debug("ExifTool warning su %s: %s", media_path, stderr[:200])
        return True

    except subprocess.TimeoutExpired:
        logger.error("ExifTool timeout su: %s", media_path)
        return False
    except FileNotFoundError:
        logger.critical("ExifTool non trovato: %s", exiftool_exe)
        raise
    except OSError as exc:
        logger.error("Errore OS su ExifTool per %s: %s", media_path, exc)
        return False


def read_metadata_from_file(
    media_path: str,
    exiftool_exe: str,
) -> Optional[Dict[str, Any]]:
    """
    Legge i metadati EXIF/XMP correnti dal file tramite ExifTool (in JSON).
    Utile per il debug o per verificare che la scrittura sia avvenuta.
    
    Returns:
        Dizionario con i metadati letti, o None in caso di errore.
    """
    try:
        proc = subprocess.run(
            [exiftool_exe, "-json", "-DateTimeOriginal", "-GPSLatitude",
             "-GPSLongitude", media_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXIFTOOL_TIMEOUT,
        )
        data = json.loads(proc.stdout)
        return data[0] if data else {}
    except Exception as exc:
        logger.debug("read_metadata_from_file errore: %s — %s", media_path, exc)
        return None
