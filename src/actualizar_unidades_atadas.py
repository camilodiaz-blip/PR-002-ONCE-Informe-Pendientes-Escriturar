"""
Agrega/actualiza la columna 'unidades_atadas' en data/analytics/clientes_detallado.csv.

Logica: para cada cliente, se cruza su proyecto+modulo contra el archivo de estado de
cuentas (data/raw/estado_cuentas, cargado desde Drive por cargue_estado_cuentas_raw.py) y
se compara la identificacion registrada en cada lado para esa MISMA unidad.

    0 = la identificacion coincide, o no hay con que comparar todavia (el proyecto no esta
        cubierto aun en estado_cuentas, o el cliente no tiene identificacion registrada) --
        no se marca problema sin evidencia.
    1 = SI hay dato de estado_cuentas para esa unidad, pero la identificacion no coincide --
        se interpreta como que la unidad esta "atada" (para revisar).

Se cruza por proyecto+modulo (no por identificacion): primero se ubica la unidad, despues
se valida si las identificaciones coinciden.
"""
import os

import pandas as pd

from api_utils import RUTA_ANALYTICS, RUTA_RAW_ESTADO_CUENTAS, leer_ultimo_parquet


def _clave(proyecto, modulo):
    return proyecto.astype(str).str.strip().str.lower() + '||' + modulo.astype(str).str.strip().str.lower()


def run():
    ruta_csv = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    df = pd.read_csv(ruta_csv, encoding='utf-8-sig')

    try:
        estado_cuentas = leer_ultimo_parquet(RUTA_RAW_ESTADO_CUENTAS, "estado_cuentas")
    except FileNotFoundError as e:
        print(f"ADVERTENCIA: {e} No se pudo calcular 'unidades_atadas'; queda en 0 para todos.")
        df['unidades_atadas'] = 0
        df.to_csv(ruta_csv, index=False, encoding='utf-8-sig')
        return ruta_csv

    df['_clave'] = _clave(df['proyecto'], df['modulo'])
    estado_cuentas['_clave'] = _clave(estado_cuentas['Proyecto'], estado_cuentas['Unidad'])

    # Si la misma unidad aparece mas de una vez en estado_cuentas, nos quedamos con la
    # primera para no multiplicar filas al cruzar.
    estado_cuentas_unico = estado_cuentas.drop_duplicates(subset='_clave', keep='first')
    identificacion_estado_cuenta = (
        estado_cuentas_unico.set_index('_clave')['Identificacion'].astype(str).str.strip()
    )

    df['_identificacion_ec'] = df['_clave'].map(identificacion_estado_cuenta)
    df['_identificacion_propia'] = df['numero_identificacion'].astype(str).str.strip()

    hay_dato_estado_cuenta = df['_identificacion_ec'].notna()
    tiene_identificacion_propia = df['numero_identificacion'].notna()
    coincide = df['_identificacion_propia'] == df['_identificacion_ec']

    # 1 solo cuando de verdad hay algo con que comparar en ambos lados y no coincide.
    df['unidades_atadas'] = (
        hay_dato_estado_cuenta & tiene_identificacion_propia & (~coincide)
    ).astype(int)

    df = df.drop(columns=['_clave', '_identificacion_ec', '_identificacion_propia'])
    df.to_csv(ruta_csv, index=False, encoding='utf-8-sig')

    n_atadas = int(df['unidades_atadas'].sum())
    n_evaluadas = int((hay_dato_estado_cuenta & tiene_identificacion_propia).sum())
    print(f"'unidades_atadas' actualizado en {ruta_csv}: {n_atadas} unidades atadas de "
          f"{n_evaluadas} evaluadas (con dato en estado_cuentas), de {len(df)} clientes totales.")
    return ruta_csv


if __name__ == "__main__":
    run()
