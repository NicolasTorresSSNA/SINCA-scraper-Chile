"""Interfaz de línea de comandos: python -m sinca <comando>."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .catalogo import ALIAS_PARAMETROS, REGIONES, RESOLUCIONES, cargar_estaciones, seleccionar_series
from .descarga import (Tarea, crear_driver, descargar_serie, escribir_estaciones_csv,
                       escribir_resumen, ruta_existente)

DEFAULTS = {
    "region": ["M"],
    "comuna": [],
    "estacion": [],
    "parametros": ["mp25", "humedad", "temperatura", "viento"],
    "resolucion": "horario",
    "salida": "descargas_sinca",
    "timeout": 90,
}


def fmt_tiempo(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def resolver_regiones(valores: list[str]) -> list[str]:
    if any(v.upper() == "TODAS" for v in valores):
        return list(REGIONES)
    codigos = [v.upper() for v in valores]
    invalidos = [c for c in codigos if c not in REGIONES]
    if invalidos:
        sys.exit(f"Región desconocida: {', '.join(invalidos)}. Usa `python -m sinca regiones` para ver los códigos.")
    return codigos


def resolver_parametros(tokens: list[str], resolucion_defecto: str) -> dict[str, str]:
    """['mp25', 'mp10:diario'] -> {'mp25': 'horario', 'mp10': 'diario'}"""
    resultado = {}
    for t in tokens:
        nombre, _, res = t.partition(":")
        res = (res or resolucion_defecto).lower()
        if res not in RESOLUCIONES:
            sys.exit(f"Resolución inválida en '{t}'. Opciones: {', '.join(RESOLUCIONES)}")
        resultado[nombre] = res
    return resultado


def cargar_opciones(args) -> dict:
    """Prioridad: argumentos CLI > archivo --config > valores por defecto."""
    opciones = dict(DEFAULTS)
    if args.config:
        ruta = Path(args.config)
        if not ruta.exists():
            sys.exit(f"No existe el archivo de configuración: {ruta}")
        opciones.update(json.loads(ruta.read_text(encoding="utf-8")))
    for clave in DEFAULTS:
        valor = getattr(args, clave, None)
        if valor not in (None, []):
            opciones[clave] = valor
    if isinstance(opciones["parametros"], dict):  # config.json puede usar {"mp25": "horario", ...}
        opciones["parametros"] = [f"{k}:{v}" for k, v in opciones["parametros"].items()]
    return opciones


# --------------------------------------------------------------------------- comandos

def cmd_regiones(_args):
    for codigo, nombre in REGIONES.items():
        print(f"  {codigo:<4} {nombre}")


def cmd_parametros(_args):
    print("Atajos disponibles (puedes usar también cualquier parte del nombre, ej. 'ozono'):\n")
    for alias in ALIAS_PARAMETROS:
        print(f"  {alias}")
    print("\nAgrega la resolución con ':' -> mp10:diario   (horario | diario | mensual)")


def cmd_estaciones(args):
    op = cargar_opciones(args)
    estaciones = cargar_estaciones(resolver_regiones(op["region"]), op["comuna"], op["estacion"])
    destino = Path(args.salida_csv)
    escribir_estaciones_csv(estaciones, destino)
    print(f"\n{len(estaciones)} estaciones guardadas en {destino}")


def cmd_descargar(args):
    op = cargar_opciones(args)
    parametros = resolver_parametros(op["parametros"], op["resolucion"])
    estaciones = cargar_estaciones(resolver_regiones(op["region"]), op["comuna"], op["estacion"])
    if not estaciones:
        sys.exit("Ningún filtro coincidió con estaciones. Revisa --region / --comuna / --estacion.")
    ejecutar_descarga(estaciones, parametros, Path(op["salida"]).resolve(), op["timeout"],
                      args.sobrescribir, args.dry_run, args.ver_navegador)


def planificar(estaciones, parametros, salida, sobrescribir) -> tuple[list[Tarea], list[Tarea]]:
    """Devuelve (todas las tareas, las pendientes) e imprime las series omitidas."""
    tareas: list[Tarea] = []
    for e in estaciones:
        series, avisos = seleccionar_series(e, parametros)
        tareas += [Tarea(e, s) for s in series]
        for aviso in avisos:
            print(f"  [omitido] {e.nombre} ({e.comuna}): {aviso}")
    pendientes = [t for t in tareas if sobrescribir or not ruta_existente(t, salida)]
    print(f"\nPlan: {len(estaciones)} estaciones, {len(tareas)} series "
          f"({len(tareas) - len(pendientes)} ya descargadas) -> {len(pendientes)} por descargar")
    print(f"Destino: {salida}")
    return tareas, pendientes


def ejecutar_descarga(estaciones, parametros, salida, timeout, sobrescribir=False,
                      dry_run=False, ver_navegador=False, confirmar=None):
    """Planifica y descarga. `confirmar` (opcional) es un callable que puede abortar tras mostrar el plan."""
    print()
    tareas, pendientes = planificar(estaciones, parametros, salida, sobrescribir)
    if dry_run:
        for t in pendientes:
            print(f"  - {t.etiqueta}")
        return
    if not pendientes or (confirmar and not confirmar()):
        return

    salida.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix="sinca_"))
    resultados = [(t, "existente", "") for t in tareas if t not in pendientes]
    inicio = time.time()
    driver = crear_driver(temporal, headless=not ver_navegador)
    try:
        for i, t in enumerate(pendientes, start=1):
            transcurrido = time.time() - inicio
            eta = fmt_tiempo(transcurrido / (i - 1) * (len(pendientes) - i + 1)) if i > 1 else "--:--"
            print(f"[{fmt_tiempo(transcurrido)}] ({i}/{len(pendientes)}) ETA {eta} | {t.etiqueta}")
            try:
                ruta = descargar_serie(driver, t, salida, temporal, timeout)
                resultados.append((t, "ok", ruta.name))
            except Exception as ex:  # una serie fallida no debe detener el resto
                print(f"    -> ERROR: {type(ex).__name__}: {ex}")
                resultados.append((t, "error", f"{type(ex).__name__}: {ex}"))
    except KeyboardInterrupt:
        print("\nInterrumpido. Vuelve a ejecutar el mismo comando para continuar donde quedó.")
    finally:
        driver.quit()
        escribir_resumen(resultados, salida / "_resumen.csv")

    ok = sum(1 for _, estado, _ in resultados if estado == "ok")
    err = sum(1 for _, estado, _ in resultados if estado == "error")
    print(f"\nListo en {fmt_tiempo(time.time() - inicio)}: {ok} descargadas, {err} con error. "
          f"Detalle en {salida / '_resumen.csv'}")


def cmd_interactivo(_args):
    from .interactivo import asistente
    asistente()


# --------------------------------------------------------------------------- parser

def _agregar_filtros(p):
    p.add_argument("--config", help="Archivo JSON con opciones (los argumentos de consola tienen prioridad)")
    p.add_argument("-r", "--region", nargs="+", metavar="COD",
                   help="Códigos de región o TODAS (ver `regiones`). Defecto: M")
    p.add_argument("-c", "--comuna", nargs="+", metavar="NOMBRE", help="Filtrar por comuna (acepta nombres parciales)")
    p.add_argument("-e", "--estacion", nargs="+", metavar="ID", help="Filtrar por ID de estación")


def construir_parser():
    p = argparse.ArgumentParser(
        prog="python -m sinca",
        description="Descarga series de calidad del aire y meteorología desde SINCA (Chile).",
        epilog="Ejemplo: python -m sinca descargar -r M -c 'El Bosque' -p mp25 humedad temperatura --dry-run",
    )
    p.add_argument("--version", action="version", version=f"sinca-scraper {__version__}")
    sub = p.add_subparsers(dest="comando", metavar="comando")

    sub.add_parser("interactivo", help="Asistente paso a paso (también se abre al ejecutar sin comando)").set_defaults(func=cmd_interactivo)
    sub.add_parser("regiones", help="Lista los códigos de región").set_defaults(func=cmd_regiones)
    sub.add_parser("parametros", help="Lista los atajos de parámetros").set_defaults(func=cmd_parametros)

    e = sub.add_parser("estaciones", help="Exporta el catálogo de estaciones (con lat/lon) a CSV")
    _agregar_filtros(e)
    e.add_argument("-o", "--salida-csv", default="estaciones_sinca.csv", help="Archivo CSV de salida")
    e.set_defaults(func=cmd_estaciones)

    d = sub.add_parser("descargar", help="Descarga las series de las estaciones seleccionadas")
    _agregar_filtros(d)
    d.add_argument("-p", "--parametros", nargs="+", metavar="PARAM",
                   help="Ej: mp25 humedad mp10:diario  (ver `parametros`). Defecto: mp25 humedad temperatura viento")
    d.add_argument("--resolucion", choices=RESOLUCIONES, help="Resolución por defecto. Defecto: horario")
    d.add_argument("-o", "--salida", help="Carpeta de salida. Defecto: descargas_sinca")
    d.add_argument("--timeout", type=int, help="Segundos máximos de espera por archivo. Defecto: 90")
    d.add_argument("--dry-run", action="store_true", help="Muestra qué se descargaría, sin abrir el navegador")
    d.add_argument("--sobrescribir", action="store_true", help="Vuelve a descargar archivos que ya existen")
    d.add_argument("--ver-navegador", action="store_true", help="Muestra la ventana de Chrome (depuración)")
    d.set_defaults(func=cmd_descargar)
    return p


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):  # sin comando: asistente si hay una persona al teclado
        if sys.stdin.isatty():
            return cmd_interactivo(args)
        parser.print_help()
        return
    args.func(args)
