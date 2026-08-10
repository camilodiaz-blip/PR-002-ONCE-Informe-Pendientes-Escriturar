import os
import pandas as pd
from glob import glob

from api_utils import RUTA_RAW_CLIENTES, RUTA_STAGING


def run():
    #Cargue de clientes
    archivos = glob(os.path.join(RUTA_RAW_CLIENTES, "*.parquet"))
    df = pd.concat([pd.read_parquet(archivo) for archivo in archivos], ignore_index=True)

    df = df[['project', 'projectCode','prospectId','firstName','lastName','identificationNumber','module',
             'stageName','agreementNumber','registrationNumber','closeDate','deedDate','deedScheduledDate']]

    df['closeDate'] = pd.to_datetime(df['closeDate'], errors='coerce')
    df['deedDate'] = pd.to_datetime(df['deedDate'], errors='coerce')

    df.rename(columns={
        'project': 'proyecto',
        'projectCode': 'id_proyecto',
        'prospectId': 'id_prospecto',
        'firstName': 'nombre',
        'lastName': 'apellido',
        'identificationNumber': 'numero_identificacion',
        'module': 'modulo',
        'stageName': 'etapa_venta',
        'agreementNumber': 'encargo',
        'registrationNumber': 'numero_escritura',
        'closeDate': 'fecha_cierre',
        'deedDate': 'fecha_escritura',
        'deedScheduledDate':'fecha_escritura_programada'
    }, inplace=True)

    df['escriturado']=df['fecha_escritura'].notnull().astype(int)

    # La API de Smarthome entrega algunos nombres de proyecto/modulo con espacios de mas
    # (ej. "VERDELIMA " con espacio al final) -- se limpia aca, en el cargue inicial, para que
    # todo lo que viene despues (staging, cruces con pagos/tareas, dashboard, historico) ya
    # trabaje con el nombre correcto, sin tener que repetir el strip() en cada script.
    df['proyecto'] = df['proyecto'].astype(str).str.strip()
    df['modulo'] = df['modulo'].astype(str).str.strip()

    os.makedirs(RUTA_STAGING, exist_ok=True)
    ruta_archivo = os.path.join(RUTA_STAGING, "clientes.parquet")
    df.to_parquet(ruta_archivo, index=False, compression='snappy')


if __name__ == "__main__":
    run()

