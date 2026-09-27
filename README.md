# Google Takeout Fixer 🖼️

Uno script Python **robusto e scalabile** per riorganizzare e riparare archivi Google Takeout di Google Foto, anche di dimensioni multi-Terabyte.

## Funzionalità

| Funzionalità | Dettaglio |
|---|---|
| 🔧 **Metadati via ExifTool** | Inietta data di scatto e GPS dai file JSON sidecar |
| 🔁 **Deduplicazione** | Hash SHA-256 parziale + completo per eliminare i duplicati da Album |
| 📁 **Riorganizzazione** | Struttura `Destinazione/Anno/Mese/File` |
| 💾 **Resume con SQLite** | Riprende esattamente da dove si era interrotto |
| ⚡ **Parallelo** | `ThreadPoolExecutor` su tutti i core disponibili |
| 🪟 **Windows MAX_PATH** | Prefisso `\\?\` per percorsi >260 caratteri |
| 🔍 **Fuzzy JSON matching** | Trova i JSON anche con nomi troncati da Takeout |

---

## Requisiti di Sistema

- **Python** ≥ 3.9
- **ExifTool** di Phil Harvey (vedi sezione installazione)
- Sistema operativo: Windows / macOS / Linux

> **Nessuna libreria Python esterna richiesta.** Lo script usa solo la libreria standard.

---

## 1. Installazione ExifTool

### 🪟 Windows

**Metodo A — Installer (consigliato):**

1. Vai su [https://exiftool.org](https://exiftool.org)
2. Scarica **`exiftool-XX.XX.exe`** (Windows Executable)
3. Rinominalo in `exiftool.exe`
4. Copialo in `C:\Windows\` oppure in una cartella già nel `PATH`
   (es. `C:\Tools\` dopo averla aggiunta al PATH di sistema)
5. Verifica aprendo un nuovo terminale PowerShell:

```powershell
exiftool -ver
# Deve stampare il numero di versione, es.: 12.76
```

**Metodo B — Chocolatey (package manager):**

```powershell
# Installa Chocolatey se non presente (vedi https://chocolatey.org)
choco install exiftool
```

**Metodo C — Winget:**

```powershell
winget install OliverBetz.ExifTool
```

---

### 🍎 macOS

```bash
# Con Homebrew (consigliato)
brew install exiftool

# Verifica
exiftool -ver
```

---

### 🐧 Linux (Debian/Ubuntu)

```bash
sudo apt update && sudo apt install libimage-exiftool-perl

# Verifica
exiftool -ver
```

**Linux (Fedora/RHEL/CentOS):**

```bash
sudo dnf install perl-Image-ExifTool
```

**Linux — Installazione manuale (ultima versione):**

```bash
cd /tmp
curl -LO https://exiftool.org/Image-ExifTool-12.76.tar.gz
tar -xzf Image-ExifTool-12.76.tar.gz
cd Image-ExifTool-12.76
sudo make install      # installa exiftool in /usr/local/bin
exiftool -ver
```

---

## 2. Struttura del Progetto

```
Download Google Fotos/
│
├── run.py                          ← Entry point semplificato
├── requirements.txt
├── README.md
│
├── google_takeout_fixer/           ← Package principale
│   ├── __init__.py
│   ├── config.py                   ← Costanti configurabili
│   ├── main.py                     ← Orchestratore + CLI argparse
│   ├── scanner.py                  ← Scansione ricorsiva sorgente
│   ├── hasher.py                   ← Hash SHA-256 (deduplicazione)
│   ├── json_matcher.py             ← Ricerca fuzzy JSON sidecar + parsing
│   ├── exiftool_wrapper.py         ← Wrapper subprocess ExifTool
│   ├── path_utils.py               ← Percorsi sicuri, Anno/Mese, conflitti
│   ├── db_manager.py               ← SQLite thread-safe
│   └── processor.py                ← Elaborazione parallela
│
└── tests/
    ├── test_json_matcher.py
    ├── test_hasher.py
    └── test_path_utils.py
