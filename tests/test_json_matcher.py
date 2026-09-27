"""
tests/test_json_matcher.py
--------------------------
Test unitari per il modulo json_matcher.py

Verifica:
  - Match diretto (nome.jpg → nome.jpg.json)
  - Match variante (nome.jpg → nome.json)
  - Match con nome troncato da Takeout
  - Parsing corretto del JSON di Takeout
  - Gestione di JSON malformati
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from google_takeout_fixer.json_matcher import find_json_for_media, parse_json_metadata


class TestFindJsonForMedia(unittest.TestCase):

    def setUp(self):
        """Crea una cartella temporanea per i test."""
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        """Rimuove la cartella temporanea."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, name: str, content: str = "") -> str:
        """Crea un file nella cartella temporanea e restituisce il percorso."""
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_direct_match_jpg_json(self):
        """Trova nome.jpg.json dato nome.jpg"""
        media = self._make_file("IMG_1234.jpg")
        json_file = self._make_file("IMG_1234.jpg.json", "{}")
        result = find_json_for_media(media)
        self.assertEqual(result, json_file)

    def test_direct_match_stem_json(self):
        """Trova nome.json dato nome.jpg (variante senza estensione nel json)"""
        media = self._make_file("IMG_5678.jpg")
        json_file = self._make_file("IMG_5678.json", "{}")
        result = find_json_for_media(media)
        self.assertEqual(result, json_file)

    def test_supplemental_metadata(self):
        """Trova nome.jpg.supplemental-metadata.json"""
        media = self._make_file("VID_2023.mp4")
        json_file = self._make_file("VID_2023.mp4.supplemental-metadata.json", "{}")
        result = find_json_for_media(media)
        self.assertEqual(result, json_file)

    def test_no_json_returns_none(self):
        """Restituisce None se non c'è nessun JSON"""
        media = self._make_file("orphan.jpg")
        result = find_json_for_media(media)
        self.assertIsNone(result)

    def test_truncated_name_fuzzy(self):
        """
        Trova il JSON anche quando Takeout ha troncato il nome.
        Takeout tronca a ~46 caratteri, poi aggiunge estensione e .json
        """
        long_name = "vacanze_estate_2023_foto_bellissima_con_amici" + "_extras"
        media = self._make_file(long_name + ".jpg")
        # Simula il troncamento di Takeout
        truncated = long_name[:46]
        json_file = self._make_file(truncated + ".jpg.json", "{}")
        result = find_json_for_media(media)
        # Dovrebbe trovare il file JSON troncato tramite fuzzy matching
        self.assertIsNotNone(result)


class TestParseJsonMetadata(unittest.TestCase):

    def _write_json(self, data: dict) -> str:
        """Scrive un JSON temporaneo e restituisce il percorso."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, tmp)
        tmp.close()
        return tmp.name

    def tearDown(self):
        pass  # I file temp vengono puliti al termine del processo

    def test_full_metadata(self):
        """Parsa correttamente tutti i campi rilevanti."""
        data = {
            "title": "Foto di Natale",
            "description": "Una bella foto",
            "photoTakenTime": {"timestamp": "1703001600", "formatted": "2023"},
            "geoData": {
                "latitude": 45.4654,
                "longitude": 9.1859,
                "altitude": 122.0,
            },
        }
        path = self._write_json(data)
        result = parse_json_metadata(path)

        self.assertEqual(result["timestamp"], 1703001600)
        self.assertAlmostEqual(result["latitude"], 45.4654, places=3)
        self.assertAlmostEqual(result["longitude"], 9.1859, places=3)
        self.assertAlmostEqual(result["altitude"], 122.0, places=1)
        self.assertEqual(result["description"], "Una bella foto")
        self.assertEqual(result["title"], "Foto di Natale")
        os.unlink(path)

    def test_zero_gps_treated_as_none(self):
        """GPS (0.0, 0.0) deve essere ignorato (indica 'nessuna posizione')."""
        data = {
            "photoTakenTime": {"timestamp": "1000"},
            "geoData": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
        }
        path = self._write_json(data)
        result = parse_json_metadata(path)
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])
        os.unlink(path)

    def test_missing_timestamp_defaults_to_zero(self):
        """Se photoTakenTime manca, il timestamp deve essere 0."""
        path = self._write_json({"title": "test"})
        result = parse_json_metadata(path)
        self.assertEqual(result["timestamp"], 0)
        os.unlink(path)

    def test_malformed_json_returns_defaults(self):
        """JSON malformato restituisce valori di default senza eccezioni."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write("{INVALID JSON{{")
        tmp.close()
        result = parse_json_metadata(tmp.name)
        self.assertEqual(result["timestamp"], 0)
        self.assertIsNone(result["latitude"])
        os.unlink(tmp.name)

    def test_prefers_geoDataExif_over_geoData(self):
        """geoDataExif ha la precedenza su geoData."""
        data = {
            "photoTakenTime": {"timestamp": "1000"},
            "geoData": {"latitude": 10.0, "longitude": 20.0},
            "geoDataExif": {"latitude": 45.0, "longitude": 9.0},
        }
        path = self._write_json(data)
        result = parse_json_metadata(path)
        self.assertAlmostEqual(result["latitude"], 45.0)
        self.assertAlmostEqual(result["longitude"], 9.0)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
