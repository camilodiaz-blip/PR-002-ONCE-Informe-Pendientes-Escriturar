import importlib
from datetime import datetime
import os
import pandas as pd
import requests

from api_utils import (
    get_session, fetch_in_parallel, guardar_parquet_versionado, MAX_WORKERS, REQUEST_TIMEOUT,
    ANIO_OBJETIVO_ESCRITURA, RUTA_ANALYTICS, RUTA_RAW_CONVERSACIONES,
)

# Reutiliza la clasificacion de tramites del dashboard (matriz Credito x Subsidio: Sin
# Radicados / Pdt un Radicado / Radicados / Listo, ver MATRIZ_CATEGORIA), para no duplicar
# esa logica de negocio aca. 6_dashboard.py empieza con un digito, por eso se importa con
# importlib (igual que en main.py).
_dashboard = importlib.import_module("6_dashboard")

# Clientes en "Sin Radicados" (no tienen ni una sola radicacion de lo que necesitan) o "Pdt
# un Radicado" (les falta radicar uno de los dos tramites) -- ver _clasificar_tramites en
# 6_dashboard.py. Se dejan afuera "Radicados" y "Listo": ya tienen todo lo que pueden radicar
# radicado, asi que el seguimiento de conversaciones ya no aporta para destrabar su avance.
CATEGORIAS_CON_SEGUIMIENTO = ['Sin Radicados', 'Pdt un Radicado']

#Cargue de conversaciones de estos clientes


def prospects_events(proyecto_id, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1/getProspectEvents/10595/{proyecto_id}/{prospect_id}'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            Events = payload.get('events', [])

            # Validamos si realmente llegaron tareas en la lista
            if Events:
                # 1. Aplanamos el JSON usando la estructura jerárquica
                df = pd.json_normalize(Events)
                return df

            else:
                print(f"Sin Eventos para {proyecto_id} (ID {prospect_id})")
                return pd.DataFrame()  # Retorna un DF vacío para que no rompa el bucle principal

        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {prospect_id}")
            return pd.DataFrame()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {prospect_id}: {e}")
        return pd.DataFrame()


def run():
    #Cargue de clientes con valores detallados
    df = pd.read_csv(os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv"))
    no_escriturados = df[
        (df['escriturado'] == 0) &
        (df['escritura_programada_anio'] == ANIO_OBJETIVO_ESCRITURA)
    ].copy()

    no_escriturados['categoria'] = no_escriturados.apply(
        lambda r: _dashboard._clasificar_tramites(r)[0], axis=1
    )
    df_filtrado = no_escriturados[no_escriturados['categoria'].isin(CATEGORIAS_CON_SEGUIMIENTO)]

    # Generacion de listado de eventos (en paralelo)
    items = [(prospect['id_proyecto'], prospect['id_prospecto']) for _, prospect in df_filtrado.iterrows()]
    df_events_list = fetch_in_parallel(items, prospects_events, max_workers=MAX_WORKERS, label="Cliente")
    print("cargue de eventos ok")

    if df_events_list:
        df_events = pd.concat(df_events_list, ignore_index=True)
    else:
        df_events = pd.DataFrame()

    ## Guardar Archivos tramites
    df_events['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
    ruta_archivo_eventos = guardar_parquet_versionado(df_events, RUTA_RAW_CONVERSACIONES, "eventos")
    print(f"Eventos Guardados en {ruta_archivo_eventos}")
    return ruta_archivo_eventos


if __name__ == "__main__":
    run()
