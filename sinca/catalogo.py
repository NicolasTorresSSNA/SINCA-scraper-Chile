"""Descubrimiento y lectura de estaciones SINCA (HTML estático, sin Selenium)."""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pyproj import Proj
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://sinca.mma.gob.cl"

REGIONES = {
    "XV": "Arica y Parinacota",
    "I": "Tarapacá",
    "II": "Antofagasta",
    "III": "Atacama",
    "IV": "Coquimbo",
    "V": "Valparaíso",
    "M": "Metropolitana",
    "VI": "O'Higgins",
    "VII": "Maule",
    "XVI": "Ñuble",
    "VIII": "Biobío",
    "IX": "Araucanía",
    "XIV": "Los Ríos",
    "X": "Los Lagos",
    "XI": "Aysén",
    "XII": "Magallanes",
}

# Atajos para los parámetros más usados -> fragmento (normalizado) del nombre real.
# Cualquier otro texto se busca tal cual como fragmento del nombre del parámetro.
ALIAS_PARAMETROS = {
    "mp25": "mp25",
    "mp10": "mp10",
    "o3": "ozono",
    "so2": "dioxidodeazufre",
    "co": "monoxidodecarbono",
    "no2": "dioxidodenitrogeno",
    "humedad": "humedad",
    "temperatura": "temperatura",
    "dir_viento": "direcciondelviento",
    "vel_viento": "velocidaddelviento",
    "viento": "viento",
}

RESOLUCIONES = ("horario", "diario", "mensual")


@dataclass
class Serie:
    parametro: str
    detalle: str  # texto entre paréntesis, ej. "MP 2,5 - μg/m3"
    resolucion: str
    altura: int | None  # metros; None = no aplica o S/I
    url: str


@dataclass
class Estacion:
    id: str
    nombre: str
    region_codigo: str
    region: str
    comuna: str
    utm: str
    huso: str
    lat: float | None
    lon: float | None
    url: str
    series: list[Serie] = field(default_factory=list)


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni símbolos: 'Material particulado MP 2,5' -> 'materialparticuladomp25'."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def nueva_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "sinca-scraper (investigacion; github.com/NicolasTorresSSNA)"
    reintentos = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    sesion.mount("https://", HTTPAdapter(max_retries=reintentos))
    return sesion


def _soup(resp: requests.Response) -> BeautifulSoup:
    return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")


def listar_urls_estaciones(sesion: requests.Session, codigos_region: list[str]) -> dict[str, str]:
    """Devuelve {url_estacion: codigo_region} para las regiones pedidas."""
    urls: dict[str, str] = {}
    for codigo in codigos_region:
        resp = sesion.get(f"{BASE_URL}/index.php/region/index/id/{codigo}", timeout=30)
        resp.raise_for_status()
        for a in _soup(resp).find_all("a", href=True):
            if "/estacion/index/" in a["href"]:
                urls.setdefault(urljoin(BASE_URL, a["href"]), codigo)
    return urls


def utm_a_latlon(utm: str, huso: str) -> tuple[float | None, float | None]:
    m = re.search(r"(\d+)\s*E\s*(\d+)\s*N", utm)
    if not m:
        return None, None
    zona = int(huso) if huso.isdigit() else 19
    lon, lat = Proj(proj="utm", zone=zona, ellps="WGS84", south=True)(
        float(m.group(1)), float(m.group(2)), inverse=True
    )
    return round(lat, 6), round(lon, 6)


def _fila(soup: BeautifulSoup, etiqueta: str) -> str:
    for th in soup.find_all("th"):
        if etiqueta in th.get_text():
            td = th.find_next_sibling("td")
            if td:
                return td.get_text(strip=True)
    return ""


