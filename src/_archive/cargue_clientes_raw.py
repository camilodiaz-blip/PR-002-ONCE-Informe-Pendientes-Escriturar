from datetime import datetime
import os
import requests
import pandas as pd


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



for proyect, proyectid in proyects_id.items():
    print(f"iniciando para: {proyect} with ID: {proyectid}")
    url = f'https://api.smart-home.com.co/api/v1/getSales/10595/{proyectid}'

    try:
        response = requests.get(url)
        if response.status_code == 200:
            payload = response.json()  # Cargue de archivo JSON
            prospects = payload.get('prospects', [])
            if prospects:
                data = pd.json_normalize(prospects)

                #data['proyect'] = proyect
                # creacion de ID_fecha_cargue
                data['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')

                CARPETA_BASE_RAW = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    'data',
                    'raw',
                    'clientes',
                )
                os.makedirs(CARPETA_BASE_RAW, exist_ok=True)
                ruta_archivo = os.path.join(CARPETA_BASE_RAW, f"{proyect}.parquet")
                data.to_parquet(ruta_archivo, index=False, compression='snappy')
            else:
                print(f"Sin prospects para {proyect} (ID {proyectid})")
        else:
            print(f"Respuesta inesperada {response.status_code} para prospect {proyectid}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for prospect {proyectid}: {e}")

