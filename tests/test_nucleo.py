import unittest

from py_test_shadow_guard import nucleo
from py_test_shadow_guard.cli import _canario

FUENTE = '''
import unittest

def test_suelto():
    pass

def ayudante_no_es_test():
    pass

class Caso(unittest.TestCase):
    def test_01_uno(self):
        pass

    async def test_02_dos(self):
        pass

    def prepara(self):
        pass

    class Anidada(unittest.TestCase):
        def test_03_tres(self):
            pass
'''


class TestOrdinal(unittest.TestCase):
    def test_extrae_prefijo(self):
        self.assertEqual(nucleo.ordinal("test_35_algo"), 35)
        self.assertEqual(nucleo.ordinal("test_35"), 35)
        self.assertEqual(nucleo.ordinal("test35"), 35)
        self.assertIsNone(nucleo.ordinal("test_algo"))


class TestExtraccion(unittest.TestCase):
    def test_clase_anidada_modulo_y_async(self):
        encontrados = nucleo.metodos(FUENTE, "tests/test_x.py")
        rotulos = {m.rotulo() for m in encontrados}
        self.assertEqual(
            rotulos,
            {
                "tests/test_x.py::test_suelto",
                "tests/test_x.py::Caso.test_01_uno",
                "tests/test_x.py::Caso.test_02_dos",
                "tests/test_x.py::Caso.Anidada.test_03_tres",
            },
        )

    def test_sintaxis_rota_no_revienta(self):
        self.assertEqual(nucleo.metodos("def (:", "tests/test_x.py"), [])

    def test_una_fuente_ilegible_no_es_un_archivo_sin_tests(self):
        obtenidos, motivo = nucleo.leer("def (:", "tests/test_x.py")
        self.assertEqual(obtenidos, [])
        self.assertTrue(motivo and "sintaxis" in motivo)

        legibles, motivo_limpio = nucleo.leer(FUENTE, "tests/test_x.py")
        self.assertTrue(legibles)
        self.assertIsNone(motivo_limpio)

    def test_byte_nulo_no_revienta_en_ninguna_version(self):
        obtenidos, motivo = nucleo.leer("x = 1\x00y = 2\n", "tests/test_x.py")
        self.assertEqual(obtenidos, [])
        self.assertTrue(motivo)


def _comparar(metodos_a, metodos_b, base=()):
    return nucleo.comparar(
        {"t.py": list(base)},
        {"a": {"t.py": list(metodos_a)}, "b": {"t.py": list(metodos_b)}},
    )


class TestPredicado(unittest.TestCase):
    def test_mismo_nombre_en_la_misma_clase_es_rojo(self):
        r = _comparar(
            [nucleo.Metodo("t.py", "C", "test_01", 1)],
            [nucleo.Metodo("t.py", "C", "test_01", 1)],
        )
        self.assertEqual(len(r.rojos), 1)
        self.assertIn("mismo nombre", r.rojos[0].motivo)

    def test_mismo_ordinal_distinto_nombre_en_la_misma_clase_es_rojo(self):
        r = _comparar(
            [nucleo.Metodo("t.py", "C", "test_35_alpha", 1)],
            [nucleo.Metodo("t.py", "C", "test_35_beta", 1)],
        )
        self.assertEqual(len(r.rojos), 1)
        self.assertIn("ordinal 35", r.rojos[0].motivo)
        self.assertEqual(r.rc, 1)

    def test_mismo_ordinal_en_clases_distintas_es_aviso(self):
        r = _comparar(
            [nucleo.Metodo("t.py", "A", "test_36_uno", 1)],
            [nucleo.Metodo("t.py", "B", "test_36_dos", 1)],
        )
        self.assertEqual(r.rojos, [])
        self.assertEqual(len(r.avisos), 1)
        self.assertEqual(r.rc, 0)

    def test_ordinal_heredado_no_es_rojo_pero_si_ruido(self):
        base = [nucleo.Metodo("t.py", "C", "test_05_viejo", 1)]
        r = _comparar(
            base,
            [*base, nucleo.Metodo("t.py", "C", "test_05_nuevo", 9)],
            base=base,
        )
        self.assertEqual(r.rojos, [])
        self.assertEqual(r.ingenuo, 1)

    def test_sin_ordinal_no_colisiona(self):
        r = _comparar(
            [nucleo.Metodo("t.py", "C", "test_alpha", 1)],
            [nucleo.Metodo("t.py", "C", "test_beta", 1)],
        )
        self.assertEqual(r.rojos, [])
        self.assertEqual(r.ingenuo, 0)

    def test_duplicado_dentro_de_una_rama_es_rojo(self):
        doble = nucleo.Metodo("t.py", "C", "test_07", 1)
        r = nucleo.comparar({}, {"a": {"t.py": [doble, nucleo.Metodo("t.py", "C", "test_07", 8)]}})
        self.assertEqual(len(r.rojos), 1)
        self.assertIn("duplicado dentro de a", r.rojos[0].motivo)

    def test_dos_nombres_distintos_con_el_mismo_ordinal_en_una_rama_es_rojo(self):
        # El mismo defecto del caso 20 -> 1, pero sin rama: un solo archivo con
        # test_07_alpha y test_07_beta en la misma clase. El chequeo por nombre
        # exacto no lo veía porque los nombres difieren.
        r = nucleo.comparar(
            {},
            {
                "a": {
                    "t.py": [
                        nucleo.Metodo("t.py", "C", "test_07_alpha", 1),
                        nucleo.Metodo("t.py", "C", "test_07_beta", 8),
                    ]
                }
            },
        )
        self.assertEqual(len(r.rojos), 1)
        self.assertIn("duplicado dentro de a", r.rojos[0].motivo)


class TestCanario(unittest.TestCase):
    def test_reproduce_veinte_a_uno(self):
        r = _canario()
        self.assertEqual(r.ingenuo, 20)
        self.assertEqual(len(r.rojos), 1)
        self.assertEqual(r.rojos[0].a.nombre, "test_35_alpha")
        self.assertEqual(r.rojos[0].b.nombre, "test_35_beta")


class TestBasePorPareja(unittest.TestCase):
    """La base de una pareja no es la base del mundo.

    Lo que dos ramas comparten porque nació después de la base global es
    herencia, no duplicado. Medido sobre el corpus: con una base única, cuatro
    ramas del mismo tronco producían 76 rojos falsos; con la base de cada
    pareja, 1 rojo verdadero.
    """

    def setUp(self):
        self.comun = nucleo.Metodo("t.py", "C", "test_40_nacio_despues_de_la_base", 1)
        self.ramas = {
            "a": {"t.py": [self.comun, nucleo.Metodo("t.py", "C", "test_41_de_a", 9)]},
            "b": {"t.py": [self.comun, nucleo.Metodo("t.py", "C", "test_42_de_b", 9)]},
        }

    def test_base_global_unica_produce_un_falso_rojo(self):
        r = nucleo.comparar({}, self.ramas)
        self.assertEqual(len(r.rojos), 1)

    def test_base_de_la_pareja_lo_desactiva(self):
        r = nucleo.comparar({}, self.ramas, bases_de_par={("a", "b"): {"t.py": [self.comun]}})
        self.assertEqual(r.rojos, [])


if __name__ == "__main__":
    unittest.main()