```

---

## 3. Come Lanciare lo Script

### Sintassi base

```powershell
# Windows PowerShell — dalla cartella del progetto
python run.py --source "D:\Takeout" --dest "E:\FotoOrganizzate"
```

```bash
# macOS / Linux — dalla cartella del progetto
python run.py --source /mnt/disco/Takeout --dest /mnt/dest/FotoOrganizzate
```

### Tutti gli argomenti disponibili

```
usage: google-takeout-fixer [-h] --source CARTELLA_SORGENTE
                             --dest CARTELLA_DESTINAZIONE
                             [--copy | --move]
                             [--workers N]
                             [--db FILE.db]
                             [--reset-errors]
                             [--dry-run]
                             [--log-level {DEBUG,INFO,WARNING,ERROR}]

Argomenti:
  --source, -s    Percorso cartella radice Takeout (obbligatorio)
  --dest,   -d    Percorso cartella destinazione   (obbligatorio)
  --copy          (default) Copia i file, gli originali restano intatti
  --move          Sposta i file (più veloce sullo stesso disco, irreversibile!)
  --workers N     Numero thread paralleli (default: numero CPU logiche)
  --db FILE.db    Percorso personalizzato del database SQLite
  --reset-errors  Riprova i file che erano andati in errore
  --dry-run       Simula senza toccare nulla (utile per stimare il lavoro)
  --log-level     DEBUG | INFO (default) | WARNING | ERROR
```

### Esempi pratici

```powershell
# ── Esecuzione tipica ──────────────────────────────────────────────
python run.py --source "D:\Google Takeout\Takeout" --dest "E:\Foto Organizzate"

# ── Con più thread (es. 12 core) ──────────────────────────────────
python run.py --source "D:\Takeout" --dest "E:\Foto" --workers 12

# ── Prima stima senza toccare nulla ───────────────────────────────
python run.py --source "D:\Takeout" --dest "E:\Foto" --dry-run

# ── Resume dopo interruzione (rilancia semplicemente) ─────────────
python run.py --source "D:\Takeout" --dest "E:\Foto"
# I file già elaborati vengono automaticamente saltati

# ── Riprova i file con errori ─────────────────────────────────────
python run.py --source "D:\Takeout" --dest "E:\Foto" --reset-errors

# ── Sposta i file (stesso disco, velocissimo) ─────────────────────
python run.py --source "D:\Takeout" --dest "D:\FotoOrganizzate" --move

# ── Log verboso per debug ─────────────────────────────────────────
python run.py --source "D:\Takeout" --dest "E:\Foto" --log-level DEBUG
```

---

## 4. Struttura della Destinazione

Dopo l'esecuzione, la cartella di destinazione avrà questa struttura:

```
E:\FotoOrganizzate\
│
├── 2019\
│   ├── 01\
│   │   ├── IMG_0001.jpg
│   │   └── VID_0002.mp4
│   └── 12\
│       └── IMG_1234.heic
│
├── 2022\
│   ├── 07\
│   │   └── foto_vacanze.jpg
│   └── 08\ ...
│
├── data_sconosciuta\      ← file senza timestamp JSON
│   └── 00\ ...
│
├── takeout_fixer_state.db ← database SQLite di stato
└── takeout_fixer.log      ← log completo dell'esecuzione
```

---

## 5. Come Funziona la Deduplicazione

Google Takeout crea duplicati perché la stessa foto può trovarsi sia nella
cartella cronologica ("Foto del 2023") sia nelle cartelle degli Album
("Vacanze estate", "Preferite", ecc.).

Lo script usa una strategia a **due hash**:

```
Per ogni file:
  1. Calcola SHA-256 parziale (primi 4 MB) — molto veloce
  2. Se lo stesso hash è già nel DB con status='processed' → DUPLICATO → skip
  3. Altrimenti → elabora e registra l'hash nel DB
