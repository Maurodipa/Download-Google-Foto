"""
run.py
------
Script di avvio semplificato per chi non vuole usare la sintassi
del modulo Python (-m google_takeout_fixer.main).

Uso equivalente:
    python run.py --source D:/Takeout --dest E:/FotoOrganizzate
"""

import sys
from google_takeout_fixer.main import main

if __name__ == "__main__":
    sys.exit(main())
