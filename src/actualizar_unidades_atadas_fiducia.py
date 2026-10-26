"""
Segunda fuente de "unidades atadas" -- distinta y APARTE de actualizar_unidades_atadas.py (que
cruza contra estado_cuentas de Drive, solo disponible para 4 proyectos). Esta usa el historico
de tareas/tramites (getTasks, ver 4_no_escriturados__tareas_raw.py), especificamente el grupo
"LEGALIZACIÓN VINCULACIÓN FIDUCIA":

    - Si el cliente tiene un registro de "Rechazo de vinculacion por parte de la fiducia (si
      aplica)" (con fecha diligenciada), la unidad se considera atada.
    - Si ADEMAS tiene un registro de "Fecha Legalizacion Fiducia" (con fecha diligenciada), ya
      se resolvio/registro -- la unidad vuelve a estar apta para escrituracion, ya no cuenta
      como atada.
    - En cualquier caso, solo se analiza esto para apartamentos NO escriturados -- una unidad
      ya escriturada no se marca como atada, ya no hay nada que gestionar sobre ella.

Nota: una tarea sin fecha diligenciada en Smarthome no genera fila en la respuesta de getTasks
(se valido con datos reales) -- por eso basta con que la fila EXISTA para saber que si tiene
fecha, sin necesidad de revisar la fecha puntual.

Por ahora (2026-09) este dato solo esta diligenciado para Verdevivo, pero la logica no se
restringe a ese proyecto -- aplica a cualquier cliente que tenga estas 2 tareas en Smarthome.

Es un proceso APARTE del cruce con estado_cuentas: los dos se pueden correr en cualquier orden,
cada uno agrega sus propios hallazgos a 'unidades_atadas' con OR (union), sin pisar lo que ya
haya marcado el otro.
"""
import os
import unicodedata

import pandas as pd

from api_utils import RUTA_ANALYTICS, RUTA_RAW_NO_ESCRITURADOS, leer_ultimo_parquet


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return texto.lower().strip()


def _prospectos_con_tarea(df_tareas, patron_normalizado):
    """prospectId -> presentes en al menos una fila cuyo CompanyTask (normalizado, sin
    tildes/mayusculas) contiene `patron_normalizado`."""
    coincide = df_tareas['CompanyTask'].apply(_normalizar).str.contains(patron_normalizado, na=False)
    return set(df_tareas.loc[coincide, 'prospectId'].unique())


def run():
    ruta_csv = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    df = pd.read_csv(ruta_csv, encoding='utf-8-sig')

    try:
        tareas = leer_ultimo_parquet(RUTA_RAW_NO_ESCRITURADOS, "tareas_tramites")
    except FileNotFoundError as e:
        print(f"ADVERTENCIA: {e} No se pudo evaluar 'unidades_atadas' por fiducia; "
              "el archivo no se modifica.")
        return None

    con_rechazo = _prospectos_con_tarea(tareas, 'rechazo de vinculacion por parte de la fiducia')
    con_legalizacion = _prospectos_con_tarea(tareas, 'legalizacion fiducia')

    # Igual que en actualizar_unidades_atadas.py: solo se analiza esto para apartamentos NO
    # escriturados -- una unidad ya escriturada no se marca como "atada" aunque tenga un
    # rechazo de fiducia sin legalizar, porque a esas alturas ya no hay nada que gestionar.
    no_escriturada = df['escriturado'] == 0
    atada_por_fiducia = (
        df['id_prospecto'].isin(con_rechazo) & ~df['id_prospecto'].isin(con_legalizacion) & no_escriturada
    )

    if 'unidades_atadas' not in df.columns:
        df['unidades_atadas'] = 0
    anterior = df['unidades_atadas'].fillna(0).astype(int)
    df['unidades_atadas'] = (anterior | atada_por_fiducia.astype(int)).astype(int)

    df.to_csv(ruta_csv, index=False, encoding='utf-8-sig')

    total_fiducia = int(atada_por_fiducia.sum())
    nuevas = int((atada_por_fiducia & (anterior == 0)).sum())
    print(f"'unidades_atadas' (fuente: fiducia) actualizado en {ruta_csv}: "
          f"{total_fiducia} unidades atadas por rechazo de fiducia sin legalizar "
          f"({nuevas} nuevas que actualizar_unidades_atadas.py no habia marcado), "
          f"de {len(df)} clientes totales.")
    if total_fiducia:
        print("Por proyecto:")
        print(df.loc[atada_por_fiducia, 'proyecto'].value_counts().to_string())
    return ruta_csv


if __name__ == "__main__":
    run()
