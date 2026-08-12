import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from glob import glob

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Numero de llamadas concurrentes a las APIs del proyecto.
# Valor conservador porque no conocemos el limite real de rate limiting de smart-home.
# Si no aparecen errores 429 en consola, se puede subir progresivamente (ej. 10, 15, 20...).
MAX_WORKERS = 8

# Concurrencia para rafagas cortas (ej. script 1: solo 10 proyectos en un solo lote).
# Con pocos items, lanzar 8 conexiones casi al mismo instante parece disparar un corte
# de conexion del lado del servidor (ConnectionResetError / "Connection aborted").
# Con volumenes grandes (cientos/miles de clientes, ej. script 4) esto no se ha visto,
# por eso queda separado de MAX_WORKERS en vez de bajar el valor general.
MAX_WORKERS_RAFAGA_CORTA = 3
ESPERA_ENTRE_LANZAMIENTOS = 0.4  # segundos entre cada envio, para no disparar todo de una

REQUEST_TIMEOUT = 30  # segundos, evita que una llamada colgada bloquee todo el proceso

# Año de escrituración objetivo del informe. Cambiar aca afecta scripts 3, 4 y 5.
ANIO_OBJETIVO_ESCRITURA = 2026

# Rutas absolutas basadas en la ubicacion de este archivo (src/), no en el
# directorio de trabajo actual. Antes cada script usaba rutas relativas tipo
# r"data\staging", lo cual falla en silencio (glob vacio -> ValueError en
# pd.concat) si el script se ejecuta desde un cwd distinto al del proyecto.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_RAW_CLIENTES = os.path.join(BASE_DIR, 'data', 'raw', 'clientes')
RUTA_STAGING = os.path.join(BASE_DIR, 'data', 'staging')
RUTA_RAW_NO_ESCRITURADOS = os.path.join(BASE_DIR, 'data', 'raw', 'no_escriturados')
RUTA_RAW_PAGOS = os.path.join(BASE_DIR, 'data', 'raw', 'pagos')
RUTA_RAW_ESTADO_CUENTAS = os.path.join(BASE_DIR, 'data', 'raw', 'estado_cuentas')
RUTA_ANALYTICS = os.path.join(BASE_DIR, 'data', 'analytics')
RUTA_HISTORICO = os.path.join(BASE_DIR, 'data', 'historico')
RUTA_REPORTES = os.path.join(BASE_DIR, 'data', 'reportes')

_thread_local = threading.local()


def cargar_clientes_staging():
    """Carga data/staging/clientes.parquet (generado por 2_cargue_clientes_staging.py)."""
    archivos = glob(os.path.join(RUTA_STAGING, "clientes.parquet"))
    if not archivos:
        raise FileNotFoundError(
            f"No se encontro clientes.parquet en {RUTA_STAGING}. "
            "Ejecuta primero 2_cargue_clientes_staging.py."
        )
    return pd.concat([pd.read_parquet(a) for a in archivos], ignore_index=True)


def filtrar_no_escriturados(df, anio=None):
    """
    Clientes no escriturados. Sin `anio` (por defecto), retorna TODOS los no escriturados sin
    importar el año proyectado de escritura -- es el colchon que usan los scripts 3 y 4 al traer
    pagos/tareas, para no depender del año objetivo exacto ni tener que re-ejecutar el fetch cada
    vez que un cliente pasa de año o el objetivo del informe cambia.
    Con `anio`, ademas exige que la fecha proyectada de escritura sea ese año -- es el alcance real
    del informe (ver ANIO_OBJETIVO_ESCRITURA y 'en_alcance_no_escriturado' en el script 5).
    """
    df = df.copy()
    df['escritura_programada_anio'] = pd.to_datetime(df['fecha_escritura_programada']).dt.year
    resultado = df[df['escriturado'] == 0]
    if anio is not None:
        resultado = resultado[resultado['escritura_programada_anio'] == anio]
    return resultado


def guardar_parquet_versionado(df, carpeta, prefijo):
    """
    Guarda df como {carpeta}/{prefijo}_{YYYYMMDD}.parquet -- una version nueva por corrida, nunca
    se sobreescribe una version anterior. Permite comparar la evolucion entre corridas y evita que
    una corrida fallida corrompa el historico completo (a diferencia de un solo archivo que se
    reescribe cada vez).
    """
    os.makedirs(carpeta, exist_ok=True)
    fecha = datetime.now().strftime('%Y%m%d')
    ruta = os.path.join(carpeta, f"{prefijo}_{fecha}.parquet")
    df.to_parquet(ruta, index=False, compression='snappy')
    return ruta


