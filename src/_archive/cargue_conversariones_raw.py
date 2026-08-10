from datetime import datetime
from glob import glob
import os
import pandas as pd
import requests


#Cargue de conversaciones de estos clientes


def prospects_events(proyecto_id, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1/getProspectEvents/10595/{proyecto_id}/{prospect_id}'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            Events = payload.get('events', [])
            
            # Validamos si realmente llegaron tareas en la lista
            if Events:
                # 1. Aplanamos el JSON usando la estructura jerárquica
                df = pd.json_normalize(Events)
                return df
            
            else:
                # Aquí conectamos tu bloque else en caso de que TaskList venga vacío []
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

df_filtrado=df_filtrado.head(1)




# Generacion de listado de tareas de tramites
df_events_list = []
contador = 1;
total_clientes=df_filtrado.shape[0]
for _, prospect in df_filtrado.iterrows():
    print("Cliente ",str(contador), " de ",total_clientes )
    contador+=1
    prospect_id = prospect['id_prospecto']
    project_code = prospect['id_proyecto']
    events_df = prospects_events(project_code, prospect_id)
    if not events_df.empty:
        df_events_list.append(events_df)
print ("cargue de eventos ok")

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
ruta_archivo_task = os.path.join(CARPETA_BASE_RAW, f"eventos.parquet")
df_events.to_parquet(ruta_archivo_task, index=False, compression='snappy')
print ("Eventos Guardados")
