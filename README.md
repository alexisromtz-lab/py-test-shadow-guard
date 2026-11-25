# py-test-shadow-guard

[![ci](https://github.com/alexisromtz-lab/py-test-shadow-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/alexisromtz-lab/py-test-shadow-guard/actions/workflows/ci.yml) ![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue) ![deps](https://img.shields.io/badge/dependencies-0-brightgreen) ![license](https://img.shields.io/badge/license-MIT-blue)

Un merge de Git puede ser limpio y aun así borrar un test.

Cuando dos ramas agregan métodos a la **misma clase** de test y ambos empiezan por
el mismo ordinal (`test_35_…`), Git ve hunks separados y hace el merge sin
conflicto. Python no dice nada: el segundo `def` sobrescribe al primero en el
diccionario de la clase. El primero **desaparece de la suite** y el CI queda verde
con un test menos. No hay error de sintaxis, ni conflicto, ni aviso de pytest.

Este detector compara dos o más refs contra su base y lo dice antes del merge.

## Instalación

Sin dependencias. Python ≥ 3.11.

```console
$ pip install git+https://github.com/alexisromtz-lab/py-test-shadow-guard@v0.2.1
# o, sin instalar nada:
$ uvx --from git+https://github.com/alexisromtz-lab/py-test-shadow-guard@v0.2.1 \
    py-test-shadow-guard --base origin/main --ref origin/rama-a --ref origin/rama-b
```

No hay wheel en PyPI todavía: `pip install py-test-shadow-guard` por nombre corto
**no resuelve**. La instalación reproducible es la URL de repositorio con su tag.

### Como hook de `pre-commit`

```yaml
repos:
  - repo: https://github.com/alexisromtz-lab/py-test-shadow-guard
    rev: v0.2.1
    hooks:
      - id: py-test-shadow-guard
        args: ["--base", "origin/main", "--ref", "HEAD", "--ref", "origin/rama-b"]
```

```console
$ pre-commit run py-test-shadow-guard --hook-stage manual
```

El hook es `manual` a propósito: necesita refs ya traídas y **dos** ramas, así que no
puede colgar de `git commit` sin inventarse el segundo ref. Ponlo donde ya tengas la
cola de PRs a la vista (el job de CI, el pre-push, o a mano antes de mergear).

## Uso

```console
$ py-test-shadow-guard --base <ref-base> --ref <ref> [--ref <ref> ...] [--repo <dir>] [--json]
```

`--base` es la base **global** (normalmente `origin/main`). El programa calcula
además el `git merge-base` real de cada pareja de ramas.

| RC | significado |
|---|---|
| 0 | sin colisiones (puede haber avisos) |
| 1 | hay al menos una colisión: no mergear así |
| 2 | ref o ruta inválida, o directorio que no es un repositorio git |

Salida:

- **ROJO** — misma clase y mismo nombre **con cuerpo distinto**, o misma clase y
  mismo ordinal con distinto nombre. Python sobrescribe en silencio: es pérdida
  de cobertura.
- **IDENTICO** — misma clase, mismo nombre y mismo cuerpo a los dos lados. El
  merge deja el método repetido y las dos copias son la misma función: **no se
  pierde ningún test**. No es un rojo y tampoco se calla: se cuenta aparte. La
  huella es el `ast.dump` del cuerpo sin números de línea, así que el mismo test
  insertado en offsets distintos —el caso real entre dos agentes— coincide.
- **AVISO** — mismo ordinal en clases distintas. No rompe la ejecución; degrada la
  trazabilidad si alguien busca `test_37` en el log y hay dos.
- **`--json`** — el mismo contenido, para consumirlo desde un pipeline.

Autodiagnóstico del propio instrumento (reproduce el caso canario 20 → 1):

```console
$ python -m py_test_shadow_guard --self-test
```

## Evidencia medida

Sobre un corpus real de 209 713 líneas de producto, entre dos ramas de trabajo
abiertas que agregan tests a la misma clase
(`tests/test_ratio_arnes_producto.py::ElPredicadoMuerde`):

```console
$ py-test-shadow-guard --base aebe3b8b --ref 669da106 --ref 55058449
ROJO  …::ElPredicadoMuerde.test_35_un_censo_todo_de_simulacion_no_tiene_techo_vivo
  vs  …::ElPredicadoMuerde.test_35_una_deuda_declarada_que_se_queda_corta_da_rojo
  (ordinal 35 en la misma clase, ambos nuevos)

ROJO: 1 colision(es) intra-clase · 0 ordinal(es) global(es) · nuevos medidos
669da106: 27 · 55058449: 6 · predicado ingenuo habria disparado 3
       · duplicados con cuerpo identico 0 (no son perdida)
```

Un detector ingenuo —«mismo ordinal entre dos refs»— habría disparado **3** veces
sobre esa pareja: un tercio de ruido. El caso canario del `--self-test` reproduce la
forma **20 → 1** en un fixture construido ad hoc; el **3 → 1** es la cifra medida
sobre el corpus. No son el mismo número porque no son el mismo sujeto, y cualquier
cita debe decir cuál produjo cuál.

## La lección que costó un falso rojo

La primera versión usaba una sola base global para todas las parejas. Con cuatro
ramas del mismo tronco devolvió **76 rojos**. No eran colisiones: las ramas
comparten tests nacidos **después** de la base global, así que con una base única
parecen «nuevos de los dos lados» y se marcan como duplicados.

> La base de una pareja no es la base del mundo.

Con el `git merge-base` de cada pareja: **76 → 1** rojo, y el rojo que queda es
verdadero. Hay dos tests que cubren exactamente esa diferencia, en
`tests/test_nucleo.py::TestBasePorPareja`.

## La lección que costó 75 falsos rojos

La primera versión comparaba `(archivo, clase, ordinal, nombre)` y nunca el
cuerpo. Sobre 15 PRs reales abiertos contra un tronco (105 parejas) marcó **2
parejas en colisión simbólica**, con 75 hallazgos por nombre compartido.

Los 75 eran el caso trivial: **el mismo `def`, con el mismo cuerpo, a los dos
lados**. `git merge` deja el método repetido y las dos copias son la misma
función; Python ejecuta una y no se pierde nada. Falsos positivos: 75 de 75.

> Un predicado que compara nombres no mide pérdida: mide coincidencia.

Con la huella del cuerpo (`ast.dump` sin números de línea) en el predicado:
**75 → 0**. El canal `IDENTICO` publica la cuenta para que el cero sea legible
como *mirado y no hay*, y el corpus fija las dos direcciones del error —cuerpo
igual ⇒ `IDENTICO`, cuerpo distinto ⇒ `ROJO`— para que el arreglo no se pueda
deshacer sin romper un test.

## En CI

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pip install py-test-shadow-guard
- run: py-test-shadow-guard --self-test
- run: py-test-shadow-guard --base origin/main --ref origin/rama-a --ref origin/rama-b
```

Sobre un PR aislado el caso casi no aparece: una rama no colisiona consigo misma.
El instrumento sirve para **composición** — varias ramas en vuelo, o un agente de IA
abriendo PRs en paralelo contra el mismo archivo de tests — y por eso el paso que
importa lleva **dos `--ref`**.

Se puede correr también como pre-commit local sobre las ramas que tengas abiertas:

```console
$ .git/hooks/pre-commit   # o el runner que uses
$ py-test-shadow-guard --base origin/main $(git for-each-ref --format='--ref %(refname:short)' refs/heads/worker/)
```

## Límites declarados

- Solo archivos `test_*.py` / `*_test.py`.
- Compara cuerpos sólo donde el cuerpo es la pregunta: mismo nombre y mismo
  cuerpo es `IDENTICO`, mismo nombre y cuerpo distinto es `ROJO`. Dos ordinales
  iguales con nombres distintos siguen siendo rojo aunque uno sea un `skip`: ahí
  lo que choca es el ordinal, no el cuerpo.
- No detecta shadowing entre módulos distintos ni entre archivos que se importen con
  el mismo nombre (`conftest` no testeado).
- No sustituye a `pytest --collect-only -q`: lo complementa antes del merge, cuando
  todavía se puede renombrar el que llega último.
- Un archivo que no compila sale como `NO_MEDIDO` con su motivo, nunca como «cero
  tests». Un byte nulo no lo acepta el parser: medido el 25-Nov-2026, 3.9.6 lo da
  como `ValueError` y 3.11.18, 3.12.16, 3.13.18 y 3.14.8 como `SyntaxError`. Se atrapan
  las dos —y por eso la primera versión podía reventar en el suelo declarado— aunque
  dentro de `>=3.11`, que es lo que declara el paquete, sólo se midió la segunda.
- La colisión **dentro** de una sola rama usa el mismo predicado que la de entre
  ramas (ordinal compartido en la misma clase). Antes agrupaba por nombre exacto: dos
  predicados para un solo fenómeno, y `test_07_a` / `test_07_b` en el mismo archivo
  pasaban limpios.

## Conformidad medida

El predicado de colisión de este paquete se mide contra
[`composicion-core`](https://github.com/alexisromtz-lab/composicion-core), que publica el
corpus de conformidad como datos y puntúa a cada herramienta contra él:

```bash
composicion-core --sonda shadow-guard --ruta .
```

Marcador del 26-Nov-2026: **10 rojo · 10 aviso · 10 no_medido · 0 discrepancias · 0 no comparables**. `composicion-core` no es una dependencia
—estos paquetes siguen sin dependencias para poder correr con `uvx`— sino un juez
externo: si los dos divergen, el que se equivoca se ve.

## Licencia

MIT.

## La familia

Tres paquetes con cero dependencias, probados en 3.11, 3.12 y 3.13:

| paquete | qué contesta |
|---|---|
| [composicion-core](https://github.com/alexisromtz-lab/composicion-core) | ¿dos ramas declaran el mismo test? predicado + corpus + juez de paridad |
| [py-test-shadow-guard](https://github.com/alexisromtz-lab/py-test-shadow-guard) | el test que el merge borra en silencio, en tu CI |
| [merge-lattice-governor](https://github.com/alexisromtz-lab/merge-lattice-governor) | en qué orden aterrizar N ramas sin romper el trinquete |
