import os

import pandas as pd

from api_utils import RUTA_RAW_CONVERSACIONES, RUTA_STAGING, leer_ultimo_parquet

MAX_EVENTOS_POR_CLIENTE = 15


def run():
    # El raw de conversaciones queda versionado por fecha (eventos_YYYYMMDD.parquet, ver
    # cargue_conversaciones_raw.py) -- aca solo se usa la version mas reciente, no se concatenan
    # todas las corridas, porque un mismo cliente puede volver a aparecer en varias corridas
    # (mientras siga en categoria "Sin Radicados" o "Pdt un Radicado") y eso duplicaria sus eventos.
    df = leer_ultimo_parquet(RUTA_RAW_CONVERSACIONES, "eventos")

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    # ~0.3% de los `date` no convierten (formato invalido) -- se descartan antes de elegir los
    # mas recientes, no se pueden ordenar ni deberian "ganarle" el cupo a un evento con fecha real.
    df = df[df['date'].notna()]

    # Los MAX_EVENTOS_POR_CLIENTE mas recientes de cada cliente, sin distinguir de que tipo son
    # (no se clasifica en este paso -- la clasificacion la hace analisis_conversaciones.py sobre
    # esta misma ventana ya filtrada).
    df_reciente = (
        df.sort_values('date', ascending=False)
        .groupby('prospectId', group_keys=False)
        .head(MAX_EVENTOS_POR_CLIENTE)
    )

    os.makedirs(RUTA_STAGING, exist_ok=True)
    ruta_archivo = os.path.join(RUTA_STAGING, "conversaciones.parquet")
    df_reciente.to_parquet(ruta_archivo, index=False, compression='snappy')
    print(
        f"Staging de conversaciones actualizado en {ruta_archivo} "
        f"({len(df_reciente)} de {len(df)} eventos, hasta {MAX_EVENTOS_POR_CLIENTE} "
        "por cliente)"
    )
    return ruta_archivo


if __name__ == "__main__":
    run()
