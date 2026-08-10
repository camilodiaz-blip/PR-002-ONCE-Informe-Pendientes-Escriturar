from datetime import datetime
import os
import pandas as pd
import requests

from api_utils import get_session, fetch_in_parallel, MAX_WORKERS, REQUEST_TIMEOUT

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


#Cargue de clientes con valores detallados
df = pd.read_csv(r"data\analytics\clientes_detallado.csv")
df_filtrado = df[(df['escriturado']==0) &
                 (df['escritura_programada_anio']==2026) &
                  (( #Requiere subsidio
                      (df['subsidio']==1) & (df['subsidio_aprobado']==0)
                  )
                   |
                    ( #Requiere Credito
                       (df['credito']==1) & (df['credito_aprobado']==0)
                   ))]




# Generacion de listado de eventos (en paralelo)
items = [(prospect['id_proyecto'], prospect['id_prospecto']) for _, prospect in df_filtrado.iterrows()]
df_events_list = fetch_in_parallel(items, prospects_events, max_workers=MAX_WORKERS, label="Cliente")
print("cargue de eventos ok")

if df_events_list:
    df_events = pd.concat(df_events_list, ignore_index=True)
else:
    df_events = pd.DataFrame()

## Guardar Archivos tramites

CARPETA_BASE_RAW = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data',
    'raw',
    'no_escriturados'
)
os.makedirs(CARPETA_BASE_RAW, exist_ok=True)

df_events['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
ruta_archivo_eventos = os.path.join(CARPETA_BASE_RAW, "eventos.parquet")
df_events.to_parquet(ruta_archivo_eventos, index=False, compression='snappy')
print("Eventos Guardados")
