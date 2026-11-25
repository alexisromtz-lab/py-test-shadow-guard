"""Un repositorio git real: dos ramas, merge limpio, un test perdido."""

import json
import pathlib
import subprocess
import tempfile
import unittest

from py_test_shadow_guard.cli import main

BASE_PY = """import unittest


class ElPredicadoMuerde(unittest.TestCase):
    def test_35_original(self):
        self.assertTrue(True)
"""

RAMA_A = BASE_PY.replace(
    "    def test_35_original(self):",
    "    def test_35_alpha(self):\n        self.assertTrue(True)\n\n    def test_35_original(self):",
)
RAMA_B = BASE_PY.replace(
    "    def test_35_original(self):",
    "    def test_35_beta(self):\n        self.assertTrue(True)\n\n    def test_35_original(self):",
)


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True)


class TestExtremoAExtremo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "prueba@ejemplo.test")
        _git(self.repo, "config", "user.name", "Prueba")
        self._commit("tests/test_x.py", BASE_PY, "base")
        for rama, contenido in (("a", RAMA_A), ("b", RAMA_B)):
            _git(self.repo, "checkout", "-q", "-b", rama, "main")
            self._commit("tests/test_x.py", contenido, rama)
        _git(self.repo, "checkout", "-q", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, ruta, contenido, mensaje):
        destino = self.repo / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", mensaje)

    def test_detecta_la_colision_y_devuelve_rc_1(self):
        rc = main(["--repo", str(self.repo), "--base", "main", "--ref", "a", "--ref", "b"])
        self.assertEqual(rc, 1)

    def test_json_publica_el_hallazgo(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(
                ["--repo", str(self.repo), "--base", "main", "--ref", "a", "--ref", "b", "--json"]
            )
        datos = json.loads(buffer.getvalue())
        self.assertEqual(rc, 1)
        self.assertEqual(datos["rc"], 1)
        self.assertEqual(len(datos["rojos"]), 1)
        self.assertIn("test_35_alpha", datos["rojos"][0]["a"])
        self.assertIn("test_35_beta", datos["rojos"][0]["b"])

    def test_ref_invalida_devuelve_rc_2(self):
        rc = main(["--repo", str(self.repo), "--base", "main", "--ref", "no-existe"])
        self.assertEqual(rc, 2)


class TestSinSujeto(unittest.TestCase):
    def test_rama_que_no_toca_tests_da_verde(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            _git(repo, "init", "-q", "-b", "main")
            _git(repo, "config", "user.email", "prueba@ejemplo.test")
            _git(repo, "config", "user.name", "Prueba")
            (repo / "modulo.py").write_text("X = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "base")
            _git(repo, "checkout", "-q", "-b", "a")
            (repo / "modulo.py").write_text("X = 2\n", encoding="utf-8")
            _git(repo, "commit", "-q", "-am", "a")
            self.assertEqual(main(["--repo", str(repo), "--base", "main", "--ref", "a"]), 0)


if __name__ == "__main__":
    unittest.main()