def _parsear_series(soup: BeautifulSoup) -> list[Serie]:
    """Cada parámetro es una fila con <th>; sus links de descarga pueden estar en la
    fila misma o en las filas 'hideme' siguientes (sin <th>)."""
    series: list[Serie] = []
    for tabla in soup.find_all("table", class_="gob"):
        actual = None
        for fila in tabla.find_all("tr"):
            th = fila.find("th")
            if th:
                texto = th.get_text("\n", strip=True)
                m = re.match(r"^(.*?)\s*\((.*)\)\s*$", texto, re.DOTALL)
                nombre, detalle = (m.group(1), m.group(2)) if m else (texto, "")
                actual = (" ".join(nombre.split()), " ".join(detalle.split()))
            if actual is None:
                continue
            for a in fila.find_all("a", class_="iframe", href=True):
                macro = re.search(r"macro=([^&]+)", a["href"])
                if not macro:
                    continue
                macro = macro.group(1)
                resolucion = next((r for r in RESOLUCIONES if r in macro), None)
                if not resolucion:
                    continue
                # Series meteorológicas: 'horario_003' -> 3 m ; 'horario_000' -> S/I
                h = re.search(r"_(\d{3})$", macro)
                altura = int(h.group(1)) or None if h else None
                series.append(Serie(actual[0], actual[1], resolucion, altura, urljoin(BASE_URL, a["href"])))
    return series


def leer_estacion(sesion: requests.Session, url: str, region_codigo: str) -> Estacion:
    resp = sesion.get(url, timeout=30)
    resp.raise_for_status()
    soup = _soup(resp)
    h1 = soup.select_one("article.post header h1")
    utm, huso = _fila(soup, "Coordenadas UTM"), _fila(soup, "Huso")
    lat, lon = utm_a_latlon(utm, huso)
    return Estacion(
        id=url.rstrip("/").split("/")[-1],
        nombre=h1.get_text(strip=True) if h1 else "Estacion_Desconocida",
        region_codigo=region_codigo,
        region=REGIONES.get(region_codigo, _fila(soup, "Región")),
        comuna=_fila(soup, "Comuna"),
        utm=utm,
        huso=huso,
        lat=lat,
        lon=lon,
        url=url,
        series=_parsear_series(soup),
    )


def cargar_estaciones(
    codigos_region: list[str],
    comunas: list[str] | None = None,
    ids: list[str] | None = None,
    progreso=print,
) -> list[Estacion]:
    """Lee todas las estaciones de las regiones y aplica filtros por comuna / id."""
    sesion = nueva_sesion()
    urls = listar_urls_estaciones(sesion, codigos_region)
    progreso(f"Se encontraron {len(urls)} estaciones. Leyendo fichas...")

    def leer(item):
        url, codigo = item
        try:
            return leer_estacion(sesion, url, codigo)
        except requests.RequestException as e:
            progreso(f"  [aviso] no se pudo leer {url}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        estaciones = [e for e in pool.map(leer, urls.items()) if e]

    if ids:
        estaciones = [e for e in estaciones if e.id in ids]
    if comunas:
        buscadas = [normalizar(c) for c in comunas]
        estaciones = [e for e in estaciones if any(c in normalizar(e.comuna) for c in buscadas)]
    return sorted(estaciones, key=lambda e: (e.region_codigo, e.comuna, e.nombre))


def seleccionar_series(
    estacion: Estacion, parametros: dict[str, str]
) -> tuple[list[Serie], list[str]]:
    """Elige qué series descargar. `parametros` = {alias_o_texto: resolucion}.

    Regla de altura: si un parámetro tiene una serie con altura declarada (3 m, 10 m) y otra
    'S/I', se prefiere la que tiene altura (la S/I es un alias congelado de la misma medición).
    Devuelve (series, avisos).
    """
    elegidas: list[Serie] = []
    avisos: list[str] = []
    for token, resolucion in parametros.items():
        fragmento = ALIAS_PARAMETROS.get(token.lower(), normalizar(token))
        candidatas = [
            s for s in estacion.series
            if fragmento in normalizar(s.parametro + s.detalle) and s.resolucion == resolucion
        ]
        if not candidatas:
            avisos.append(f"{token} ({resolucion}): no disponible")
            continue
        por_parametro: dict[str, list[Serie]] = {}
        for s in candidatas:
            por_parametro.setdefault(s.parametro, []).append(s)
        for opciones in por_parametro.values():
            elegidas.append(max(opciones, key=lambda s: s.altura or 0))
    return elegidas, avisos
