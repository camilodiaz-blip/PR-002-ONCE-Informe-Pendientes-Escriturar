"""
Genera dos CSV pensados para adjuntar directamente a una IA (Claude, Gemini, etc.) y que
pueda responder preguntas sobre el detalle de la informacion sin necesidad de ejecutar codigo.
Se corre automaticamente al final de cada actualizacion del dashboard (ver 6_dashboard.py) --
no hace falta correrlo aparte, aunque tambien funciona solo (`python generar_detalle_ia.py`).

    - detalle_clientes.csv: una fila por cliente, con la categoria/subcategoria YA calculada
      (hoy y en el corte de comite del mes, ver data/referencia/cortes_comite.csv), para que
      la IA no tenga que re-derivar la logica de negocio (la matriz Credito x Subsidio, etc.).
    - cambios_vs_comite.csv: solo los clientes que CAMBIARON entre el corte de comite y hoy
      (categoria, escriturado, unidades atadas) -- el archivo mas directo para responder
      "a que corresponden los cambios" / "por que las diferencias" sin comparar dos tablas
      grandes a mano.

Ambos comparan contra el mismo corte de comite que ya usa el dashboard. Si el mes en curso
todavia no tiene fila en cortes_comite.csv (comite aun no definido), 'detalle_clientes.csv'
sale igual pero sin las columnas "_comite" (quedan vacias), y 'cambios_vs_comite.csv' sale
vacio -- no hay con que comparar todavia.
"""
import importlib
import os

import pandas as pd

from api_utils import RUTA_ANALYTICS, RUTA_HISTORICO, RUTA_DETALLE_IA

# 6_dashboard.py empieza con un digito, por eso se importa con importlib (igual que en main.py).
dash = importlib.import_module("6_dashboard")

COLUMNAS_CAMBIOS = [
    'id_prospecto', 'proyecto', 'modulo', 'cliente',
    'categoria_comite', 'categoria_hoy', 'escriturado_comite', 'escriturado_hoy',
    'unidades_atadas_comite', 'unidades_atadas_hoy', 'tipo_cambio',
]


def _categoria_subcategoria(row):
    categoria, _color_cat, subcategoria, _color_sub = dash._clasificar_tramites(row)
    return categoria, subcategoria


def _cargar_snapshot_comite(fecha_corte_comite):
    """Snapshot completo de clientes guardado el dia del comite (ver
    5_no_escriturados_staging.py), o None si no hay corte de comite definido o se perdio el
    snapshot de ese dia."""
    if not fecha_corte_comite:
        return None
    ruta = os.path.join(RUTA_HISTORICO, f"clientes_detallado_{fecha_corte_comite.replace('-', '')}.parquet")
    if not os.path.exists(ruta):
        return None
    df_comite = pd.read_parquet(ruta)
    if 'unidades_atadas' not in df_comite.columns:
        # Fotos guardadas antes de que main.py copiara las atadas al historico: sin dato.
        print(f"ADVERTENCIA: la foto del comite ({fecha_corte_comite}) no tiene 'unidades_atadas'; "
              "los cambios de 'Unidad atada' contra ese comite no son confiables.")
        df_comite['unidades_atadas'] = 0
    return df_comite


def _tipo_cambio(row):
    if pd.isna(row['categoria_comite']):
        return 'Nuevo (no estaba en el corte de comite)'
    partes = []
    if row['escriturado_comite'] != row['escriturado_hoy']:
        partes.append('Se escrituro')
    if row['categoria_comite'] != row['categoria_hoy']:
        partes.append(f"Categoria: {row['categoria_comite']} -> {row['categoria_hoy']}")
    if row['unidades_atadas_comite'] != row['unidades_atadas_hoy']:
        partes.append('Unidad atada' if row['unidades_atadas_hoy'] == 1 else 'Ya no esta atada')
    return '; '.join(partes) if partes else 'Sin cambio detectado'


