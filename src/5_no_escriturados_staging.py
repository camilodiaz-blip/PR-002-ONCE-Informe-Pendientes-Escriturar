import os
from datetime import datetime

import pandas as pd

from api_utils import (
    cargar_clientes_staging, ANIO_OBJETIVO_ESCRITURA,
    RUTA_RAW_NO_ESCRITURADOS, RUTA_RAW_PAGOS, RUTA_ANALYTICS, RUTA_HISTORICO,
    leer_ultimo_parquet, leer_parquet_mas_antigua, guardar_parquet_versionado,
)

def _fecha_por_tarea(df_tareas, nombre_tarea):
    """
    Fecha (por prospectId) de la primera tarea que coincida con `nombre_tarea` en df_tareas.
    Toma endDate, si no hay usa startDate, si no hay usa scheduleDate (el primero diligenciado).
    Si `nombre_tarea` no aparece en df_tareas, avisa (en vez de fallar en silencio con todo en 0),
    porque el nombre debe coincidir EXACTO (tildes, mayusculas, typos) con el que entrega Smarthome.
    """
    subset = df_tareas[df_tareas['CompanyTask'] == nombre_tarea]
    if subset.empty:
        print(f"ADVERTENCIA: ninguna tarea coincide con CompanyTask == '{nombre_tarea}'. "
              "Verifica el nombre exacto en Smarthome; esta columna quedara vacia para todos los clientes.")
        return pd.Series(dtype='object')

    subset = subset.copy()
    for col in ('endDate', 'startDate', 'scheduleDate'):
        if col not in subset.columns:
            subset[col] = pd.NA
    subset['fecha'] = subset['endDate'].fillna(subset['startDate']).fillna(subset['scheduleDate'])
    subset['prospectId_limpio'] = subset['prospectId'].astype(str).str.strip().str.lower()
    subset = subset.dropna(subset=['fecha']).drop_duplicates(subset=['prospectId_limpio'], keep='first')
    return subset.set_index('prospectId_limpio')['fecha']


