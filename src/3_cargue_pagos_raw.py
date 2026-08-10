from datetime import datetime
import os
import pandas as pd
import requests

from api_utils import get_session, REQUEST_TIMEOUT


CARPETA_BASE_RAW = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data',
    'raw',
    'pagos'
)


def get_payments():
    url = 'https://manage.smart-home.com.co/api/bi/GetPaymentsRecords/YWZjYjZhYWUtMDUxMC00NDg4LWFmYzAtZjQ3MzUyNWRmMmY2O2E5Zjg3NTA3LTRjOWEtNDA1Mi04NzgxLTM5Y2QzMTk3NTk2YTsxMS8yMi8yMDIz'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            payload = response.json()
            records = payload.get('records', [])
            if records:
                data = pd.json_normalize(records)
                data['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')
                return data

            print('Sin registros de pagos')
            return pd.DataFrame()

        print(f"Respuesta inesperada {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for records: {e}")

    return pd.DataFrame()


def run():
    os.makedirs(CARPETA_BASE_RAW, exist_ok=True)
    data = get_payments()

    if data.empty:
        print('No se encontraron registros para guardar.')
        return

    fecha = datetime.now().strftime('%Y%m%d')
    ruta_archivo = os.path.join(CARPETA_BASE_RAW, f'pagos_raw_{fecha}.parquet')
    data.to_parquet(ruta_archivo, index=False, compression='snappy')
    print(f'Pagos guardados en {ruta_archivo}')


if __name__ == '__main__':
    run()

