"""
tests/test_path_utils.py
------------------------
Test unitari per path_utils.py

Verifica:
  - Sanitizzazione nomi file con caratteri illegali
  - Gestione nomi riservati Windows
  - Costruzione struttura Anno/Mese nella destinazione
  - Risoluzione conflitti nomi file
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from google_takeout_fixer.path_utils import (
    sanitize_filename,
    build_dest_path,
    resolve_conflict,
    make_safe_path,
)


class TestSanitizeFilename(unittest.TestCase):

    def test_normal_filename_unchanged(self):
        self.assertEqual(sanitize_filename("IMG_1234.jpg"), "IMG_1234.jpg")

    def test_removes_illegal_chars_windows(self):
        result = sanitize_filename('foto<>:"/\\|?*.jpg')
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertNotIn(":", result)
        self.assertNotIn('"', result)
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)
        self.assertNotIn("|", result)
        self.assertNotIn("?", result)

    def test_reserved_names(self):
        result = sanitize_filename("CON.jpg")
        self.assertNotEqual(result.upper(), "CON.JPG")

    def test_preserves_extension(self):
        result = sanitize_filename("test<name>.jpeg")
        self.assertTrue(result.endswith(".jpeg"))

    def test_truncation(self):
        long_name = "a" * 300 + ".jpg"
        result = sanitize_filename(long_name, max_length=200)
        self.assertLessEqual(len(result), 204)  # 200 stem + ".jpg"

    def test_empty_stem_gets_default(self):
        """Un filename con solo estensione (stem vuoto) riceve lo stem 'unnamed'."""
        result = sanitize_filename(".jpg")
        self.assertTrue(result.endswith(".jpg"))
        # "unnamed.jpg" = 11 chars; verifica che lo stem non sia vuoto
        self.assertGreater(len(result), len(".jpg"))


class TestBuildDestPath(unittest.TestCase):

    def test_valid_timestamp(self):
        """File con timestamp valido finisce in Anno/Mese corretto."""
        # 2023-06-15 12:00:00 UTC
        ts = int(datetime(2023, 6, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        path = build_dest_path("/dest", "foto.jpg", ts)
        parts = path.replace("\\", "/").split("/")
        self.assertIn("2023", parts)
        self.assertIn("06", parts)
        self.assertIn("foto.jpg", parts)

    def test_zero_timestamp_goes_to_unknown(self):
        """File senza data va nella cartella 'data_sconosciuta'."""
        path = build_dest_path("/dest", "foto.jpg", 0)
        self.assertIn("data_sconosciuta", path)

    def test_negative_timestamp(self):
        """Timestamp negativo non causa eccezioni."""
        path = build_dest_path("/dest", "old.jpg", -1)
        self.assertIn("data_sconosciuta", path)


class TestResolveConflict(unittest.TestCase):

    def test_no_conflict(self):
        """Se il file non esiste, restituisce il percorso originale."""
        path = "/tmp/questo_file_non_esiste_davvero_12345.jpg"
        result = resolve_conflict(path)
        self.assertEqual(result, path)

    def test_conflict_adds_suffix(self):
        """Se il file esiste, aggiunge un suffisso numerico."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            existing = tmp.name

        try:
            result = resolve_conflict(existing)
            self.assertNotEqual(result, existing)
            self.assertTrue(result.endswith(".jpg"))
        finally:
            os.unlink(existing)


if __name__ == "__main__":
    unittest.main()
