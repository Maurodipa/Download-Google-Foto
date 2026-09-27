"""
config.py
---------
Configurazione centralizzata per google_takeout_fixer.
Tutte le costanti e i parametri modificabili dall'utente si trovano qui.
"""

import os

# ---------------------------------------------------------------------------
# Estensioni supportate
# ---------------------------------------------------------------------------

# Estensioni di immagini supportate da ExifTool
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".raw", ".cr2", ".cr3", ".nef",
    ".arw", ".dng", ".orf", ".rw2", ".pef", ".srw",
}

# Estensioni video supportate da ExifTool
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".wmv",
    ".mts", ".m2ts", ".mpg", ".mpeg", ".flv", ".webm",
}

# Insieme completo dei media supportati
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# ---------------------------------------------------------------------------
# Parametri di hashing (deduplicazione)
# ---------------------------------------------------------------------------

# Numero di byte letti per l'hash parziale "veloce" (4 MB)
# Usato per un pre-filtro rapido; se due file hanno lo stesso hash parziale
# si passa all'hash completo per confermare.
PARTIAL_HASH_BYTES = 4 * 1024 * 1024  # 4 MB

# Algoritmo usato per l'hash
HASH_ALGORITHM = "sha256"

# ---------------------------------------------------------------------------
# Parametri ExifTool
# ---------------------------------------------------------------------------

# Timeout in secondi per ogni singola invocazione di ExifTool
EXIFTOOL_TIMEOUT = 60

# Numero massimo di file passati in una singola chiamata batch a ExifTool
# (oltre questo numero si fa batching per evitare argomenti troppo lunghi)
EXIFTOOL_BATCH_SIZE = 100

# ---------------------------------------------------------------------------
# Database SQLite
# ---------------------------------------------------------------------------

# Nome del file DB; verrà creato nella cartella di destinazione
DB_FILENAME = "takeout_fixer_state.db"

# ---------------------------------------------------------------------------
# Threading
# ---------------------------------------------------------------------------

# Numero di worker per il thread pool.
# None = usa os.cpu_count()
MAX_WORKERS = None

# Numero di file in coda prima di fare flush sul DB
DB_COMMIT_BATCH = 200

# ---------------------------------------------------------------------------
# Windows MAX_PATH
# ---------------------------------------------------------------------------

# Prefisso UNC per superare il limite dei 260 caratteri su Windows
WINDOWS_LONG_PATH_PREFIX = "\\\\?\\"

# ---------------------------------------------------------------------------
# Fuzzy matching JSON
# ---------------------------------------------------------------------------

# Lunghezza massima del nome base (senza estensione) nei file JSON troncati
# da Google Takeout. Takeout tronca a ~46 caratteri.
TAKEOUT_TRUNCATION_LENGTH = 46

# Soglia di similarità (0.0–1.0) per il fuzzy matching del nome file
FUZZY_MATCH_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# Organizzazione destinazione
# ---------------------------------------------------------------------------

# Formato cartella anno/mese nella destinazione
DEST_YEAR_FORMAT = "%Y"
DEST_MONTH_FORMAT = "%m"  # zero-padded

# Se True, copia il file (mantiene l'originale); se False, sposta il file
COPY_FILES = True  # Cambia a False per uno spostamento (più veloce su stesso disco)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
