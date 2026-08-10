from datetime import datetime

import pandas as pd
import requests

from api_utils import (
    get_session, fetch_in_parallel, MAX_WORKERS, REQUEST_TIMEOUT,
    cargar_clientes_staging, filtrar_no_escriturados, RUTA_RAW_NO_ESCRITURADOS,
    guardar_parquet_versionado,
)


def get_scheduled_payments(project_code, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1/GetCustomerScheduledPayments/10595/{project_code}/{prospect_id}'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            recordsArray = payload.get('recordsArray', [])

            # Validamos si realmente llegaron tareas en la lista
            if recordsArray:
                # 1. Aplanamos el JSON usando la estructura jerárquica
                df = pd.json_normalize(recordsArray)
                df['prospectId'] = prospect_id
                return df

            else:
                print(f"Sin pagos para {project_code} (ID {prospect_id})")
                return pd.DataFrame()
        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {prospect_id}")
            return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {prospect_id}: {e}")
        return pd.DataFrame()




def guardar_pagos(df_payment):
    df_payment['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
    ruta = guardar_parquet_versionado(df_payment, RUTA_RAW_NO_ESCRITURADOS, "pagos")
    print(f"Pagos Guardados en {ruta}")


def run():
    #Cargue de clientes
    df = cargar_clientes_staging()
    df_no_escriturados = filtrar_no_escriturados(df)
    print("cargue de clientes ok")
    print("total clientes: ", df_no_escriturados.shape[0])

    # Generacion de listado de pagos (en paralelo)
    items = [(prospect['id_proyecto'], prospect['id_prospecto']) for _, prospect in df_no_escriturados.iterrows()]
    df_payments_list = fetch_in_parallel(items, get_scheduled_payments, max_workers=MAX_WORKERS, label="Cliente")

    print("cargue de pagos ok")
    if df_payments_list:
        df_payment = pd.concat(df_payments_list, ignore_index=True)
    else:
        df_payment = pd.DataFrame()

    guardar_pagos(df_payment)


if __name__ == "__main__":
    run()
