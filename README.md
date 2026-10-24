# SINCA Scraper Chile

Descarga series históricas de calidad del aire (MP2.5, MP10, O₃, …) y variables meteorológicas
(temperatura, humedad, viento) desde el [Sistema de Información Nacional de Calidad del Aire (SINCA)](https://sinca.mma.gob.cl)
del Ministerio del Medio Ambiente de Chile, filtrando por región, comuna o estación.

Nació para un proyecto de Big Data cuyo caso de estudio era MP2.5, complementado con variables
meteorológicas medidas en las mismas estaciones.

## Instalación

Requiere Python 3.10+ y Google Chrome (el driver se descarga solo).

```bash
git clone https://github.com/NicoAndresSSNA/SINCA-scraper-Chile.git
cd SINCA-scraper-Chile
pip install -r requirements.txt
```

## Modo interactivo (recomendado si no usas la terminal a menudo)

```bash
python -m sinca
```

Un asistente te pregunta paso a paso: región → comuna → estaciones → parámetros → resolución → carpeta.
Solo ofrece los parámetros que realmente miden las estaciones que elegiste, te muestra el plan y pide
confirmación antes de descargar. Al final imprime el **comando equivalente** para repetir lo mismo sin
el asistente. En cualquier pregunta puedes escribir números sueltos o rangos (`1 3`, `2-4`), `Enter` para
elegir todo, o `q` para salir.

## Uso directo (comandos)

```bash
# 1. ¿Qué voy a descargar? (no abre el navegador)
python -m sinca descargar -r M -c "El Bosque" -p mp25 humedad temperatura viento --dry-run

# 2. Descargar
python -m sinca descargar -r M -c "El Bosque" -p mp25 humedad temperatura viento
```

Los archivos quedan en `descargas_sinca/` junto a un `_resumen.csv` con el estado de cada serie.
Si se interrumpe (o algo falla), **vuelve a ejecutar el mismo comando**: salta lo ya descargado.

### Comandos

| Comando | Qué hace |
| :--- | :--- |
| `interactivo` | Asistente paso a paso (es lo que se abre al ejecutar `python -m sinca` sin comando) |
| `descargar` | Descarga las series de las estaciones elegidas |
| `estaciones` | Exporta el catálogo de estaciones (con latitud/longitud) a CSV |
| `regiones` | Lista los códigos de región (`M`, `V`, `VIII`, …) |
| `parametros` | Lista los atajos de parámetros (`mp25`, `humedad`, …) |

### Filtros (`descargar` y `estaciones`)

| Opción | Ejemplo | Notas |
| :--- | :--- | :--- |
| `-r`, `--region` | `-r M V` · `-r TODAS` | Defecto: `M` |
| `-c`, `--comuna` | `-c "El Bosque" Quilicura` | Acepta nombres parciales, sin importar tildes |
| `-e`, `--estacion` | `-e 260` | ID de estación (columna `id` del catálogo) |

### Opciones de `descargar`

| Opción | Descripción |
| :--- | :--- |
| `-p`, `--parametros` | Atajos o parte del nombre: `mp25 mp10 o3 so2 co no2 humedad temperatura viento dir_viento vel_viento`. Para elegir resolución por parámetro: `mp10:diario`. |
| `--resolucion` | `horario` (defecto), `diario` o `mensual` |
| `-o`, `--salida` | Carpeta de salida (defecto `descargas_sinca`) |
| `--dry-run` | Muestra el plan sin descargar |
| `--sobrescribir` | Vuelve a descargar archivos existentes |
| `--ver-navegador` | Muestra Chrome (para depurar) |
| `--timeout` | Segundos máximos por archivo (defecto 90) |
| `--config` | Archivo JSON con estas mismas opciones |

### Archivo de configuración (opcional)

Copia `config.example.json` a `config.json` y ejecuta `python -m sinca descargar --config config.json`.
Las claves son los nombres de las opciones de arriba; lo que escribas en la consola tiene prioridad.

## Catálogo de estaciones

`data/estaciones_sinca.csv` es un snapshot de las 219 estaciones del país (región, comuna, latitud/longitud
WGS84 convertida desde UTM, y series disponibles). Regéneralo con:

```bash
python -m sinca estaciones -r TODAS -o data/estaciones_sinca.csv
```

## Detalles a tener en cuenta

- **Formato de los datos descargados**: el SINCA entrega CSV separados por `;` y con coma decimal.
  En pandas: `pd.read_csv(ruta, sep=";", decimal=",")`. Las fechas vienen como `YYMMDD` y la hora como `HHMM`.
- **Alturas `S/I`**: varias estaciones publican la misma variable meteorológica dos veces, una sin
  altura (`S/I`) y otra con altura declarada (3 m, 10 m). La serie `S/I` es un alias de la misma medición,
  así que el scraper prioriza la que tiene altura y usa `S/I` solo si es la única.
- **Series no disponibles**: si una estación no mide el parámetro (o no con esa resolución) se informa como
  `[omitido]` y se continúa.
- **Uso responsable**: las descargas son secuenciales a propósito. Los datos pertenecen al Ministerio del
  Medio Ambiente; revisa los términos de uso del SINCA para redistribuirlos.

## Estructura

```text
sinca/
├── catalogo.py   # estaciones, coordenadas, series disponibles (requests + BeautifulSoup)
├── descarga.py   # descarga con Selenium y escritura de CSV
├── cli.py        # línea de comandos
└── interactivo.py # asistente paso a paso
data/estaciones_sinca.csv
```

## Licencia

MIT
