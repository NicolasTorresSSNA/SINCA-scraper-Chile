"""Asistente interactivo: guía paso a paso y muestra el comando equivalente al final."""
from pathlib import Path

from .catalogo import ALIAS_PARAMETROS, REGIONES, RESOLUCIONES, cargar_estaciones, normalizar
from .cli import DEFAULTS, ejecutar_descarga

# (atajo, descripción) en el orden en que se muestran
MENU_PARAMETROS = [
    ("mp25", "Material particulado MP2.5"),
    ("mp10", "Material particulado MP10"),
    ("o3", "Ozono"),
    ("so2", "Dióxido de azufre"),
    ("co", "Monóxido de carbono"),
    ("no2", "Dióxido de nitrógeno"),
    ("humedad", "Humedad relativa"),
    ("temperatura", "Temperatura ambiente"),
    ("viento", "Viento (dirección y velocidad)"),
]


class Cancelado(Exception):
    pass


def preguntar(texto: str, defecto: str = "") -> str:
    sufijo = f" [{defecto}]" if defecto else ""
    try:
        respuesta = input(f"{texto}{sufijo}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Cancelado from None
    if respuesta.lower() in ("q", "salir"):
        raise Cancelado
    return respuesta or defecto


def elegir(texto: str, opciones: list[str], multiple=True, vacio_es_todas=False) -> list[int]:
    """Muestra opciones numeradas y devuelve los índices elegidos (acepta '1 3', '1,3' o '2-4')."""
    for i, o in enumerate(opciones, start=1):
        print(f"  {i:>3}. {o}")
    while True:
        r = preguntar(texto).replace(",", " ")
        if not r:
            if vacio_es_todas:
                return list(range(len(opciones)))
            print("  Elige al menos una opción.")
            continue
        try:
            indices: list[int] = []
            for tramo in r.split():
                a, _, b = tramo.partition("-")
                indices += range(int(a), int(b or a) + 1)
            if all(1 <= i <= len(opciones) for i in indices) and (multiple or len(indices) == 1):
                return sorted({i - 1 for i in indices})
        except ValueError:
            pass
        print(f"  No entendí '{r}'. Escribe números entre 1 y {len(opciones)}, ej: 1 3 o 2-4.")


def _citar(texto: str) -> str:
    """Comillas dobles: funcionan igual en cmd, PowerShell y bash."""
    return f'"{texto}"' if " " in texto else texto


def comando_equivalente(regiones, comunas, ids, parametros, resolucion, salida) -> str:
    partes = ["python -m sinca descargar", "-r " + " ".join(regiones)]
    if ids:
        partes.append("-e " + " ".join(ids))
    elif comunas:
        partes.append("-c " + " ".join(_citar(c) for c in comunas))
    partes.append("-p " + " ".join(parametros))
    if resolucion != DEFAULTS["resolucion"]:
        partes.append(f"--resolucion {resolucion}")
    if salida != DEFAULTS["salida"]:
        partes.append("-o " + _citar(salida))
    return " ".join(partes)


def asistente():
    print("=" * 60)
    print(" SINCA Scraper - asistente interactivo")
    print(" (escribe 'q' en cualquier momento para salir)")
    print("=" * 60)
    try:
        _flujo()
    except Cancelado:
        print("\nCancelado. No se descargó nada más.")


def _flujo():
    # 1. Regiones
    print("\n1) ¿De qué región(es)? (Enter = todo el país)")
    codigos = list(REGIONES)
    idx = elegir("Región(es)", [f"{c:<4} {n}" for c, n in REGIONES.items()], vacio_es_todas=True)
    regiones = [codigos[i] for i in idx]
    es_todas = len(regiones) == len(codigos)

    print("\nBuscando estaciones...")
    estaciones = cargar_estaciones(regiones)
    if not estaciones:
        print("No se encontraron estaciones.")
        return

    # 2. Comunas
    comunas = sorted({e.comuna for e in estaciones if e.comuna})
    conteo = {c: sum(1 for e in estaciones if e.comuna == c) for c in comunas}
    print(f"\n2) ¿Qué comuna(s)? Hay {len(estaciones)} estaciones en {len(comunas)} comunas. (Enter = todas)")
    idx = elegir("Comuna(s)", [f"{c} ({conteo[c]})" for c in comunas], vacio_es_todas=True)
    comunas_sel = [comunas[i] for i in idx]
    estaciones = [e for e in estaciones if e.comuna in comunas_sel]

    # 3. Estaciones (solo vale la pena preguntar si hay varias)
    ids: list[str] = []
    if len(estaciones) > 1:
        print(f"\n3) Hay {len(estaciones)} estaciones. ¿Quieres todas? (Enter = todas)")
        idx = elegir("Estación(es)", [f"{e.nombre} - {e.comuna} (id {e.id})" for e in estaciones],
                     vacio_es_todas=True)
        if len(idx) < len(estaciones):
            estaciones = [estaciones[i] for i in idx]
            ids = [e.id for e in estaciones]

    # 4. Parámetros (solo los que existen en las estaciones elegidas)
    def disponibles(alias):
        frag = ALIAS_PARAMETROS[alias]
        return sum(1 for e in estaciones if any(frag in normalizar(s.parametro + s.detalle) for s in e.series))

    menu = [(a, d, disponibles(a)) for a, d in MENU_PARAMETROS]
    menu = [m for m in menu if m[2]]
    if not menu:
        print("\nLas estaciones elegidas no miden ninguno de los parámetros más comunes.")
        return
    print("\n4) ¿Qué parámetros? (los números pueden combinarse: 1 3 4)")
    idx = elegir("Parámetro(s)", [f"{d} - en {n} de {len(estaciones)} estaciones" for _, d, n in menu])
    parametros = [menu[i][0] for i in idx]

    # 5. Resolución y carpeta
    print("\n5) Resolución de los datos")
    res_idx = elegir("Resolución", [f"{r}" + ("  (recomendada)" if r == "horario" else "") for r in RESOLUCIONES],
                     multiple=False)
    resolucion = RESOLUCIONES[res_idx[0]]
    salida = preguntar("\n   Carpeta donde guardar", DEFAULTS["salida"])

    # 6. Confirmar y ejecutar
    equivalente = comando_equivalente(regiones if not es_todas else ["TODAS"], comunas_sel if len(comunas_sel) < len(comunas) else [],
                                      ids, parametros, resolucion, salida)

    def confirmar() -> bool:
        return preguntar("\n¿Descargar ahora? (s/n)", "s").lower().startswith("s")

    ejecutar_descarga(estaciones, {p: resolucion for p in parametros}, Path(salida).resolve(),
                      DEFAULTS["timeout"], confirmar=confirmar)
    print(f"\nPara repetir esto sin el asistente:\n  {equivalente}")
