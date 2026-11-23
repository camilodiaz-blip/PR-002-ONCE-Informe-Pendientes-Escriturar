from datetime import datetime
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from api_utils import (
    get_session, MAX_WORKERS_RAFAGA_CORTA, ESPERA_ENTRE_LANZAMIENTOS, REQUEST_TIMEOUT_DESCARGA_GRANDE,
    REINTENTOS_PROYECTO_FALLIDO, ESPERA_ANTES_DE_REINTENTAR,
)

proyects_id = {
    "Azul Club Residencial Celeste": "1001",
    "Azul Club Residencial Turquesa": "1002",
    "Candil": "d8606278",
    "Cristales": "93123aea",
    "Las Mañanitas Apartamentos VIS": "1006",
    "Las Mañanitas Casas": "22653ed1",
    "VERDELIMA": "1007",
    "Verdeoliva": "1005",
    "Verdepino": "772bf3df",
    "Verdevivo": "1003"
}

CARPETA_BASE_RAW = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data',
    'raw',
    'clientes',
)


def get_sales(proyect, proyectid):
    print(f"iniciando para: {proyect} with ID: {proyectid}")
    url = f'https://api.smart-home.com.co/api/v1/getSales/10595/{proyectid}'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_DESCARGA_GRANDE)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            prospects = payload.get('prospects', [])
            if prospects:
                data = pd.json_normalize(prospects)
                data['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
                return proyect, data
            else:
                print(f"Sin prospects para {proyect} (ID {proyectid})")
        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {proyectid}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {proyectid}: {e}")
    return proyect, pd.DataFrame()


def run():
    """
    Retorna {'actualizados': [...], 'fallidos': [...]} con la lista de proyectos cuyo
    archivo raw se refresco en esta corrida, y los que no (quedaron con el archivo viejo,
    si existia, porque get_sales() no pudo traer datos nuevos). main.py usa esto para
    avisar si el pipeline seguiria con datos desactualizados en algun proyecto.
    """
    os.makedirs(CARPETA_BASE_RAW, exist_ok=True)

    actualizados = []
    fallidos = []

    # Cada proyecto se guarda en su propio archivo, por eso no se usa fetch_in_parallel
    # (que concatena todo en un solo resultado) sino un ThreadPoolExecutor directo.
    # Concurrencia baja + pequeño espera entre envios: con solo 10 proyectos, lanzar todo
    # de una (8 conexiones casi simultaneas) ha provocado que el servidor corte la conexion
    # (ConnectionResetError / "Connection aborted") en varios proyectos a la vez.
    def guardar(proyect, data):
        ruta_archivo = os.path.join(CARPETA_BASE_RAW, f"{proyect}.parquet")
        data.to_parquet(ruta_archivo, index=False, compression='snappy')
        print(f"Guardado: {ruta_archivo}")
        actualizados.append(proyect)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_RAFAGA_CORTA) as executor:
        futures = []
        for proyect, proyectid in proyects_id.items():
            futures.append(executor.submit(get_sales, proyect, proyectid))
            time.sleep(ESPERA_ENTRE_LANZAMIENTOS)
        for future in as_completed(futures):
            proyect, data = future.result()
            if not data.empty:
                guardar(proyect, data)
            else:
                fallidos.append(proyect)

    # Los que fallaron en el lote (timeout o corte de conexion del servidor) se reintentan
    # uno por uno, sin otras descargas en paralelo, despues de una pausa.
    for intento in range(1, REINTENTOS_PROYECTO_FALLIDO + 1):
        if not fallidos:
            break
        print(f"Reintento {intento} de {REINTENTOS_PROYECTO_FALLIDO} para {len(fallidos)} proyecto(s) "
              f"en {ESPERA_ANTES_DE_REINTENTAR} s: {', '.join(fallidos)}")
        time.sleep(ESPERA_ANTES_DE_REINTENTAR)
        pendientes, fallidos = fallidos, []
        for proyect in pendientes:
            _, data = get_sales(proyect, proyects_id[proyect])
            if not data.empty:
                guardar(proyect, data)
            else:
                fallidos.append(proyect)

    return {'actualizados': actualizados, 'fallidos': fallidos}


if __name__ == "__main__":
    run()