def run():
    df = cargar_clientes_staging()

    # Cargue de archivos de los detalles.
    # Los pagos se toman de la carpeta de pagos raw y se lee la version mas antigua.
    df_pagos = leer_parquet_mas_antigua(RUTA_RAW_PAGOS, "pagos_raw")
    df_tareas = leer_ultimo_parquet(RUTA_RAW_NO_ESCRITURADOS, "tareas_tramites")

    #Creacion de Columna de programcion escritura
    df['escritura_programada_anio']= pd.to_datetime(df['fecha_escritura_programada']).dt.year
    df['escritura_programada_mes']= pd.to_datetime(df['fecha_escritura_programada']).dt.month

    # Solo para estos clientes se consultaron pagos y tareas (scripts 3 y 4).
    # Para el resto, subsidio/credito/aprobado/radicado quedan en 0 pero NO significa "no requiere":
    # significa que no se evaluo, porque no estan en el alcance de escritura del anio objetivo.
    df['en_alcance_no_escriturado'] = (
        (df['escriturado'] == 0) & (df['escritura_programada_anio'] == ANIO_OBJETIVO_ESCRITURA)
    ).astype(int)

    #Normalizamos temporalmente la columna del DataFrame principal para comparar con Pagos
    df_id_limpio = df['id_prospecto'].astype(str).str.strip().str.lower()

    # El nuevo archivo de pagos no trae prospectId; usamos Project + Module como clave de unión.
    pagos_con_clave = df_pagos.copy()
    pagos_con_clave['Project_limpio'] = pagos_con_clave['Project'].astype(str).str.strip().str.lower()
    pagos_con_clave['Module_limpio'] = pagos_con_clave['Module'].astype(str).str.strip().str.lower()

    df['proyecto_limpio'] = df['proyecto'].astype(str).str.strip().str.lower()
    df['modulo_limpio'] = df['modulo'].astype(str).str.strip().str.lower()

    # Validacion si el cliente requiere subsidio
    clientes_con_subsidio = (
        pagos_con_clave[pagos_con_clave['PaymentType'] == 2]
        .groupby(['Project_limpio', 'Module_limpio'])
        .size()
        .index
    )
    df['subsidio'] = (
        df[['proyecto_limpio', 'modulo_limpio']]
        .apply(lambda row: tuple(row) in clientes_con_subsidio, axis=1)
        .astype(int)
    )

    # Validacion si el cliente requiere credito
    clientes_con_credito = (
        pagos_con_clave[pagos_con_clave['PaymentType'] == 5]
        .groupby(['Project_limpio', 'Module_limpio'])
        .size()
        .index
    )
    df['credito'] = (
        df[['proyecto_limpio', 'modulo_limpio']]
        .apply(lambda row: tuple(row) in clientes_con_credito, axis=1)
        .astype(int)
    )

    # Indicador binario: 1 si la suma de Amount de las cuotas 01 a 06 (Type=1, PaymentType=1)
    # es menor que la suma de Amount de los pagos (Type=2, PaymentType=1), y 0 en caso contrario.
    cuotas_6 = pagos_con_clave[
        (pagos_con_clave['Type'] == 1)
        & (pagos_con_clave['PaymentType'] == 1)
        & (pagos_con_clave['Title'].astype(str).str.strip().isin([
            'Cuota 01', 'Cuota 02', 'Cuota 03', 'Cuota 04', 'Cuota 05', 'Cuota 06'
        ]))
    ]
    pagos_tipo2_paymenttype1 = pagos_con_clave[
        (pagos_con_clave['Type'] == 2) & (pagos_con_clave['PaymentType'] == 1)
    ]

    suma_cuotas = (
        cuotas_6.groupby(['Project_limpio', 'Module_limpio'])['Amount']
        .sum()
        .reset_index(name='suma_cuotas')
    )
    suma_pagos = (
        pagos_tipo2_paymenttype1.groupby(['Project_limpio', 'Module_limpio'])['Amount']
        .sum()
        .reset_index(name='suma_pagos')
    )

    resumen = suma_cuotas.merge(suma_pagos, on=['Project_limpio', 'Module_limpio'], how='outer')
    resumen['suma_cuotas'] = resumen['suma_cuotas'].fillna(0)
    resumen['suma_pagos'] = resumen['suma_pagos'].fillna(0)
    resumen['pago_6_cuotas'] = (resumen['suma_cuotas'] < resumen['suma_pagos']).astype(int)

    resumen = resumen.rename(columns={'Project_limpio': 'proyecto_limpio', 'Module_limpio': 'modulo_limpio'})
    df = df.merge(
        resumen[['proyecto_limpio', 'modulo_limpio', 'pago_6_cuotas']],
        on=['proyecto_limpio', 'modulo_limpio'],
        how='left'
    )
    df['pago_6_cuotas'] = df['pago_6_cuotas'].fillna(0).astype(int)
    df = df.drop(columns=['proyecto_limpio', 'modulo_limpio'])

    #validacion si el subsidio tiene fecha de aprobacion
    df['fecha_subsidio_aprobado'] = df_id_limpio.map(_fecha_por_tarea(df_tareas, 'Aprobación del subisidio'))
    df['subsidio_aprobado'] = df['fecha_subsidio_aprobado'].notna().astype(int)

    #validacion si el subsidio tiene fecha de radicado
    df['fecha_subsidio_radicado'] = df_id_limpio.map(_fecha_por_tarea(df_tareas, 'Radicacion subsidio'))
    df['subsidio_radicado'] = df['fecha_subsidio_radicado'].notna().astype(int)

    #validacion si el credito tiene fecha de aprobacion
    df['fecha_credito_aprobado'] = df_id_limpio.map(_fecha_por_tarea(df_tareas, 'Fecha Aprobacion'))
    df['credito_aprobado'] = df['fecha_credito_aprobado'].notna().astype(int)

    #validacion si el credito tiene fecha de radicacion
    df['fecha_credito_radicado'] = df_id_limpio.map(_fecha_por_tarea(df_tareas, 'Radicacion documentos en banco'))
    df['credito_radicado'] = df['fecha_credito_radicado'].notna().astype(int)

    # credito_radicado queda pendiente: ese campo/tarea aun no existe en Smarthome (confirmado con negocio).

    df['fecha_corte'] = datetime.now().strftime('%Y-%m-%d')

    # "Foto" actual para negocio: siempre el mismo nombre, se sobreescribe cada corrida.
    os.makedirs(RUTA_ANALYTICS, exist_ok=True)
    ruta_archivo = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    # utf-8-sig para que Excel en Windows muestre bien tildes/ñ (nombre, apellido, etc.)
    df.to_csv(ruta_archivo, index=False, encoding='utf-8-sig')

    # Historico: una version nueva por corrida (nunca se sobreescribe), para comparar la
    # evolucion de los tramites de un cliente/apartamento entre una corrida y otra.
    ruta_historico = guardar_parquet_versionado(df, RUTA_HISTORICO, "clientes_detallado")
    print(f"Historico guardado en {ruta_historico}")

    print(df)


if __name__ == "__main__":
    run()

