"""
main.py
-------
Entry point dello script Google Takeout Fixer.

Orchestratore principale che:
  1. Parsa gli argomenti da riga di comando (argparse)
  2. Configura il logging su file + console
  3. Verifica che ExifTool sia installato
  4. Apre/crea il database SQLite di stato
  5. Scansiona la sorgente e registra i file nel DB
  6. Avvia l'elaborazione parallela
  7. Stampa le statistiche finali

Uso:
    python -m google_takeout_fixer.main \\
        --source "D:/Takeout" \\
        --dest   "E:/Foto Organizzate" \\
        [--workers 8] \\
        [--copy | --move] \\
        [--reset-errors] \\
        [--dry-run] \\
        [--log-level DEBUG]
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Importazioni interne al package
from . import __version__
from .config import (
    DB_FILENAME,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    MAX_WORKERS,
    COPY_FILES,
)
from . import config as cfg
from .db_manager import initialize_db, get_stats
from .exiftool_wrapper import check_exiftool
from .scanner import scan_and_register, get_files_to_process
from .processor import process_all_files


# ---------------------------------------------------------------------------
# Configurazione Logging
# ---------------------------------------------------------------------------

def setup_logging(log_level: str, log_file: str) -> None:
    """
    Configura il logging su:
    - Console (StreamHandler): mostra INFO e superiori con colori ANSI se disponibili
    - File (FileHandler): registra tutto al livello specificato
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # cattura tutto; i handler filtrano

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # --- Handler console ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # --- Handler file ---
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # tutto nel file
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        logging.getLogger(__name__).info("Log file: %s", log_file)
    except OSError as exc:
        logging.getLogger(__name__).warning("Impossibile aprire log file: %s", exc)


