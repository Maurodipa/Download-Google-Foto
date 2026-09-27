"""
tests/test_hasher.py
--------------------
Test unitari per il modulo hasher.py

Verifica:
  - Hash deterministico (stesso file → stesso hash)
  - File diversi producono hash diversi
  - File vuoti
  - File inesistente restituisce None
"""

import os
import tempfile
import unittest

from google_takeout_fixer.hasher import compute_dedup_hash, partial_hash, full_hash


class TestHasher(unittest.TestCase):

    def _make_temp_file(self, content: bytes) -> str:
        """Crea un file temporaneo con il contenuto dato."""
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(content)
        tmp.close()
        return tmp.name

    def tearDown(self):
        pass

    def test_same_content_same_hash(self):
        """Lo stesso contenuto deve produrre lo stesso hash."""
        content = b"A" * 1024
        f1 = self._make_temp_file(content)
        f2 = self._make_temp_file(content)
        h1 = compute_dedup_hash(f1)
        h2 = compute_dedup_hash(f2)
        self.assertEqual(h1, h2)
        os.unlink(f1)
        os.unlink(f2)

    def test_different_content_different_hash(self):
        """Contenuto diverso deve produrre hash diverso."""
        f1 = self._make_temp_file(b"AAAA")
        f2 = self._make_temp_file(b"BBBB")
        h1 = compute_dedup_hash(f1)
        h2 = compute_dedup_hash(f2)
        self.assertNotEqual(h1, h2)
        os.unlink(f1)
        os.unlink(f2)

    def test_empty_file(self):
        """File vuoto deve restituire un hash valido (SHA-256 dell'input vuoto)."""
        f = self._make_temp_file(b"")
        h = compute_dedup_hash(f)
        self.assertIsNotNone(h)
        self.assertEqual(len(h), 64)  # SHA-256 = 64 caratteri hex
        os.unlink(f)

    def test_nonexistent_file_returns_none(self):
        """File inesistente deve restituire None senza eccezioni."""
        h = compute_dedup_hash("/percorso/che/non/esiste/mai.jpg")
        self.assertIsNone(h)

    def test_hash_is_hex_string(self):
        """L'hash deve essere una stringa esadecimale."""
        f = self._make_temp_file(b"test content")
        h = compute_dedup_hash(f)
        self.assertIsNotNone(h)
        int(h, 16)  # deve poter essere parsato come esadecimale
        os.unlink(f)

    def test_partial_hash_consistent(self):
        """L'hash parziale deve essere stabile."""
        content = b"X" * (5 * 1024 * 1024)  # 5 MB
        f = self._make_temp_file(content)
        h1 = partial_hash(f)
        h2 = partial_hash(f)
        self.assertEqual(h1, h2)
        os.unlink(f)


if __name__ == "__main__":
    unittest.main()
