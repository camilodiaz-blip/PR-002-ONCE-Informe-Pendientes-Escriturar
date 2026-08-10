from datetime import datetime
import os
import pandas as pd
from glob import glob
import pandas as pd
import requests



def get_task(project_code, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1//getTasks/10595/{project_code}/{prospect_id}'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            TaskList = payload.get('TaskList', [])
            
            # Validamos si realmente llegaron tareas en la lista
            if TaskList:
                # 1. Aplanamos el JSON usando la estructura jerárquica
                df = pd.json_normalize(
                    TaskList, 
                    record_path=['prospectTasksDetail'], 
                    meta=['taskListName']
                )
                
                # 2. Definimos el orden exacto de todas las columnas requeridas
                columnas_filtradas = ["prospectId", "taskListName", "CompanyTask",
                    "prospectTaskListId", "scheduleDateFormat",
                    "scheduleDate", "startDate", "endDate", "comments"
                ]
                
                # 3. Filtramos y reordenamos el DataFrame
                df_final = df[columnas_filtradas]
                return df_final
            
            else:
                # Aquí conectamos tu bloque else en caso de que TaskList venga vacío []
                print(f"Sin tareas (TaskList vacío) para {project_code} (ID {prospect_id})")
                return pd.DataFrame()  # Retorna un DF vacío para que no rompa el bucle principal
                
        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {prospect_id}")
            return pd.DataFrame()
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {prospect_id}: {e}")
        return pd.DataFrame()
    


# ubicacion carpeta de destino
CARPETA_BASE_RAW = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data',
    'raw',
    'no_escriturados'
)
os.makedirs(CARPETA_BASE_RAW, exist_ok=True)


#Cargue de clientes
carpeta = r"data\staging"
archivos = glob(os.path.join(carpeta, "*.parquet"))
df = pd.concat([pd.read_parquet(archivo) for archivo in archivos], ignore_index=True)

df['escritura_programada_anio']= pd.to_datetime(df['fecha_escritura_programada']).dt.year
df_no_escriturados = df[(df['escriturado'] == 0) &  (df['escritura_programada_anio']== 2026)]
print ("cargue de clientes ok")



# Generacion de listado de tareas de tramites
df_task_list = []
contador = 1;
total_clientes=df_no_escriturados.shape[0]
for _, prospect in df_no_escriturados.iterrows():
    print("Cliente ",str(contador), " de ",total_clientes )
    contador+=1
    prospect_id = prospect['id_prospecto']
    project_code = prospect['id_proyecto']
    task_df = get_task(project_code, prospect_id)
    if not task_df.empty:
        df_task_list.append(task_df)
print ("cargue de tareas ok")
if df_task_list:
    df_task = pd.concat(df_task_list, ignore_index=True)
else:
    df_task = pd.DataFrame()

## Guardar Archivos tramites
df_task['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
ruta_archivo_task = os.path.join(CARPETA_BASE_RAW, f"tareas_tramites.parquet")
df_task.to_parquet(ruta_archivo_task, index=False, compression='snappy')
print ("Tramites Guardados")
