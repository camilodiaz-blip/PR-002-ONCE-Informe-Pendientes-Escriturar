import os

import pandas as pd

from api_utils import RUTA_RAW_CONVERSACIONES, RUTA_STAGING, leer_ultimo_parquet
import analisis_conversaciones as analisis

MAX_EVENTOS_POR_CATEGORIA = 5


def run():
    # El raw de conversaciones queda versionado por fecha (eventos_YYYYMMDD.parquet, ver
    # cargue_conversaciones_raw.py) -- aca solo se usa la version mas reciente, no se concatenan
    # todas las corridas, porque un mismo cliente puede volver a aparecer en varias corridas
    # (mientras siga en categoria "Sin Cartas") y eso duplicaria sus eventos.
    df = leer_ultimo_parquet(RUTA_RAW_CONVERSACIONES, "eventos")

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    # ~0.3% de los `date` no convierten (formato invalido) -- se descartan antes de elegir los
    # mas recientes, no se pueden ordenar ni deberian "ganarle" el cupo a un evento con fecha real.
    df = df[df['date'].notna()]

    # Se clasifica aca (reutilizando la misma logica de analisis_conversaciones.py) para poder
    # quedarse con los MAX_EVENTOS_POR_CATEGORIA mas recientes de CADA naturaleza (GESTION_SISTEMA
    # / INTERACCION / DESCONOCIDO) por cliente, en vez de los N mas recientes en total sin
    # distincion. Con un solo tope total, un cliente con mucha actividad reciente de un solo tipo
    # (ej. varias cargas de documentos seguidas) se quedaba sin NINGUN evento de la otra categoria
    # en el staging, aunque si tuviera uno mas atras en su historial completo -- eso es justamente
    # lo que causaba los vacios en 'ultimo_seguimiento'/'ultima_gestion_sistema' del analisis.
    df_clasificado = analisis._clasificar_eventos(df)

    df_reciente = (
        df_clasificado.sort_values('date', ascending=False)
        .groupby(['prospectId', 'naturaleza'], group_keys=False)
        .head(MAX_EVENTOS_POR_CATEGORIA)
    )
    # El staging solo guarda las columnas originales del raw -- las columnas de clasificacion
    # (tipo_interaccion, canal, naturaleza, direccion) las vuelve a calcular
    # analisis_conversaciones.py sobre la ventana ya filtrada; no hace falta persistirlas aca.
    df_reciente = df_reciente[df.columns]

    os.makedirs(RUTA_STAGING, exist_ok=True)
    ruta_archivo = os.path.join(RUTA_STAGING, "conversaciones.parquet")
    df_reciente.to_parquet(ruta_archivo, index=False, compression='snappy')
    print(
        f"Staging de conversaciones actualizado en {ruta_archivo} "
        f"({len(df_reciente)} de {len(df)} eventos, hasta {MAX_EVENTOS_POR_CATEGORIA} "
        "por cliente y categoria)"
    )
    return ruta_archivo


if __name__ == "__main__":
    run()