```

> 💡 La probabilità di collisione SHA-256 su 4 MB è astronomicamente bassa
> (~1 su 2^128). Per archivi di foto/video è assolutamente sicura.

---

## 6. Gestione dei File JSON Sidecar

Google Takeout usa queste convenzioni di naming:

| File media | File JSON cercato (in ordine) |
|---|---|
| `IMG_1234.jpg` | `IMG_1234.jpg.json` |
| `IMG_1234.jpg` | `IMG_1234.json` |
| `VID_2023.mp4` | `VID_2023.mp4.supplemental-metadata.json` |
| `nome_molto_lungo_della_fo...` | Fuzzy match con soglia 70% di similarità |

Il fuzzy matching usa `difflib.SequenceMatcher` per gestire i troncamenti
di Takeout (nomi lunghi troncati a ~46 caratteri prima di `.json`).

---

## 7. Database SQLite — Monitoraggio

Il file `takeout_fixer_state.db` nella cartella di destinazione tiene traccia
dello stato di ogni file. Puoi interrogarlo con qualsiasi client SQLite:

```sql
-- Riepilogo per status
SELECT status, COUNT(*) FROM files GROUP BY status;

-- File con errori
SELECT source_path, error_msg FROM files WHERE status = 'error';

-- File elaborati oggi
SELECT source_path, dest_path FROM files
WHERE status = 'processed'
AND processed_at > datetime('now', '-1 day');

-- Statistiche totali
SELECT
  COUNT(*) as totale,
  SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) as processati,
  SUM(CASE WHEN status = 'duplicate' THEN 1 ELSE 0 END) as duplicati
FROM files;
```

**Client SQLite consigliati:**
- [DB Browser for SQLite](https://sqlitebrowser.org/) (gratuito, Windows/macOS/Linux)
- DBeaver Community Edition
- VS Code con estensione SQLite Viewer

---

## 8. Configurazione Avanzata

Tutti i parametri configurabili si trovano in
[`google_takeout_fixer/config.py`](google_takeout_fixer/config.py):

```python
# Modalità copia (True) o sposta (False)
COPY_FILES = True

# Dimensione blocco per hash parziale (default: 4 MB)
PARTIAL_HASH_BYTES = 4 * 1024 * 1024

# Timeout ExifTool per file singolo (secondi)
EXIFTOOL_TIMEOUT = 60

# Soglia fuzzy matching JSON (0.0 – 1.0)
FUZZY_MATCH_THRESHOLD = 0.7

# Numero di file nel batch SQLite
DB_COMMIT_BATCH = 200

# Numero worker thread (None = os.cpu_count())
MAX_WORKERS = None
```

---

## 9. Esecuzione dei Test

```bash
# Dalla cartella radice del progetto
python -m pytest tests/ -v

# Con report copertura (richiede: pip install pytest-cov)
python -m pytest tests/ --cov=google_takeout_fixer --cov-report=term-missing
```

---

## 10. Risoluzione Problemi

### ExifTool non trovato

```
RuntimeError: ExifTool non trovato nel PATH.
```

→ Verifica che `exiftool -ver` funzioni nel terminale. Se hai installato
ExifTool ma lo script non lo trova, specifica il percorso nel file
`config.py` aggiungendo la funzione `find_exiftool()` personalizzata.

### Errori MAX_PATH su Windows

Se vedi errori `FileNotFoundError` con percorsi molto lunghi:

1. Abilita il supporto percorsi lunghi in Windows:
   - `Win + R` → `gpedit.msc` → Configurazione Computer → Modelli
     Amministrativi → Sistema → File System → Abilita percorsi Win32 lunghi
2. Oppure: sposta la cartella sorgente più vicina alla radice del disco
   (es. `D:\TK\` invece di `D:\Backup\Google\Takeout 2023\...`)

### Processo lento / troppa RAM

- Riduci `--workers` (meno thread = meno memoria)
- Abbassa `DB_COMMIT_BATCH` in `config.py` per flush più frequenti
- Usa `--move` invece di `--copy` se sorgente e destinazione sono sullo stesso disco

### File video senza metadati dopo l'elaborazione

ExifTool supporta la maggior parte dei formati video, ma alcuni tag
specifici (es. `TrackCreateDate` in .MTS) potrebbero richiedere un
pacchetto Perl aggiuntivo. Controlla i log con `--log-level DEBUG`.

---

## 11. Note Legali e Sicurezza

- Lo script non carica nessun dato su internet.
- **Non modifica mai i file sorgenti originali**: opera sempre su
  una copia nella destinazione (modalità `--copy` predefinita).
- Con `--move` i file vengono rimossi dalla sorgente: usa con cautela.

---

## Licenza

MIT — Libero per uso personale e commerciale.