def leer_ultimo_parquet(carpeta, prefijo):
    """Lee la version mas reciente de {carpeta}/{prefijo}_*.parquet (ordena por nombre, YYYYMMDD)."""
    archivos = sorted(glob(os.path.join(carpeta, f"{prefijo}_*.parquet")))
    if not archivos:
        raise FileNotFoundError(
            f"No se encontro ningun archivo '{prefijo}_*.parquet' en {carpeta}. "
            "Ejecuta primero el script que lo genera."
        )
    return pd.read_parquet(archivos[-1])


def leer_parquet_mas_antigua(carpeta, prefijo):
    """Lee la version mas antigua de {carpeta}/{prefijo}.parquet o {prefijo}_*.parquet."""
    archivos = []
    archivos.extend(glob(os.path.join(carpeta, f"{prefijo}.parquet")))
    archivos.extend(glob(os.path.join(carpeta, f"{prefijo}_*.parquet")))
    archivos = sorted(set(archivos))

    if not archivos:
        raise FileNotFoundError(
            f"No se encontro ningun archivo '{prefijo}.parquet' o '{prefijo}_*.parquet' en {carpeta}."
        )

    return pd.read_parquet(archivos[0])


def get_session():
    """Sesion HTTP reutilizable por hilo, con reintentos y backoff ante rate limiting / errores 5xx."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,  # espera 1s, 2s, 4s entre reintentos
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _thread_local.session = session
    return _thread_local.session


def fetch_in_parallel(items, fetch_fn, max_workers=MAX_WORKERS, label="Cliente"):
    """
    Ejecuta fetch_fn sobre cada elemento de items en paralelo (hilos) e imprime progreso.

    items: iterable de argumentos para fetch_fn. Cada elemento puede ser una tupla
        (se desempaqueta como *args al llamar fetch_fn) o un valor unico.
    fetch_fn: funcion que recibe el/los argumento(s) de un item y retorna un pd.DataFrame
        (vacio o None si no hay datos para ese item).

    Retorna una lista con los DataFrames no vacios obtenidos (listo para pd.concat).
    """
    items = list(items)
    total = len(items)
    completados = 0
    lock = threading.Lock()
    resultados = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for item in items:
            if isinstance(item, tuple):
                future = executor.submit(fetch_fn, *item)
            else:
                future = executor.submit(fetch_fn, item)
            futures[future] = item

        for future in as_completed(futures):
            item = futures[future]
            with lock:
                completados += 1
                print(f"{label} {completados} de {total}")
            try:
                df = future.result()
                if df is not None and not df.empty:
                    resultados.append(df)
            except Exception as e:
                print(f"Error inesperado procesando {item}: {e}")

    return resultados


def fetch_dos_en_paralelo(items, fetch_fn_a, fetch_fn_b, max_workers=MAX_WORKERS, label="Cliente"):
    """
    Como fetch_in_parallel, pero por cada item llama fetch_fn_a y fetch_fn_b en el MISMO
    ThreadPoolExecutor (un solo recorrido concurrente de 2*N llamadas en vez de dos
    recorridos completos de N llamadas cada uno, uno detras del otro).

    items: iterable de tuplas, se desempaqueta como *args para ambas funciones.
    Retorna (resultados_a, resultados_b), cada uno listo para pd.concat.
    """
    items = list(items)
    total = len(items) * 2
    completados = 0
    lock = threading.Lock()
    resultados_a, resultados_b = [], []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for item in items:
            futures[executor.submit(fetch_fn_a, *item)] = ('a', item)
            futures[executor.submit(fetch_fn_b, *item)] = ('b', item)

        for future in as_completed(futures):
            origen, item = futures[future]
            with lock:
                completados += 1
                print(f"{label} {completados} de {total}")
            try:
                df = future.result()
                if df is not None and not df.empty:
                    (resultados_a if origen == 'a' else resultados_b).append(df)
            except Exception as e:
                print(f"Error inesperado procesando {item} ({origen}): {e}")

    return resultados_a, resultados_b
