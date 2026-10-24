"""Descarga de series con Selenium (el botón de exportar del SINCA corre por JavaScript)."""
import csv
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .catalogo import Estacion, Serie


@dataclass
class Tarea:
    estacion: Estacion
    serie: Serie

    @property
    def etiqueta(self) -> str:
        altura = f" {self.serie.altura} m" if self.serie.altura else ""
        return f"{self.estacion.nombre} | {self.serie.parametro}{altura} [{self.serie.resolucion}]"

    def nombre_base(self) -> str:
        partes = [self.estacion.id, self.estacion.nombre.replace("Estación", "").strip(),
                  self.serie.parametro, self.serie.resolucion]
        if self.serie.altura:
            partes.append(f"{self.serie.altura}m")
        return "__".join(re.sub(r"\s+", "_", re.sub(r"[^\w\s,.-]", "", p)).strip("_") for p in partes)


def crear_driver(carpeta_temporal: Path, headless: bool) -> webdriver.Chrome:
    opciones = Options()
    if headless:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")
    opciones.add_experimental_option("prefs", {
        "download.default_directory": str(carpeta_temporal),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })
    return webdriver.Chrome(options=opciones)  # Selenium Manager baja el chromedriver solo


def _esperar_archivo(carpeta: Path, timeout: int) -> Path | None:
    limite = time.time() + timeout
    while time.time() < limite:
        archivos = [p for p in carpeta.iterdir() if p.is_file()]
        if archivos and not any(p.suffix in (".crdownload", ".tmp") for p in archivos):
            return archivos[0]
        time.sleep(0.5)
    return None


def descargar_serie(driver, tarea: Tarea, salida: Path, temporal: Path, timeout: int) -> Path:
    """Descarga una serie a `salida`. Lanza excepción si falla."""
    for p in temporal.iterdir():
        p.unlink()
    driver.get(tarea.serie.url)
    WebDriverWait(driver, 20).until(EC.frame_to_be_available_and_switch_to_it("right"))
    driver.execute_script("Open('xcl');")
    archivo = _esperar_archivo(temporal, timeout)
    if not archivo:
        raise TimeoutError(f"sin descarga tras {timeout}s")
    destino = salida / (tarea.nombre_base() + archivo.suffix)
    shutil.move(str(archivo), destino)
    return destino


def ruta_existente(tarea: Tarea, salida: Path) -> Path | None:
    return next(iter(salida.glob(tarea.nombre_base() + ".*")), None)


def escribir_estaciones_csv(estaciones: list[Estacion], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel abre bien las tildes
        w = csv.writer(f)
        w.writerow(["id", "estacion", "region_codigo", "region", "comuna", "latitud", "longitud",
                    "utm", "huso", "parametros", "url"])
        for e in estaciones:
            parametros = sorted({etiqueta_serie(s) for s in e.series})
            w.writerow([e.id, e.nombre, e.region_codigo, e.region, e.comuna, e.lat, e.lon,
                        e.utm, e.huso, "; ".join(parametros), e.url])


def etiqueta_serie(s: Serie) -> str:
    altura = f" {s.altura}m" if s.altura else ""
    return f"{s.parametro}{altura} [{s.resolucion}]"


def escribir_resumen(resultados: list[tuple[Tarea, str, str]], ruta: Path) -> None:
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "estacion", "comuna", "parametro", "resolucion", "altura_m", "estado", "detalle"])
        for t, estado, detalle in resultados:
            w.writerow([t.estacion.id, t.estacion.nombre, t.estacion.comuna, t.serie.parametro,
                        t.serie.resolucion, t.serie.altura or "", estado, detalle])