# ---------------------------------------------------------------------------
# Parser argomenti
# ---------------------------------------------------------------------------

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="google-takeout-fixer",
        description=(
            "Riorganizza e ripara un archivio Google Takeout:\n"
            "  - Deduplica i file tramite hash SHA-256\n"
            "  - Inietta metadati (data, GPS) dai JSON sidecar via ExifTool\n"
            "  - Organizza i file nella struttura Destinazione/Anno/Mese\n"
            "  - Supporta resume tramite database SQLite"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Argomenti obbligatori
    parser.add_argument(
        "--source", "-s",
        required=True,
        metavar="CARTELLA_SORGENTE",
        help="Percorso della cartella radice del Takeout di Google (es. D:/Takeout)",
    )
    parser.add_argument(
        "--dest", "-d",
        required=True,
        metavar="CARTELLA_DESTINAZIONE",
        help="Percorso della cartella di destinazione (es. E:/FotoOrganizzate)",
    )

    # Modalità copia vs spostamento
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--copy",
        action="store_true",
        default=True,
        help="(Default) Copia i file nella destinazione, lasciando intatti gli originali",
    )
    mode_group.add_argument(
        "--move",
        action="store_true",
        help="Sposta i file nella destinazione (più veloce sullo stesso disco, irreversibile)",
    )

    # Thread
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        metavar="N",
        help=f"Numero di thread paralleli (default: numero di CPU logiche = {os.cpu_count()})",
    )

    # Database
    parser.add_argument(
        "--db",
        metavar="FILE.db",
        default=None,
        help=(
            f"Percorso personalizzato per il database SQLite "
            f"(default: <dest>/{DB_FILENAME})"
        ),
    )

    # Retry degli errori
    parser.add_argument(
        "--reset-errors",
        action="store_true",
        help="Reimposta a 'pending' tutti i file con status='error' per ritentarli",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula l'elaborazione senza copiare file o modificare metadati",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Livello di dettaglio del log (default: INFO)",
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Entry point principale. Restituisce 0 se tutto ok, 1 in caso di errore.
    """
    parser = build_argument_parser()
    args = parser.parse_args()

    # --- Validazione percorsi ---
    source = os.path.abspath(args.source)
    dest = os.path.abspath(args.dest)

    if not os.path.isdir(source):
        print(f"ERRORE: La cartella sorgente non esiste: {source}", file=sys.stderr)
        return 1

    # Crea la destinazione se non esiste
    os.makedirs(dest, exist_ok=True)

    # --- Percorso DB ---
    db_path = args.db if args.db else os.path.join(dest, DB_FILENAME)

    # --- Percorso log ---
    log_file = os.path.join(dest, "takeout_fixer.log")

    # --- Setup logging ---
    setup_logging(args.log_level, log_file)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Google Takeout Fixer v%s", __version__)
    logger.info("  Sorgente    : %s", source)
    logger.info("  Destinazione: %s", dest)
    logger.info("  Database    : %s", db_path)
    logger.info("  Modalità    : %s", "COPIA" if not args.move else "SPOSTA")
    logger.info("  Dry Run     : %s", "SÌ" if args.dry_run else "NO")
    logger.info("=" * 60)

    # Applica configurazioni runtime
    if args.move:
        cfg.COPY_FILES = False
    if args.workers:
        cfg.MAX_WORKERS = args.workers
    if args.dry_run:
        # In dry-run non modifichiamo config, ma lo gestiamo nel flusso
        logger.info("[DRY RUN] Nessun file sarà modificato o copiato.")

    # --- Verifica ExifTool ---
    try:
        exiftool_exe = check_exiftool()
    except RuntimeError as exc:
        logger.critical("ExifTool non disponibile: %s", exc)
        return 1

    # --- Inizializzazione DB ---
    conn = initialize_db(db_path)

    # --- Reset errori se richiesto ---
    if args.reset_errors:
        with conn:
            count = conn.execute(
                "UPDATE files SET status='pending', error_msg=NULL WHERE status='error'"
            ).rowcount
        logger.info("Reset errori: %d file reimpostati a 'pending'", count)

    # --- Scansione sorgente ---
    total_found, newly_registered = scan_and_register(source, conn)

    # --- Statistiche pre-elaborazione ---
    pre_stats = get_stats(conn)
    logger.info("Stato DB prima dell'elaborazione: %s", pre_stats)

    if args.dry_run:
        logger.info("[DRY RUN] Termine. Nessun file elaborato.")
        conn.close()
        return 0

    # --- Lista file da elaborare ---
    files_to_process = get_files_to_process(conn)

    if not files_to_process:
        logger.info("Nessun file da elaborare. L'archivio è già aggiornato.")
        conn.close()
        return 0

    # --- Progress callback per il terminale ---
    _last_print = [time.monotonic()]

    def progress_callback(completed: int, total: int, status: str) -> None:
        """Stampa una barra di avanzamento semplice ogni 5 secondi."""
        now = time.monotonic()
        if now - _last_print[0] >= 5.0 or completed == total:
            pct = completed / total * 100
            bar_len = 40
            filled = int(bar_len * completed / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(
                f"\r  [{bar}] {completed}/{total} ({pct:.1f}%) — ultimo: {status}",
                end="", flush=True,
            )
            _last_print[0] = now
            if completed == total:
                print()  # newline finale

    # --- Elaborazione ---
    start = time.monotonic()
    try:
        process_all_files(
            files_to_process=files_to_process,
            dest_root=dest,
            conn=conn,
            exiftool_exe=exiftool_exe,
            progress_callback=progress_callback,
        )
    except KeyboardInterrupt:
        logger.warning("\nInterrotto dall'utente. Riesegui lo script per riprendere.")
        conn.close()
        return 130  # convenzione UNIX per Ctrl+C

    elapsed = time.monotonic() - start

    # --- Statistiche finali ---
    final_stats = get_stats(conn)
    logger.info("Statistiche finali:")
    for status, count in sorted(final_stats.items()):
        logger.info("  %-12s: %d", status, count)
    logger.info("Tempo totale: %.1f secondi", elapsed)

    conn.close()

    errors = final_stats.get("error", 0)
    if errors > 0:
        logger.warning(
            "%d file hanno avuto errori. Usa --reset-errors per ritentarli.", errors
        )
        return 1

    return 0


# ---------------------------------------------------------------------------
# Entry point da riga di comando
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
