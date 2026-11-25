"""CLI: `py-test-shadow-guard --base REF --ref REF [--ref REF ...]`."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

from . import nucleo

VERSION = "0.1.0"
_ES_TEST = re.compile(r"(^test_.*|.*_test)\.py$")


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=False
    )


def _es_commit(repo: str, ref: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def _rutas(repo: str, base: str, ref: str) -> list[str]:
    salida = _git(repo, "diff", "--name-only", f"{base}...{ref}")
    return [
        ruta
        for ruta in salida.stdout.splitlines()
        if ruta and _ES_TEST.search(ruta.rsplit("/", 1)[-1])
    ]


def _leer(repo: str, ref: str, ruta: str) -> str | None:
    salida = _git(repo, "show", f"{ref}:{ruta}")
    return salida.stdout if salida.returncode == 0 else None


def _canario() -> nucleo.Resultado:
    """Reproduce el 20 -> 1: 19 avisos ingenuos heredados y 1 colisión real."""
    base = [
        nucleo.Metodo("tests/test_x.py", "Caso", f"test_{i:02d}_heredado", 1)
        for i in range(1, 20)
    ]
    nueva_a = [nucleo.Metodo("tests/test_x.py", "Caso", "test_35_alpha", 99)]
    nueva_b = [
        *(nucleo.Metodo("tests/test_x.py", "Caso", f"test_{i:02d}_b", 1) for i in range(1, 20)),
        nucleo.Metodo("tests/test_x.py", "Caso", "test_35_beta", 99),
    ]
    return nucleo.comparar(
        {"tests/test_x.py": base},
        {
            "rama_a": {"tests/test_x.py": base + nueva_a},
            "rama_b": {"tests/test_x.py": base + nueva_b},
        },
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="py-test-shadow-guard",
        description="Detecta métodos de test que se sobrescriben en silencio tras un merge limpio.",
    )
    p.add_argument("--base", help="referencia base común (rama o commit)")
    p.add_argument("--ref", action="append", default=[], help="rama a componer; repetible")
    p.add_argument("--repo", default=".", help="ruta del repositorio git (por defecto .)")
    p.add_argument("--json", action="store_true", help="salida legible por máquina")
    p.add_argument("--self-test", action="store_true", help="canario interno 20 -> 1")
    p.add_argument("--version", action="version", version=f"py-test-shadow-guard {VERSION}")
    args = p.parse_args(argv)

    if args.self_test:
        r = _canario()
        ok = len(r.rojos) == 1 and r.ingenuo == 20
        print(f"CANARIO {'OK' if ok else 'ROTO'}: ingenuo {r.ingenuo} -> discrimado {len(r.rojos)}")
        for h in r.rojos:
            print("  " + h.linea())
        return 0 if ok else 1

    if not args.base or not args.ref:
        p.error("se requiere --base y al menos un --ref")

    for ref in [args.base, *args.ref]:
        if not _es_commit(args.repo, ref):
            print(f"REF INVALIDA: {ref} no resuelve a un commit en {args.repo}", file=sys.stderr)
            return 2
    if len(set(args.ref)) != len(args.ref):
        print("REF REPETIDA: cada --ref debe ser distinta", file=sys.stderr)
        return 2

    rutas: list[str] = []
    for ref in args.ref:
        for ruta in _rutas(args.repo, args.base, ref):
            if ruta not in rutas:
                rutas.append(ruta)
    if not rutas:
        if args.json:
            print(json.dumps({"schema": 1, "rc": 0, "rojos": [], "avisos": [], "rutas": []}))
        else:
            print(f"SIN SUJETO: ninguna rama toca un archivo de test entre {args.base} y las refs.")
        return 0

    base = {}
    for ruta in rutas:
        fuente = _leer(args.repo, args.base, ruta)
        base[ruta] = nucleo.metodos(fuente, ruta) if fuente else []

    ramas: dict[str, dict[str, list[nucleo.Metodo]]] = {}
    for ref in args.ref:
        archivos = {}
        for ruta in rutas:
            fuente = _leer(args.repo, ref, ruta)
            if fuente is None:
                fuente = _leer(args.repo, args.base, ruta) or ""
            archivos[ruta] = nucleo.metodos(fuente, ruta)
        ramas[ref] = archivos

    bases_de_par: dict[tuple[str, str], dict[str, list[nucleo.Metodo]]] = {}
    refs = list(args.ref)
    for i, ref_a in enumerate(refs):
        for ref_b in refs[i + 1:]:
            fusion = _git(args.repo, "merge-base", ref_a, ref_b)
            if fusion.returncode != 0 or not fusion.stdout.strip():
                continue
            comun = fusion.stdout.strip()
            archivos = {}
            for ruta in rutas:
                fuente = _leer(args.repo, comun, ruta)
                archivos[ruta] = nucleo.metodos(fuente, ruta) if fuente else []
            bases_de_par[(ref_a, ref_b)] = archivos

    r = nucleo.comparar(base, ramas, bases_de_par=bases_de_par)

    if args.json:
        print(
            json.dumps(
                {
                    "schema": 1,
                    "rc": r.rc,
                    "base": args.base,
                    "refs": args.ref,
                    "rutas": rutas,
                    "nuevos": r.nuevos,
                    "ingenuo": r.ingenuo,
                    "rojos": [
                        {"clase": h.clase, "a": h.a.rotulo(), "b": h.b.rotulo(), "motivo": h.motivo}
                        for h in r.rojos
                    ],
                    "avisos": [
                        {"clase": h.clase, "a": h.a.rotulo(), "b": h.b.rotulo(), "motivo": h.motivo}
                        for h in r.avisos
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return r.rc

    for h in r.rojos:
        print(h.linea())
    for h in r.avisos:
        print(h.linea())
    nuevos = " · ".join(f"{ref}: {n}" for ref, n in r.nuevos.items())
    print(
        f"\n{r.rc and 'ROJO' or 'VERDE'}: {len(r.rojos)} colision(es) intra-clase · "
        f"{len(r.avisos)} ordinal(es) global(es) · nuevos medidos {nuevos}"
        f" · predicado ingenuo habria disparado {r.ingenuo}"
    )
    return r.rc


if __name__ == "__main__":
    raise SystemExit(main())