def run():
    os.makedirs(RUTA_DETALLE_IA, exist_ok=True)

    df_hoy = pd.read_csv(os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv"), encoding='utf-8-sig')
    fecha_corte = df_hoy['fecha_corte'].iloc[0] if 'fecha_corte' in df_hoy.columns and len(df_hoy) else None
    fecha_corte_comite = dash._fecha_corte_comite(fecha_corte) if fecha_corte else None
    df_comite = _cargar_snapshot_comite(fecha_corte_comite)

    # --- detalle_clientes.csv ---
    categoria_hoy = df_hoy.apply(_categoria_subcategoria, axis=1, result_type='expand')
    categoria_hoy.columns = ['categoria_hoy', 'subcategoria_hoy']
    detalle = pd.concat([
        df_hoy[['id_prospecto', 'proyecto', 'modulo', 'nombre', 'apellido', 'numero_identificacion',
                'asesor', 'escriturado', 'escritura_programada_anio', 'unidades_atadas']],
        categoria_hoy,
    ], axis=1)
    detalle['cliente'] = (
        detalle['nombre'].fillna('').str.strip() + ' ' + detalle['apellido'].fillna('').str.strip()
    ).str.strip()
    detalle = detalle.drop(columns=['nombre', 'apellido']).rename(columns={
        'escriturado': 'escriturado_hoy', 'unidades_atadas': 'unidades_atadas_hoy',
    })

    if df_comite is not None:
        categoria_comite = df_comite.apply(_categoria_subcategoria, axis=1, result_type='expand')
        categoria_comite.columns = ['categoria_comite', 'subcategoria_comite']
        comite_cols = pd.concat([
            df_comite[['id_prospecto', 'escriturado', 'unidades_atadas']].rename(columns={
                'escriturado': 'escriturado_comite', 'unidades_atadas': 'unidades_atadas_comite',
            }),
            categoria_comite,
        ], axis=1)
        detalle = detalle.merge(comite_cols, on='id_prospecto', how='left')
    else:
        for col in ['categoria_comite', 'subcategoria_comite', 'escriturado_comite', 'unidades_atadas_comite']:
            detalle[col] = pd.NA

    detalle['fecha_corte'] = fecha_corte
    detalle['fecha_corte_comite'] = fecha_corte_comite

    ruta_detalle = os.path.join(RUTA_DETALLE_IA, "detalle_clientes.csv")
    detalle.to_csv(ruta_detalle, index=False, encoding='utf-8-sig')
    print(f"Detalle para IA generado en {ruta_detalle} ({len(detalle)} clientes)")

    # --- cambios_vs_comite.csv ---
    if df_comite is None:
        cambios = pd.DataFrame(columns=COLUMNAS_CAMBIOS)
    else:
        cambio_categoria = detalle['categoria_comite'] != detalle['categoria_hoy']
        cambio_escritura = detalle['escriturado_comite'] != detalle['escriturado_hoy']
        cambio_atadas = detalle['unidades_atadas_comite'] != detalle['unidades_atadas_hoy']
        nuevo = detalle['categoria_comite'].isna()  # no estaba en el snapshot de comite
        cambios = detalle[cambio_categoria | cambio_escritura | cambio_atadas | nuevo].copy()
        cambios['tipo_cambio'] = cambios.apply(_tipo_cambio, axis=1)
        cambios = cambios[COLUMNAS_CAMBIOS]

    ruta_cambios = os.path.join(RUTA_DETALLE_IA, "cambios_vs_comite.csv")
    cambios.to_csv(ruta_cambios, index=False, encoding='utf-8-sig')
    print(f"Cambios vs. comite generado en {ruta_cambios} ({len(cambios)} clientes con cambios)")

    if fecha_corte_comite and df_comite is None:
        print(f"ADVERTENCIA: no se encontro el snapshot de clientes del corte de comite "
              f"({fecha_corte_comite}) en {RUTA_HISTORICO} -- 'cambios_vs_comite.csv' sale "
              f"vacio y las columnas '*_comite' de 'detalle_clientes.csv' quedan sin dato.")
    return ruta_detalle, ruta_cambios


if __name__ == "__main__":
    run()
