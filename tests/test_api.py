"""Testes de API: persistência de músicas fora do repo e teste de sistema.

Rodam em modo simulador e usam um MUSIC_DATA_DIR temporário para não tocar
nos dados reais.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HARDWARE_MODE", "simulator")
# Diretório de dados isolado ANTES de importar o app (é lido no import).
_TMP = tempfile.mkdtemp(prefix="mgtest-")
os.environ["MUSIC_DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from backend import main  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_data_dir_is_outside_repo(self):
        repo = Path(main.__file__).resolve().parents[1]
        self.assertFalse(str(main.SONGS).startswith(str(repo)))

    def test_seed_songs_are_listed(self):
        with self.client as c:
            ids = [s["id"] for s in c.get("/api/songs").json()]
        self.assertIn("demo", ids)
        self.assertIn("demo-loop", ids)

    def test_uploaded_song_persists_in_data_dir_and_lists(self):
        # Grava uma música direto na pasta de dados e confirma que aparece.
        folder = main.SONGS / "musica-do-usuario"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "chart.json").write_text(
            '{"id":"musica-do-usuario","title":"User","events":[]}', encoding="utf-8"
        )
        with self.client as c:
            ids = [s["id"] for s in c.get("/api/songs").json()]
        self.assertIn("musica-do-usuario", ids)
        # Continua fora do repositório (sobrevive a atualizações de código).
        self.assertTrue(str(folder).startswith(_TMP))

    def test_system_test_endpoint(self):
        with self.client as c:
            r = c.post("/api/system-test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_youtube_without_url_is_rejected(self):
        with self.client as c:
            r = c.post("/api/songs", data={"title": "x", "generation_mode": "youtube"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
