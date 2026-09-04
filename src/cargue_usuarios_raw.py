"""
Cargue de usuarios (asesores) desde la API de Smarthome.

A diferencia de la version anterior (que llamaba getUsers/10595/, un solo listado masivo),
este script consulta getUser/10595/{userId} UNO POR UNO -- porque getUsers solo trae usuarios
ACTIVOS (53 en la ultima corrida), mientras que 'asesor' en clientes_detallado.csv tiene 64
UUID de asesores que ya no aparecen ahi (probablemente ex-empleados). getUser si puede
resolver esos, consultando directamente por su id.

Los UUID a consultar se sacan de clientes_detallado.csv: son los valores de la columna
'asesor' que TODAVIA se ven como UUID crudo (5_no_escriturados_staging.py deja el UUID sin
resolver cuando no encuentra coincidencia -- ver _nombre_asesor en ese script).

El resultado es un archivo HISTORICO acumulativo: cada corrida solo consulta los UUID que
faltan por resolver y los agrega a lo que ya se tenia (sin duplicar por userId), en vez de
reemplazar el archivo completo -- asi nunca se pierde un usuario ya resuelto en una corrida
anterior, aunque ese ex-empleado ya no aparezca en ningun lado de la API.
"""
import os
import re

import pandas as pd
import requests

from api_utils import (
    get_session, fetch_in_parallel, MAX_WORKERS, REQUEST_TIMEOUT,
    RUTA_ANALYTICS, RUTA_RAW_USUARIOS, guardar_parquet_versionado, leer_ultimo_parquet,
)

_RE_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def get_user(user_id):
    url = f'https://api.smart-home.com.co/api/v1/getUser/10595/{user_id}'
    session = get_session()
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"Respuesta inesperada {response.status_code} para usuario {user_id}")
            return pd.DataFrame()

        payload = response.json()
        # La respuesta real viene envuelta en {"users": [ {...un solo usuario...} ], ...}.
        # Se maneja tambien objeto/lista sueltos por si el endpoint cambia de forma.
        if isinstance(payload, dict) and 'users' in payload:
            payload = payload['users']
        if isinstance(payload, list):
            payload = payload[0] if payload else None

        if not payload:
            print(f"Sin datos para el usuario {user_id}")
            return pd.DataFrame()

        df = pd.json_normalize(payload)
        if 'userId' not in df.columns:
            df['userId'] = user_id
        return df

    except requests.exceptions.RequestException as e:
        print(f"Error consultando usuario {user_id}: {e}")
        return pd.DataFrame()


def _uuids_por_resolver():
    """
    UUID de asesor en clientes_detallado.csv que todavia no se resolvieron a un nombre. La
    columna 'asesor' queda con el UUID crudo (formato UUID) cuando 5_no_escriturados_staging.py
    no encontro coincidencia -- los que si se resolvieron ya son un nombre, no un UUID.
    """
    ruta_csv = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    df = pd.read_csv(ruta_csv, encoding='utf-8-sig')
    valores = df['asesor'].dropna().astype(str).unique()
    return sorted({v for v in valores if _RE_UUID.match(v)})


def run():
    uuids = _uuids_por_resolver()
    if not uuids:
        print("No hay UUID de asesor pendientes por resolver -- nada que consultar.")
        return None

    print(f"Consultando {len(uuids)} usuarios sin resolver en clientes_detallado.csv...")
    nuevos_list = fetch_in_parallel(uuids, get_user, max_workers=MAX_WORKERS, label="Usuario")
    nuevos = pd.concat(nuevos_list, ignore_index=True) if nuevos_list else pd.DataFrame()

    if nuevos.empty:
        print("Ningun usuario nuevo se pudo resolver en esta corrida (quedan como estaban).")
        return None

    # Historico acumulativo: se une con lo que ya se tenia (si existe una corrida anterior),
    # sin duplicar por userId -- si el mismo usuario se vuelve a resolver, el dato nuevo pisa
    # al viejo (keep='last').
    try:
        existente = leer_ultimo_parquet(RUTA_RAW_USUARIOS, "usuarios")
    except FileNotFoundError:
        existente = pd.DataFrame()

    combinado = pd.concat([existente, nuevos], ignore_index=True).drop_duplicates(
        subset='userId', keep='last'
    )

    ruta_archivo = guardar_parquet_versionado(combinado, RUTA_RAW_USUARIOS, "usuarios")
    print(f"Usuarios actualizados en {ruta_archivo} "
          f"({len(nuevos)} resueltos en esta corrida, {len(combinado)} en el historico total)")
    return ruta_archivo


if __name__ == "__main__":
    run()
