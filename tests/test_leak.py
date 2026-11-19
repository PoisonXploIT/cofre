"""Pruebas del escaner de fugas (paso 3.4, 2026-11-18).

Lo importante que se comprueba aqui: encuentra el secreto pegado, no lo muestra
nunca, y no se cae con carpetas raras.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import leak


def _clave() -> bytes:
    return leak.clave_de_huellas(b"k" * 32)


class TestHuellas(unittest.TestCase):
    def test_el_valor_no_viaja_en_la_huella(self):
        clave = _clave()
        tabla, cortos = leak.huellas_de(clave, {"SECRETO": "restauracion-ok-42"})
        self.assertEqual(len(tabla), 1)
        self.assertEqual(cortos, [])
        for huella in tabla:
            self.assertNotIn(b"restauracion", huella)

    def test_cortos_y_no_tokens_van_por_subcadena(self):
        tabla, cortos = leak.huellas_de(_clave(), {
            "LARGO": "abcdefghijkl",
            "CORTO": "ab",
            "CON_SEPARADORES": "usuario:clave:1",
        })
        self.assertEqual(len(tabla), 1)
        self.assertEqual(sorted(n for n, _ in cortos), ["CON_SEPARADORES", "CORTO"])

    def test_dos_cofres_no_comparten_huellas(self):
        uno, _ = leak.huellas_de(leak.clave_de_huellas(b"a" * 32), {"S": "valor-largo-1"})
        otro, _ = leak.huellas_de(leak.clave_de_huellas(b"b" * 32), {"S": "valor-largo-1"})
        self.assertNotEqual(list(uno), list(otro))


class TestEscaneo(unittest.TestCase):
    def setUp(self):
        self.clave = _clave()
        self.tabla, self.cortos = leak.huellas_de(self.clave, {
            "CF_TEST_TOKEN": "valor-de-prueba",
            "SIMULACRO_RESTAURA": "restauracion-ok-42",
            "CORTO": "xy",
        })
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-leak-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detecta_dentro_de_una_asignacion(self):
        hallazgos = leak.escanear_texto(
            "A=1\nCF_TOKEN=valor-de-prueba\n", self.clave, self.tabla, self.cortos)
        self.assertEqual(hallazgos, [(2, "CF_TEST_TOKEN")])

    def test_detecta_el_corto_por_subcadena(self):
        hallazgos = leak.escanear_texto("login: xy\n", self.clave, self.tabla,
                                        self.cortos)
        self.assertEqual(hallazgos, [(1, "CORTO")])

    def test_lo_limpio_no_salta(self):
        self.assertEqual(leak.escanear_texto("nada que ver\n", self.clave,
                                             self.tabla, self.cortos), [])

    def test_carpeta_salta_excluidos_y_binarias(self):
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "app.py").write_text("ok = 1\n", encoding="utf-8")
        (self.tmp / ".git").mkdir()
        (self.tmp / ".git" / "config").write_text("valor-de-prueba\n", encoding="utf-8")
        (self.tmp / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nvalor-de-prueba")
        (self.tmp / "fuga.txt").write_text("restauracion-ok-42\n", encoding="utf-8")
        rutas = [r.name for r, _l, _n in leak.escanear_carpeta(
            self.tmp, self.clave, self.tabla, self.cortos)]
        self.assertEqual(rutas, ["fuga.txt"])

    def test_escenificados_ve_lo_del_commit(self):
        try:
            subprocess.run(["git", "init", "-q", str(self.tmp)], check=True,
                           capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("sin git")
        fichero = self.tmp / "secreto.env"
        fichero.write_text("TOKEN=valor-de-prueba\n", encoding="utf-8")
        self.assertEqual(leak.escanear_escenificados(
            self.tmp, self.clave, self.tabla, self.cortos), [])
        subprocess.run(["git", "-C", str(self.tmp), "add", "secreto.env"], check=True,
                       capture_output=True)
        hallazgos = leak.escanear_escenificados(self.tmp, self.clave, self.tabla,
                                                self.cortos)
        self.assertEqual([(r.name, l, n) for r, l, n in hallazgos],
                         [("secreto.env", 1, "CF_TEST_TOKEN")])


if __name__ == "__main__":
    unittest.main()


class TestCodigoDeRecuperacion(unittest.TestCase):
    """Regla del incidente 2026-11-19: 24 palabras seguidas de la lista = código.

    La lista es de palabras frecuentes, así que la regla pide además 18 distintas
    para no bloquear prosa normal.
    """

    def setUp(self):
        from cofre.leak import palabras_del_codigo
        self.lista = sorted(palabras_del_codigo())

    def test_24_seguidas_saltan(self):
        from cofre.leak import codigos_de_recuperacion
        texto = " ".join(self.lista[:24])
        self.assertEqual(codigos_de_recuperacion(texto), [(1, 24)])

    def test_23_no_saltan(self):
        from cofre.leak import codigos_de_recuperacion
        self.assertEqual(codigos_de_recuperacion(" ".join(self.lista[:23])), [])

    def test_con_comas_y_mayusculas(self):
        from cofre.leak import codigos_de_recuperacion
        texto = ", ".join(p.upper() for p in self.lista[:24])
        self.assertEqual(len(codigos_de_recuperacion(texto)), 1)

    def test_prosa_normal_no_salta(self):
        from cofre.leak import codigos_de_recuperacion
        prosa = ("para que como pero este esta todo cuando sobre todos tiene porque "
                 "bien entre puede desde hasta hacer ahora esto hace otra vez como "
                 "siempre y nunca")
        self.assertEqual(codigos_de_recuperacion(prosa), [])

    def test_el_escaneo_lo_marca_como_fuga(self):
        from cofre.leak import NOMBRE_CODIGO, escanear_texto, huellas_de, clave_de_huellas
        clave = clave_de_huellas(b"k" * 32)
        tabla, cortos = huellas_de(clave, {})
        hallazgos = escanear_texto(" ".join(self.lista[:24]), clave, tabla, cortos)
        self.assertEqual(hallazgos, [(1, NOMBRE_CODIGO)])
