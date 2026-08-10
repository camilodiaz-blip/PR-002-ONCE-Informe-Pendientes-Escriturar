from datetime import datetime
import os
import pandas as pd
from glob import glob
import pandas as pd
import requests


def get_scheduled_payments(project_code, prospect_id):
    url = f'https://api.smart-home.com.co/api/v1//GetCustomerScheduledPayments/10595/{project_code}/{prospect_id}'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            recordsArray = payload.get('recordsArray', [])
            
            # Validamos si realmente llegaron tareas en la lista
            if recordsArray:
                # 1. Aplanamos el JSON usando la estructura jerárquica
                df = pd.json_normalize(recordsArray)
                
                df['prospectId']= prospect_id           
                # 3. Filtramos y reordenamos el DataFrame
                df_final = df
                return df_final

            else:
                print(f"Sin pagos para {project_code} (ID {prospect_id})")
        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {prospect_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {prospect_id}: {e}")


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
print ("total clientes: ",df_no_escriturados.shape[0])


# Generacion de listado de pagos
df_payments_list = []
contador = 1;
total_clientes=df_no_escriturados.shape[0]
for _, prospect in df_no_escriturados.iterrows():
    print("Cliente ",str(contador), " de ",total_clientes )
    contador+=1
    prospect_id = prospect['id_prospecto']
    project_code = prospect['id_proyecto']
    payment_df = get_scheduled_payments(project_code, prospect_id)
    if not payment_df.empty:
        df_payments_list.append(payment_df)

print ("cargue de pagos ok")
if df_payments_list:
    df_payment = pd.concat(df_payments_list, ignore_index=True)
else:
    df_payment = pd.DataFrame()


## Guardar Archivos Pagos
df_payment['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
ruta_archivo_payment = os.path.join(CARPETA_BASE_RAW, f"pagos.parquet")
df_payment.to_parquet(ruta_archivo_payment, index=False, compression='snappy')

print ("Pagos Guardados")