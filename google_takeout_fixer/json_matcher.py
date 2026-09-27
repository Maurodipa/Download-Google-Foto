"""
json_matcher.py
---------------
Logica per trovare e parsare il file JSON "sidecar" associato a ogni
file multimediale esportato da Google Takeout.

Google Takeout usa convenzioni di naming non sempre coerenti:
  - IMG_1234.jpg  →  IMG_1234.jpg.json   (più comune)
  - IMG_1234.jpg  →  IMG_1234.json        (variante)
  - IMG_1234(1).jpg → IMG_1234(1).jpg.json
  - nome_molto_lungo_della_fo...jpg.json  (troncato a ~46 char + estensione)
  - VID_20230415.mp4.supplemental-metadata.json  (export recenti)

Strategia di ricerca (in ordine):
  1. <nome>.<ext>.json          (es. foto.jpg.json)
  2. <nome>.json                (es. foto.json)
  3. <nome>.<ext>.supplemental-metadata.json
  4. Ricerca fuzzy nella stessa cartella e in cartella "metadata"
"""

import json
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Dict, Any

from .config import TAKEOUT_TRUNCATION_LENGTH, FUZZY_MATCH_THRESHOLD

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ricerca del file JSON
# ---------------------------------------------------------------------------

def find_json_for_media(media_path: str) -> Optional[str]:
    """
    Cerca il file JSON sidecar per il file multimediale dato.
    
    Args:
        media_path: Percorso assoluto del file multimediale.
    
    Returns:
        Percorso assoluto del JSON trovato, o None se non trovato.
    """
    media_path = Path(media_path)
    parent = media_path.parent
    stem = media_path.stem        # es. "IMG_1234"
    suffix = media_path.suffix    # es. ".jpg"
    name = media_path.name        # es. "IMG_1234.jpg"

    # --- Candidati diretti (ordine di priorità) ---
    candidates = [
        parent / f"{name}.json",                              # foto.jpg.json
        parent / f"{stem}.json",                              # foto.json
        parent / f"{name}.supplemental-metadata.json",        # export recenti
        parent / f"{stem}.supplemental-metadata.json",
        # Varianti con numero progressivo (es. foto(1).jpg.json)
        parent / f"{stem}{suffix}.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            logger.debug("JSON trovato (match diretto): %s", candidate)
            return str(candidate)

    # --- Ricerca fuzzy nella stessa cartella ---
    json_found = _fuzzy_search_in_dir(parent, name, stem)
    if json_found:
        return json_found

    # --- Alcune versioni di Takeout mettono i JSON in una sotto-cartella ---
    for subdir_name in ("metadata", ".metadata"):
        subdir = parent / subdir_name
        if subdir.is_dir():
            json_found = _fuzzy_search_in_dir(subdir, name, stem)
            if json_found:
                return json_found

    logger.warning("Nessun JSON trovato per: %s", media_path)
    return None


def _fuzzy_search_in_dir(
    directory: Path, media_name: str, media_stem: str
) -> Optional[str]:
    """
    Scansiona la directory cercando file .json il cui nome corrisponde
    (anche parzialmente/troncato) al file multimediale.
    
    Google Takeout tronca i nomi lunghi a circa 46 caratteri prima di
    aggiungere l'estensione .json, quindi dobbiamo confrontare il prefisso.
    """
    try:
        all_jsons = [
            f for f in directory.iterdir()
            if f.suffix.lower() == ".json"
        ]
    except PermissionError:
        return None

    best_score = 0.0
    best_match: Optional[Path] = None

    # Prefisso del nome media troncato alla lunghezza di Takeout
    truncated_stem = media_stem[:TAKEOUT_TRUNCATION_LENGTH]

    for json_file in all_jsons:
        json_stem = json_file.name  # es. "nome_molto_lungo_della_fo...jpg.json"

        # Rimuove il .json finale per confrontare il "corpo" del nome
        body = json_stem[: -len(".json")] if json_stem.endswith(".json") else json_stem

        # Tentativo 1: il body corrisponde esattamente al nome del media
        if body == media_name:
            return str(json_file)

        # Tentativo 2: il body è il nome del media troncato (Takeout truncation)
        if media_name.startswith(body.rstrip(".")) or body.startswith(truncated_stem):
            score = SequenceMatcher(None, body, media_name).ratio()
            if score > best_score:
                best_score = score
                best_match = json_file

        # Tentativo 3: similarità generica
        score = SequenceMatcher(None, body, media_name).ratio()
        if score > best_score:
            best_score = score
            best_match = json_file

    if best_match and best_score >= FUZZY_MATCH_THRESHOLD:
        logger.debug(
            "JSON trovato (fuzzy %.0f%%): %s → %s",
            best_score * 100, media_name, best_match.name,
        )
        return str(best_match)

    return None


# ---------------------------------------------------------------------------
# Parsing del file JSON
# ---------------------------------------------------------------------------

def parse_json_metadata(json_path: str) -> Dict[str, Any]:
    """
    Legge e parsa il file JSON di Google Takeout.
    
    Restituisce un dizionario con i campi rilevanti estratti e normalizzati:
      - 'timestamp'     : int (epoch Unix) della data di scatto (o 0 se assente)
      - 'latitude'      : float | None
      - 'longitude'     : float | None
      - 'altitude'      : float | None
      - 'description'   : str | None
      - 'title'         : str | None
      - 'raw'           : dict (contenuto JSON grezzo)
    
    Struttura tipica del JSON di Takeout:
    {
      "title": "IMG_1234.jpg",
      "description": "...",
      "photoTakenTime": { "timestamp": "1680000000", "formatted": "..." },
      "geoData": { "latitude": 45.1, "longitude": 7.7, "altitude": 300.0, ... },
      "geoDataExif": { ... },  // dati GPS originali dall'EXIF (a volte diversi)
      ...
    }
    """
    result: Dict[str, Any] = {
        "timestamp": 0,
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "description": None,
        "title": None,
        "raw": {},
    }

    try:
        with open(json_path, "r", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Errore parsing JSON %s: %s", json_path, exc)
        return result

    result["raw"] = data

    # --- Timestamp di scatto ---
    photo_taken = data.get("photoTakenTime", {})
    ts_str = photo_taken.get("timestamp", "0")
    try:
        result["timestamp"] = int(ts_str)
    except (ValueError, TypeError):
        result["timestamp"] = 0

    # --- Dati GPS ---
    # Preferisce geoDataExif (dati originali EXIF) rispetto a geoData (serverside)
    geo = data.get("geoDataExif") or data.get("geoData") or {}
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    alt = geo.get("altitude")

    # Google Takeout usa (0.0, 0.0) per indicare "nessuna posizione"
    if lat and lon and not (lat == 0.0 and lon == 0.0):
        result["latitude"] = float(lat)
        result["longitude"] = float(lon)
        if alt is not None:
            result["altitude"] = float(alt)

    # --- Testo ---
    result["description"] = data.get("description") or None
    result["title"] = data.get("title") or None

    return result
