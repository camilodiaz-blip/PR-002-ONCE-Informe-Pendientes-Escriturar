from datetime import datetime

import pandas as pd
import requests

from api_utils import (
    get_session, fetch_in_parallel, MAX_WORKERS, REQUEST_TIMEOUT,
    cargar_clientes_staging, filtrar_no_escriturados, RUTA_RAW_NO_ESCRITURADOS,
    guardar_parquet_versionado,
)

COLUMNAS_FILTRADAS = [
    "prospectId", "taskListName", "CompanyTask",
    "prospectTaskListId", "scheduleDateFormat",
    "scheduleDate", "startDate", "endDate", "comments"
]


def get_task(project_code, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1/getTasks/10595/{project_code}/{prospect_id}'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
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

                # 2. Filtramos y reordenamos el DataFrame (solo columnas que sí llegaron)
                columnas_presentes = [c for c in COLUMNAS_FILTRADAS if c in df.columns]
                columnas_faltantes = [c for c in COLUMNAS_FILTRADAS if c not in df.columns]
                if columnas_faltantes:
                    print(f"Aviso: columnas faltantes {columnas_faltantes} para prospect {prospect_id}")
                df_final = df[columnas_presentes]
                return df_final

            else:
                print(f"Sin tareas (TaskList vacío) para {project_code} (ID {prospect_id})")
                return pd.DataFrame()  # Retorna un DF vacío para que no rompa el bucle principal

        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {prospect_id}")
            return pd.DataFrame()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {prospect_id}: {e}")
        return pd.DataFrame()



def guardar_tareas(df_task):
    df_task['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
    ruta = guardar_parquet_versionado(df_task, RUTA_RAW_NO_ESCRITURADOS, "tareas_tramites")
    print(f"Tramites Guardados en {ruta}")


def run():
    # Cargue de clientes
    df = cargar_clientes_staging()
    df_no_escriturados = filtrar_no_escriturados(df)
    print("cargue de clientes ok")

    # Generacion de listado de tareas de tramites (en paralelo)
    items = [(prospect['id_proyecto'], prospect['id_prospecto']) for _, prospect in df_no_escriturados.iterrows()]
    df_task_list = fetch_in_parallel(items, get_task, max_workers=MAX_WORKERS, label="Cliente")

    print("cargue de tareas ok")
    if df_task_list:
        df_task = pd.concat(df_task_list, ignore_index=True)
    else:
        df_task = pd.DataFrame()

    guardar_tareas(df_task)


if __name__ == "__main__":
    run()
