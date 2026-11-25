"""Extracción AST de métodos de test y detección de shadowing entre ramas.

Medición de origen (corpus privado, 24-Nov-2026): el predicado ingenuo
`ordinal(m1) == ordinal(m2)` entre dos ramas disparó 20 veces y 19 eran tests
heredados del ancestro común. El predicado discriminado —misma clase, mismo
ordinal, nombre distinto y **ambos nuevos respecto de la base**— disparó 1 vez:
el defecto real, dos `def test_35_*` distintos en la misma clase que un merge de
git deja pasar como limpio y que Python resuelve borrando el primero.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

_ORDINAL = re.compile(r"^test_?(\d+)")


def ordinal(nombre: str) -> int | None:
    """Devuelve el prefijo numérico de `test_35_algo`, o None si no tiene."""
    encontrado = _ORDINAL.match(nombre)
    return int(encontrado.group(1)) if encontrado else None


@dataclass(frozen=True)
class Metodo:
    ruta: str
    clase: str | None
    nombre: str
    linea: int

    @property
    def ordinal(self) -> int | None:
        return ordinal(self.nombre)

    @property
    def clave(self) -> tuple[str, str | None]:
        return (self.ruta, self.clase)

    def rotulo(self) -> str:
        cual = f"{self.clase}.{self.nombre}" if self.clase else self.nombre
        return f"{self.ruta}::{cual}"


@dataclass(frozen=True)
class Hallazgo:
    clase: str  # "rojo" | "aviso"
    a: Metodo
    b: Metodo
    motivo: str

    def linea(self) -> str:
        etiqueta = "ROJO" if self.clase == "rojo" else "AVISO"
        return f"{etiqueta}  {self.a.rotulo()}  vs  {self.b.rotulo()}   ({self.motivo})"


@dataclass
class Resultado:
    rojos: list[Hallazgo]
    avisos: list[Hallazgo]
    nuevos: dict[str, int]
    ingenuo: int

    @property
    def rc(self) -> int:
        return 1 if self.rojos else 0


def metodos(fuente: str, ruta: str) -> list[Metodo]:
    """Métodos de test de un archivo. `unittest` usa el prefijo `test` a secas."""
    try:
        arbol = ast.parse(fuente, filename=ruta)
    except SyntaxError:
        return []
    salida: list[Metodo] = []

    def visita(nodos, clase: str | None) -> None:
        for nodo in nodos:
            if isinstance(nodo, ast.ClassDef):
                anidada = f"{clase}.{nodo.name}" if clase else nodo.name
                visita(nodo.body, anidada)
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if nodo.name.startswith("test"):
                    salida.append(Metodo(ruta, clase, nodo.name, nodo.lineno))

    visita(arbol.body, None)
    return salida


def _mismo_sujeto(a: Metodo, b: Metodo) -> bool:
    return a.clave == b.clave


def _compara_par(a: Metodo, b: Metodo, *, nuevos_de_base: bool) -> Hallazgo | None:
    if not _mismo_sujeto(a, b):
        mismo_ordinal = a.ordinal is not None and a.ordinal == b.ordinal
        if mismo_ordinal and a.nombre != b.nombre:
            return Hallazgo("aviso", a, b, f"ordinal {a.ordinal} repetido entre clases distintas")
        return None
    if a.nombre == b.nombre:
        return Hallazgo("rojo", a, b, "mismo nombre en la misma clase: el segundo borra al primero")
    if a.ordinal is not None and a.ordinal == b.ordinal:
        etiqueta = "ambos nuevos" if nuevos_de_base else "uno heredado"
        return Hallazgo("rojo", a, b, f"ordinal {a.ordinal} en la misma clase, {etiqueta}")
    return None


def _indice(archivos: dict[str, list[Metodo]]) -> set[tuple[str, str | None, str]]:
    return {(ruta, m.clase, m.nombre) for ruta, lista in archivos.items() for m in lista}


def comparar(
    base: dict[str, list[Metodo]],
    ramas: dict[str, dict[str, list[Metodo]]],
    bases_de_par: dict[tuple[str, str], dict[str, list[Metodo]]] | None = None,
) -> Resultado:
    """`base` y cada rama van indexados por ruta de archivo.

    `bases_de_par` es la base real de cada pareja (su `git merge-base`): lo que
    dos ramas comparten porque nació después de la base global no es un
    duplicado, es herencia. Sin ella el detector produce falsos rojos.
    """
    bases_de_par = bases_de_par or {}
    indice_base = _indice(base)
    nuevos: dict[str, list[Metodo]] = {}
    for ref, archivos in ramas.items():
        propios = _indice(archivos)
        nuevos[ref] = [
            m for ruta, lista in archivos.items() for m in lista if (ruta, m.clase, m.nombre) in propios - indice_base
        ]

    rojos: list[Hallazgo] = []
    avisos: list[Hallazgo] = []

    # Duplicado dentro de una misma rama: el archivo ya está roto antes del merge.
    for ref, lista in nuevos.items():
        vistos: dict[tuple[str, str | None, str], list[Metodo]] = {}
        for m in lista:
            vistos.setdefault((m.ruta, m.clase, m.nombre), []).append(m)
        for grupo in vistos.values():
            if len(grupo) > 1:
                rojos.append(Hallazgo("rojo", grupo[0], grupo[1], f"duplicado dentro de {ref}"))

    refs = list(ramas)
    for i, ref_a in enumerate(refs):
        for ref_b in refs[i + 1:]:
            base_par = bases_de_par.get((ref_a, ref_b)) or bases_de_par.get((ref_b, ref_a))
            indice_par = _indice(base_par) if base_par is not None else indice_base
            solo_a = [
                m
                for lista in ramas[ref_a].values()
                for m in lista
                if (m.ruta, m.clase, m.nombre) not in indice_par
            ]
            solo_b = [
                m
                for lista in ramas[ref_b].values()
                for m in lista
                if (m.ruta, m.clase, m.nombre) not in indice_par
            ]
            for a in solo_a:
                for b in solo_b:
                    h = _compara_par(a, b, nuevos_de_base=True)
                    if h is not None:
                        (rojos if h.clase == "rojo" else avisos).append(h)

    # Predicado ingenuo: mismo ordinal entre ramas, sin filtrar por base. Es el ruido.
    ingenuo = 0
    for i, ref_a in enumerate(refs):
        for ref_b in refs[i + 1:]:
            for ruta, lista_a in ramas[ref_a].items():
                lista_b = ramas[ref_b].get(ruta, [])
                for a in lista_a:
                    for b in lista_b:
                        if a.ordinal is not None and a.ordinal == b.ordinal and a.nombre != b.nombre:
                            ingenuo += 1
    rojos.sort(key=lambda h: (h.a.ruta, h.a.clase or "", h.a.ordinal or 0, h.a.nombre))
    avisos.sort(key=lambda h: (h.a.ruta, h.a.clase or "", h.a.ordinal or 0, h.a.nombre))
    return Resultado(rojos, avisos, {ref: len(lista) for ref, lista in nuevos.items()}, ingenuo)
