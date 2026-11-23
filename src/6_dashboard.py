import json
import os
from collections import defaultdict
from datetime import datetime
from glob import glob

import pandas as pd
import plotly.graph_objects as go

from api_utils import RUTA_ANALYTICS, RUTA_REPORTES, RUTA_HISTORICO, RUTA_REFERENCIA, ANIO_OBJETIVO_ESCRITURA

# --- Paleta base: un color con nombre por cada significado, usado en todo el archivo. ---
# Cambiar un color de verdad es cambiar UNA sola linea aca; todo lo demas abajo son mapas
# de "etiqueta -> color de esta paleta", no colores nuevos.
COLOR_VERDE = '#2E8B45'           # bien / listo
COLOR_VERDE_OSCURO = '#1B5E20'    # texto y acentos (titulos, encabezados)
COLOR_PENDIENTE = '#E8A33D'       # ambar -- radicado, pendiente de aprobar
COLOR_ROJO = '#C62828'            # mal -- sin ningun radicado
COLOR_MORADO = '#6A1B9A'          # subsidio no radicado + credito radicado
COLOR_AZUL = '#1f77b4'            # subsidio radicado + credito no radicado
COLOR_GRIS = '#C3C2B7'            # gris neutro; subsidio radicado + credito radicado
COLOR_CARBON = '#2C2C2A'         # sin uso actual (queda disponible en la paleta)
COLOR_ROJO_CLARO = "#E68989"     # categoria principal 'Pdt un Radicado'
COLOR_MORADO_CLARO = "#BA90C5"   # subsidio no radicado + credito aprobado
COLOR_AZUL_CLARO = "#80a4be"     # subsidio aprobado + credito no radicado
COLOR_AMARILLO_CLARO = "#ECBF7A"  # subsidio aprobado + credito radicado
COLOR_NARANJA_CLARO = "#ffdbbb"   # subsidio radicado + credito aprobado
COLOR_FUERA_REPORTE = "#9E9E9E"   # "Corte anterior - Estado actual": ya no esta en clientes_detallado.csv

TODOS = 'Todos'


def _fecha_corte_comite(fecha_corte):
    """
    Fecha del corte que se presento en el comite del MES de `fecha_corte` (ver
    data/referencia/cortes_comite.csv: una fila por mes, 'anio_mes' -> 'fecha_corte_comite').
    El comparativo COMITE del dashboard compara contra esta fecha en vez de "el primer corte
    del mes" -- el comite no siempre cae el dia 1, y puede cambiar de fecha de un mes a otro.

    data/referencia/cortes_comite.csv lo mantiene el equipo de negocio a mano (igual que
    clientes_desistidos.csv), sin tocar codigo: una fila nueva por mes, apenas se sepa que
    corte se presenta. Si el mes de `fecha_corte` todavia no tiene fila ahi (comite de este
    mes aun no definido/corrido), retorna None y el comparativo comite cae al automatico
    (primer corte del mes, o del mes anterior si no hay ninguno -- ver JS:
    fechaCorteAnteriorSegunVista), para no bloquear el informe mientras tanto.
    """
    ruta = os.path.join(RUTA_REFERENCIA, "cortes_comite.csv")
    if not os.path.exists(ruta):
        return None
    cortes = pd.read_csv(ruta, encoding='utf-8-sig', dtype=str)
    fila = cortes[cortes['anio_mes'] == fecha_corte[:7]]
    if fila.empty:
        return None
    fecha_comite = fila.iloc[0]['fecha_corte_comite'].strip()

    # El informe del DIA del comite (o uno corrido antes de esa fecha dentro del mismo mes) no
    # puede compararse contra si mismo: se compara contra el comite anterior mas reciente
    # (ej. el informe del comite de noviembre, 2026-11-03, compara contra el de octubre, 2026-10-14).
    if fecha_comite >= fecha_corte:
        anteriores = sorted(f.strip() for f in cortes['fecha_corte_comite'].dropna() if f.strip() < fecha_corte)
        return anteriores[-1] if anteriores else None
    return fecha_comite

# --- Matriz de categorizacion (Credito x Subsidio) ---
# Reemplaza el esquema anterior de "Listos/En Gestión/Sin Cartas" + subcategoria por unidad
# atada. Cada tramite (credito y subsidio) tiene 3 estados posibles:
#   NR = no radicado, R = radicado (pendiente de aprobar), A = aprobado o no se requiere (lo
#   que no se requiere cuenta como ya resuelto, igual que en el esquema anterior).
# La combinacion (estado_credito, estado_subsidio) determina la categoria principal + color,
# y -- salvo en los dos extremos "Sin Radicados" y "Listo" -- una subcategoria de detalle +
# color. 'unidades_atadas' ya NO hace parte de esta clasificacion: pasa a ser un filtro
# independiente, aparte de la categoria (ver JS: filtroAtadas).
MATRIZ_CATEGORIA = {
    ('NR', 'NR'): ('Sin Radicados', COLOR_ROJO, None, None),
    ('R', 'NR'): ('Pdt un Radicado', COLOR_ROJO_CLARO, 'Subsidio (No radicado)-Credito (radicado)', COLOR_MORADO),
    ('A', 'NR'): ('Pdt un Radicado', COLOR_ROJO_CLARO, 'Subsidio (No radicado)-Credito (aprobado)', COLOR_MORADO_CLARO),
    ('NR', 'R'): ('Pdt un Radicado', COLOR_ROJO_CLARO, 'Subsidio (radicado)-Credito (No radicado)', COLOR_AZUL),
    ('R', 'R'): ('Radicados', COLOR_PENDIENTE, 'Subsidio (radicado)-Credito (radicado)', COLOR_GRIS),
    ('A', 'R'): ('Radicados', COLOR_PENDIENTE, 'Subsidio (radicado)-Credito (aprobado)', COLOR_NARANJA_CLARO),
    ('NR', 'A'): ('Pdt un Radicado', COLOR_ROJO_CLARO, 'Subsidio (aprobado)-Credito (No radicado)', COLOR_AZUL_CLARO),
    ('R', 'A'): ('Radicados', COLOR_PENDIENTE, 'Subsidio (aprobado)-Credito (radicado)', COLOR_AMARILLO_CLARO),
    ('A', 'A'): ('Listo', COLOR_VERDE, None, None),
}

# Orden de apilado para "Clientes por categoría y mes proyectado": PRIMERO en la lista =
# base/abajo de la barra, ULTIMO = arriba. Pedido: Sin Radicados arriba del todo, despues Pdt
# un Radicado, despues Radicados, y Listo abajo del todo. 'Escrituradas' va en la base (debajo
# de 'Listo'): es el estado mas avanzado de todos, ya no hay nada que gestionar.
ORDEN_CATEGORIA_PRINCIPAL = ['Escrituradas', 'Listo', 'Radicados', 'Pdt un Radicado', 'Sin Radicados']
COLOR_ESCRITURADAS = '#000000'
COLORES_CATEGORIA_PRINCIPAL = {cat: color for (cat, color, _, _) in MATRIZ_CATEGORIA.values()}
COLORES_CATEGORIA_PRINCIPAL['Escrituradas'] = COLOR_ESCRITURADAS

# Orden de apilado del detalle (todo lo que no es 'Sin Radicados' ni 'Listo'), de la
# combinacion mas atrasada a la mas avanzada.
ORDEN_SUBCATEGORIA_GESTION = [
    'Subsidio (No radicado)-Credito (radicado)',
    'Subsidio (No radicado)-Credito (aprobado)',
    'Subsidio (radicado)-Credito (No radicado)',
    'Subsidio (radicado)-Credito (radicado)',
    'Subsidio (radicado)-Credito (aprobado)',
    'Subsidio (aprobado)-Credito (No radicado)',
    'Subsidio (aprobado)-Credito (radicado)',
]
COLORES_SUBCATEGORIA_GESTION = {sub: color_sub for (_, _, sub, color_sub) in MATRIZ_CATEGORIA.values() if sub}

# Colores para los badges de la tabla de "Clientes pendientes de aprobación": subcategorias +
# 'Sin Radicados' (todavia no tienen ni una radicacion) + 'Listo' (por si acaso, aunque no
# deberia aparecer un cliente "Listo" en la tabla de pendientes).
COLORES_CATEGORIA_TABLA = {**COLORES_SUBCATEGORIA_GESTION, 'Sin Radicados': COLOR_ROJO, 'Listo': COLOR_VERDE}

ETAPAS_SUBSIDIO = ['Vendidos', 'No escriturados', 'Requieren subsidio', 'Subsidio sin aprobar', 'Subsidio sin radicar']
ETAPAS_CREDITO = ['Vendidos', 'No escriturados', 'Requieren crédito', 'Crédito sin aprobar', 'Crédito sin radicar']

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


SIN_TORRE = 'Sin torre'


def _torre_o_default(valor):
    """El bucket 'Sin torre' agrupa casas y otros registros sin torre identificable (ver
    _extraer_torre en 2_cargue_clientes_staging.py) -- se usa un string fijo en vez de dejar
    NaN/None para que el filtro de torre en JS no tenga que manejar nulos aparte."""
    return valor if pd.notna(valor) else SIN_TORRE


def _torres_por_proyecto(df):
    """proyecto -> lista de torres presentes (orden numerico, 'Sin torre' al final si aplica).
    Alimenta el filtro de torre del dashboard, que depende de que proyectos esten marcados."""
    resultado = {}
    for proyecto, grupo in df.groupby('proyecto'):
        torres = sorted(grupo['torre'].dropna().unique().tolist(), key=lambda t: int(t.split()[1]))
        if grupo['torre'].isna().any():
            torres.append(SIN_TORRE)
        resultado[proyecto] = torres
    return resultado


def _tabla_clientes_funnel(df):
    """
    Una fila por cliente (TODOS, escriturados o no -- 'Vendidos' en el embudo cuenta a todos)
    con los campos crudos que necesita el embudo/KPI. Reemplaza el precalculo de 'datos' para
    la actualizacion en vivo del dashboard, porque ese precalculo es por proyecto+año y no
    puede filtrarse ademas por torre sin volver a agregar del lado del cliente (JS).
    """
    df = df.copy()
    # Año de la escritura REAL (no la programada) -- lo usa el KPI "Total Unidades
    # Escrituradas" para filtrar por el año seleccionado. Se calcula aca porque
    # 'fecha_escritura' llega como texto desde el CSV (pd.read_csv no infiere fechas solo).
    df['anio_escritura'] = pd.to_datetime(df['fecha_escritura'], errors='coerce').dt.year

    columnas = [
        'id_prospecto', 'proyecto', 'torre', 'escriturado', 'escritura_programada_anio', 'anio_escritura',
        'subsidio', 'subsidio_aprobado', 'subsidio_radicado',
        'credito', 'credito_aprobado', 'credito_radicado', 'unidades_atadas',
    ]
    registros = []
    for _, r in df[columnas].iterrows():
        anio_val = r['escritura_programada_anio']
        anio_escritura_val = r['anio_escritura']
        registros.append({
            'id_prospecto': r['id_prospecto'],
            'proyecto': r['proyecto'],
            'torre': _torre_o_default(r['torre']),
            'anio': None if pd.isna(anio_val) else str(int(anio_val)),
            'anio_escritura': None if pd.isna(anio_escritura_val) else str(int(anio_escritura_val)),
            'escriturado': int(r['escriturado']),
            'subsidio': int(r['subsidio']), 'subsidio_aprobado': int(r['subsidio_aprobado']),
            'subsidio_radicado': int(r['subsidio_radicado']),
            'credito': int(r['credito']), 'credito_aprobado': int(r['credito_aprobado']),
            'credito_radicado': int(r['credito_radicado']),
            'unidades_atadas': 0 if pd.isna(r['unidades_atadas']) else int(r['unidades_atadas']),
        })
    return registros


def _contar_escrituradas(df_proyecto, anio):
    """
    Unidades escrituradas (escriturado == 1) de `df_proyecto`, filtradas por el año de la
    escritura REAL (fecha_escritura), no por el año proyectado -- ese ultimo casi nunca esta
    diligenciado para unidades ya escrituradas (es un campo de proyeccion a futuro). Con
    anio == TODOS, cuenta todas las escrituradas sin importar el año.
    """
    escrituradas = df_proyecto[df_proyecto['escriturado'] == 1]
    if anio != TODOS:
        anio_escritura = pd.to_datetime(escrituradas['fecha_escritura'], errors='coerce').dt.year
        escrituradas = escrituradas[anio_escritura == float(anio)]
    return len(escrituradas)


def _calcular_metricas(df_proyecto, anio):
    """Métricas de los dos embudos para un subconjunto ya filtrado por proyecto y un año dado."""
    total_aptos = len(df_proyecto)
    n_escrituradas = _contar_escrituradas(df_proyecto, anio)

    no_escriturados = df_proyecto[df_proyecto['escriturado'] == 0]
    if anio != TODOS:
        no_escriturados = no_escriturados[no_escriturados['escritura_programada_anio'] == float(anio)]
    n_no_escriturados = len(no_escriturados)

    req_subsidio = no_escriturados[no_escriturados['subsidio'] == 1]
    n_req_subsidio = len(req_subsidio)
    subsidio_sin_aprobar = req_subsidio[req_subsidio['subsidio_aprobado'] == 0]
    n_subsidio_sin_aprobar = len(subsidio_sin_aprobar)
    n_subsidio_sin_radicar = int((subsidio_sin_aprobar['subsidio_radicado'] == 0).sum())

    req_credito = no_escriturados[no_escriturados['credito'] == 1]
    n_req_credito = len(req_credito)
    credito_sin_aprobar = req_credito[req_credito['credito_aprobado'] == 0]
    n_credito_sin_aprobar = len(credito_sin_aprobar)
    credito_sin_radicar = credito_sin_aprobar[credito_sin_aprobar['credito_radicado'] == 0]
    n_credito_sin_radicar = len(credito_sin_radicar)

    return {
        'subsidio': [total_aptos, n_no_escriturados, n_req_subsidio, n_subsidio_sin_aprobar, n_subsidio_sin_radicar],
        'credito': [total_aptos, n_no_escriturados, n_req_credito, n_credito_sin_aprobar, n_credito_sin_radicar ],
        'escrituradas': n_escrituradas,
    }


def _motivo_pendiente(row):
    partes = []
    if row['subsidio'] == 1 and row['subsidio_aprobado'] == 0:
        partes.append('Subsidio')
    if row['credito'] == 1 and row['credito_aprobado'] == 0:
        partes.append('Crédito')
    return ' y '.join(partes)


def _tabla_pendientes(df):
    """Clientes no escriturados que todavia no quedan en categoria 'Listo' (ver
    _clasificar_tramites) -- les falta radicar y/o aprobar subsidio y/o crédito."""
    no_esc = df[df['escriturado'] == 0].copy()

    registros = []
    for _, r in no_esc.iterrows():
        categoria_principal, _color_cat, subcategoria, _color_sub = _clasificar_tramites(r)
        if categoria_principal == 'Listo':
            continue

        anio_val = r['escritura_programada_anio']
        mes_val = r['escritura_programada_mes']
        if pd.isna(anio_val) or pd.isna(mes_val):
            anio_str, orden, periodo = None, 999999, 'Sin fecha proyectada'
        else:
            anio_str = str(int(anio_val))
            orden = int(anio_val) * 100 + int(mes_val)
            periodo = f"{MESES[int(mes_val)]} {anio_str}"

        cliente = f"{str(r['nombre'] or '').strip()} {str(r['apellido'] or '').strip()}".strip()
        # La categoria que se muestra en la tabla usa la subcategoria de detalle cuando existe
        # (todo lo que no es 'Sin Radicados' ni 'Listo'); si no, la categoria principal.
        categoria_mostrar = subcategoria if subcategoria else categoria_principal
        registros.append({
            'proyecto': r['proyecto'],
            'torre': _torre_o_default(r['torre']),
            'anio': anio_str,
            'modulo': r['modulo'],
            'cliente': cliente,
            'motivo': _motivo_pendiente(r),
            'categoria': categoria_mostrar,
            'unidades_atadas': 0 if pd.isna(r.get('unidades_atadas')) else int(r.get('unidades_atadas', 0)),
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


def _estado_tramite(necesita, aprobado, radicado):
    """
    Estado de un tramite (subsidio o credito), como letra:
        'A' = aprobado, o no se requiere (regla base: lo que no se requiere cuenta como ya
              resuelto, no hay nada que gestionar ahi).
        'R' = radicado, pendiente de aprobar.
        'NR' = sin radicar (no ha arrancado nada).
    """
    if not necesita or aprobado:
        return 'A'
    if radicado:
        return 'R'
    return 'NR'


def _clasificar_tramites(row):
    """
    Clasifica a un cliente segun la matriz Credito x Subsidio (ver MATRIZ_CATEGORIA): el
    estado de cada tramite (NR/R/A, ver _estado_tramite) determina la categoria principal +
    color y, salvo en los extremos "Sin Radicados"/"Listo", una subcategoria de detalle +
    color. 'unidades_atadas' no interviene aqui -- es un filtro aparte (ver dashboard JS).

    Retorna (categoria, color_categoria, subcategoria, color_subcategoria) -- subcategoria y
    su color son None si la categoria es 'Sin Radicados' o 'Listo'.
    """
    e_credito = _estado_tramite(bool(row.get('credito', 0) == 1), row.get('credito_aprobado', 0) == 1, row.get('credito_radicado', 0) == 1)
    e_subsidio = _estado_tramite(bool(row.get('subsidio', 0) == 1), row.get('subsidio_aprobado', 0) == 1, row.get('subsidio_radicado', 0) == 1)
    return MATRIZ_CATEGORIA[(e_credito, e_subsidio)]


def _periodo_orden(anio_val, mes_val, sin_fecha='Sin fecha proyectada'):
    """(periodo, orden, anio_str) a partir de un año/mes (pueden venir NaN) -- mismo criterio
    en todos lados: 'Mes Año' + orden = año*100+mes para que ordene cronologicamente, o
    `sin_fecha` con orden 999999 (al final) si no hay dato."""
    if pd.isna(anio_val) or pd.isna(mes_val):
        return sin_fecha, 999999, None
    anio_str = str(int(anio_val))
    return f"{MESES[int(mes_val)]} {anio_str}", int(anio_val) * 100 + int(mes_val), anio_str


def _tabla_categoria_tramites(df):
    """
    Registros con la categoria/subcategoria de avance de tramites (ver _clasificar_tramites):
    uno por cliente NO escriturado (incluye a los que no requieren ni subsidio ni credito --
    la regla los clasifica como 'Listo' de entrada), mas uno por cliente YA escriturado, con
    categoria fija 'Escrituradas' y ubicado por el MES/AÑO de la escritura REAL (no el
    proyectado, que casi nunca esta diligenciado para unidades ya cerradas).
    """
    registros = []
    for _, r in df.iterrows():
        cliente = f"{str(r['nombre'] or '').strip()} {str(r['apellido'] or '').strip()}".strip()
        unidades_atadas = 0 if pd.isna(r.get('unidades_atadas')) else int(r.get('unidades_atadas', 0))

        if r['escriturado'] == 1:
            fecha_escritura = pd.to_datetime(r.get('fecha_escritura'), errors='coerce')
            anio_mes = (fecha_escritura.year, fecha_escritura.month) if pd.notna(fecha_escritura) else (None, None)
            periodo, orden, anio_str = _periodo_orden(*anio_mes, sin_fecha='Sin fecha de escritura')
            categoria, subcategoria = 'Escrituradas', None
        else:
            periodo, orden, anio_str = _periodo_orden(r['escritura_programada_anio'], r['escritura_programada_mes'])
            categoria, _color_cat, subcategoria, _color_sub = _clasificar_tramites(r)

        registros.append({
            'id_prospecto': r['id_prospecto'],
            'proyecto': r['proyecto'],
            'torre': _torre_o_default(r['torre']),
            'anio': anio_str,
            'modulo': r['modulo'],
            'cliente': cliente,
            'categoria': categoria,
            'subcategoria': subcategoria,
            'unidades_atadas': unidades_atadas,
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


def _tabla_estado_actual_corte_anterior(fecha_corte_comite):
    """
    TODOS los clientes del snapshot completo guardado el dia del corte de COMITE (ver
    5_no_escriturados_staging.py) -- exactamente la misma poblacion que ya arma hoy la barra
    "Corte anterior" de "Clientes por categoría y mes proyectado" (incluye tanto a los no
    escriturados con mes proyectado como a los ya escriturados a esa fecha, ubicados por su mes
    de escritura real -- ver _tabla_categoria_tramites). Se usa para la 2da columna "Corte
    anterior - Estado actual" de ese grafico (ver JS: estadoActualCorteAnterior), reclasificando
    a cada uno por su estado DE HOY -- sin importar si desde entonces cambio de mes proyectado,
    se escrituro, o salio del reporte (ej. desistimiento).

    Retorna [] si no hay corte de comite definido para este mes, o si se perdio el snapshot de
    ese dia -- esa 2da columna simplemente no aparece (ver JS: estadoActualDisponible).
    """
    if not fecha_corte_comite:
        return []
    ruta_snapshot = os.path.join(RUTA_HISTORICO, f"clientes_detallado_{fecha_corte_comite.replace('-', '')}.parquet")
    if not os.path.exists(ruta_snapshot):
        return []

    df_comite = pd.read_parquet(ruta_snapshot)
    registros_comite = _tabla_categoria_tramites(df_comite)

    return [
        {
            'id_prospecto': r['id_prospecto'],
            'proyecto': r['proyecto'],
            'torre': r['torre'],
            # Mismo año/periodo/orden que ya usa la barra "Corte anterior" (ver
            # HISTORICO_CATEGORIA_TODO) -- así el filtro de año deja ambas columnas mostrando
            # exactamente los mismos periodos en el eje x, y los mismos totales de base.
            'anio': r['anio'],
            'periodo': r['periodo'],
            'orden': r['orden'],
        }
        for r in registros_comite
    ]


# Columnas del historico de categorias por mes proyectado (para el comparativo de "corte
# anterior"/semanal/comite en la grafica "Clientes por categoría y mes proyectado").
# Granularidad: una fila por proyecto + año (del cliente) + mes proyectado -- no hace falta
# por cliente, solo los totales de las 5 categorias principales de MATRIZ_CATEGORIA.
COLUMNAS_HISTORICO_CATEGORIA = ['fecha_corte', 'proyecto', 'anio', 'periodo', 'orden'] + ORDEN_CATEGORIA_PRINCIPAL


def _tabla_historico_categoria_principal(categoria_tramites):
    """Agrega los registros (uno por cliente) de _tabla_categoria_tramites en conteos de las
    5 categorias principales (ORDEN_CATEGORIA_PRINCIPAL) por proyecto + año + mes proyectado."""
    conteos = defaultdict(lambda: defaultdict(int))
    ordenes = {}
    for r in categoria_tramites:
        clave = (r['proyecto'], r['anio'], r['periodo'])
        conteos[clave][r['categoria']] += 1
        ordenes[clave] = r['orden']

    filas = []
    for (proyecto, anio, periodo), cats in conteos.items():
        fila = {
            'proyecto': proyecto,
            'anio': anio,
            'periodo': periodo,
            'orden': ordenes[(proyecto, anio, periodo)],
        }
        for cat in ORDEN_CATEGORIA_PRINCIPAL:
            fila[cat] = cats.get(cat, 0)
        filas.append(fila)
    return filas


def _guardar_historico_categoria_principal(categoria_tramites, fecha_corte):
    """
    Agrega al historico (data/historico/indicadores_por_proyecto.csv) una fila por proyecto +
    año + mes proyectado con el conteo de hoy de las 5 categorias principales (ver
    MATRIZ_CATEGORIA). Sirve para el comparativo semanal/comite que se agrega a la grafica
    "Clientes por categoría y mes proyectado" (ver JS mas abajo).

    Si ya existen filas con la misma fecha_corte, se reemplazan (evita duplicar si el
    dashboard se corre mas de una vez el mismo dia).
    """
    filas = _tabla_historico_categoria_principal(categoria_tramites)
    for fila in filas:
        fila['fecha_corte'] = fecha_corte
    nuevo = (
        pd.DataFrame(filas)[COLUMNAS_HISTORICO_CATEGORIA] if filas
        else pd.DataFrame(columns=COLUMNAS_HISTORICO_CATEGORIA)
    )

    os.makedirs(RUTA_HISTORICO, exist_ok=True)
    ruta = os.path.join(RUTA_HISTORICO, 'indicadores_por_proyecto.csv')
    if os.path.exists(ruta):
        existente = pd.read_csv(ruta, encoding='utf-8-sig')
        # Un esquema de categorias anterior (distintos nombres/cantidad de categorias, incluso
        # si es solo una fusion como "En gestion" -> "Pdt un Radicado") es incompatible con
        # este -- se descarta en vez de migrarse, porque no hay forma de reconstruir las
        # categorias nuevas a partir de las viejas ya agregadas. Se compara el SET exacto de
        # columnas de categoria (no solo subset), para detectar tambien una fusion/division.
        columnas_fijas = {'fecha_corte', 'proyecto', 'anio', 'periodo', 'orden'}
        categorias_existentes = set(existente.columns) - columnas_fijas
        if 'periodo' not in existente.columns or categorias_existentes != set(ORDEN_CATEGORIA_PRINCIPAL):
            existente = pd.DataFrame(columns=COLUMNAS_HISTORICO_CATEGORIA)
        existente['proyecto'] = existente['proyecto'].astype(str).str.strip()
        existente = existente[existente['fecha_corte'] != fecha_corte]
        historico = pd.concat([existente, nuevo], ignore_index=True)
    else:
        historico = nuevo

    historico.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f"Historico de categorias actualizado en {ruta} ({len(nuevo)} filas de hoy, {len(historico)} filas totales)")
    return ruta


# Columnas del historico de KPI por proyecto (para la variacion vs. el corte anterior en las
# tarjetas KPI). Granularidad: una fila por proyecto + año -- igual que `datos[proy][anio]`,
# no hace falta desglosar por mes proyectado aca (los embudos tampoco se filtran por mes).
COLUMNAS_HISTORICO_KPI = [
    'fecha_corte', 'proyecto', 'anio',
    'Vendidos', 'No escriturados', 'Requieren subsidio', 'Subsidio sin aprobar',
    'Requieren crédito', 'Crédito sin aprobar', 'Total Escrituradas',
]


def _fila_historico_kpi(proy, datos, anio):
    """Los 6 KPI que se muestran en las tarjetas, para un proyecto y un año (u 'Todos').
    'Vendidos' se conserva por continuidad del historico (total de unidades del proyecto, sin
    filtrar por año -- es lo que siempre significo), aunque la tarjeta kpi-0 ya no lo muestra;
    'Total Escrituradas' es la columna nueva que SI usa esa tarjeta (ver _contar_escrituradas)."""
    s = datos[proy][anio]['subsidio']
    c = datos[proy][anio]['credito']
    return {
        'Vendidos': s[0],
        'No escriturados': s[1],
        'Requieren subsidio': s[2],
        'Subsidio sin aprobar': s[3],
        'Requieren crédito': c[2],
        'Crédito sin aprobar': c[3],
        'Total Escrituradas': datos[proy][anio]['escrituradas'],
    }


def _guardar_historico_kpis(proyectos, datos, anios, fecha_corte):
    """
    Agrega al historico (data/historico/kpis_por_proyecto.csv) una fila por proyecto y por
    cada año disponible (incluido 'Todos') con el snapshot de hoy de los 6 KPI de las
    tarjetas. Sirve para la variacion vs. el corte anterior que se muestra debajo de cada
    tarjeta (ver JS mas abajo).

    Si ya existen filas con la misma fecha_corte, se reemplazan (evita duplicar si el
    dashboard se corre mas de una vez el mismo dia).
    """
    filas = []
    for anio in anios:
        for proy in proyectos:
            fila = _fila_historico_kpi(proy, datos, anio)
            fila['fecha_corte'] = fecha_corte
            fila['proyecto'] = proy
            fila['anio'] = anio
            filas.append(fila)
    nuevo = pd.DataFrame(filas)[COLUMNAS_HISTORICO_KPI]

    os.makedirs(RUTA_HISTORICO, exist_ok=True)
    ruta = os.path.join(RUTA_HISTORICO, 'kpis_por_proyecto.csv')
    if os.path.exists(ruta):
        existente = pd.read_csv(ruta, encoding='utf-8-sig')
        existente['proyecto'] = existente['proyecto'].astype(str).str.strip()
        existente = existente[existente['fecha_corte'] != fecha_corte]
        historico = pd.concat([existente, nuevo], ignore_index=True)
    else:
        historico = nuevo

    historico.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f"Historico de KPI actualizado en {ruta} ({len(nuevo)} filas de hoy, {len(historico)} filas totales)")

    _backfill_total_escrituradas(ruta)
    return ruta


def _backfill_total_escrituradas(ruta):
    """
    Rellena 'Total Escrituradas' en las filas de kpis_por_proyecto.csv que quedaron sin ese
    dato -- las que se guardaron ANTES de agregar esta columna (ver _fila_historico_kpi). No
    se toca ninguna otra columna de esas filas (serian recalculadas con las reglas de HOY, que
    pueden no coincidir con las vigentes el dia real de esa corrida -- igual que paso con el
    histórico de categorías, ver _guardar_historico_kpis_gestion para el mismo patron).

    Se reconstruye desde los snapshots completos de ese dia
    (data/historico/clientes_detallado_*.parquet); si no existe snapshot para alguna fecha,
    esa fecha se queda sin dato (no hay de donde sacarlo) y el comparativo simplemente no
    encontrara base para ese corte puntual, en vez de mostrar un numero inventado.
    """
    historico = pd.read_csv(ruta, encoding='utf-8-sig')
    if 'Total Escrituradas' not in historico.columns:
        return
    historico['proyecto'] = historico['proyecto'].astype(str).str.strip()
    pendientes = historico[historico['Total Escrituradas'].isna()]
    if pendientes.empty:
        return

    cambios = 0
    for fecha in pendientes['fecha_corte'].astype(str).unique():
        ruta_snapshot = os.path.join(RUTA_HISTORICO, f"clientes_detallado_{fecha.replace('-', '')}.parquet")
        if not os.path.exists(ruta_snapshot):
            continue
        df_snapshot = pd.read_parquet(ruta_snapshot)
        if 'fecha_escritura' not in df_snapshot.columns or 'escriturado' not in df_snapshot.columns:
            continue
        df_snapshot = df_snapshot.copy()
        df_snapshot['proyecto'] = df_snapshot['proyecto'].astype(str).str.strip()

        filas_fecha = pendientes[pendientes['fecha_corte'].astype(str) == fecha]
        for proy, anio in filas_fecha[['proyecto', 'anio']].drop_duplicates().itertuples(index=False):
            valor = _contar_escrituradas(df_snapshot[df_snapshot['proyecto'] == proy], str(anio))
            mask = (
                (historico['fecha_corte'].astype(str) == fecha)
                & (historico['proyecto'] == proy)
                & (historico['anio'].astype(str) == str(anio))
            )
            historico.loc[mask, 'Total Escrituradas'] = valor
            cambios += int(mask.sum())

    if cambios:
        historico.to_csv(ruta, index=False, encoding='utf-8-sig')
        print(f"'Total Escrituradas' rellenado retroactivamente en {cambios} filas de {ruta}")


# Columnas de origen (en clientes_detallado) -> nombre del indicador en la nueva seccion de
# "Indicadores de Gestión". A diferencia del resto del dashboard, estos 5 indicadores se calculan
# sobre TODOS los clientes (escriturados o no) y son independientes entre si -- una misma
# unidad puede contar en varios a la vez (ej. ya escriturada Y con credito aprobado), o puede
# que ninguno aplique (ej. un desistido). No se filtran por año proyectado: mas del 89% de
# los clientes escriturados no tiene ese dato (es un campo de proyeccion futura, no aplica a
# lo que ya paso), asi que filtrar por año dejaria a "Total Escrituradas" practicamente en 0.
COLUMNAS_KPI_GESTION = {
    'TotalEscrituradas': 'escriturado',
    'SubsidioRadicado': 'subsidio_radicado',
    'CreditoRadicado': 'credito_radicado',
    'SubsidioAprobado': 'subsidio_aprobado',
    'CreditoAprobado': 'credito_aprobado',
}
COLUMNAS_HISTORICO_KPI_GESTION = ['fecha_corte', 'proyecto'] + list(COLUMNAS_KPI_GESTION.keys())


def _calcular_kpis_gestion_por_proyecto(df):
    """Los 5 indicadores de COLUMNAS_KPI_GESTION, agregados por proyecto, para un df de
    clientes_detallado (de hoy o de un snapshot historico -- ver _guardar_historico_kpis_gestion).
    Si al df le falta alguna columna (ej. snapshots viejos sin 'credito_radicado' todavia), esa
    columna queda en None para ese proyecto en vez de asumir 0, para no ensuciar el historico
    con un dato que en realidad no se pudo calcular."""
    filas = []
    for proyecto, grupo in df.groupby('proyecto'):
        fila = {'proyecto': proyecto}
        for nombre_kpi, columna in COLUMNAS_KPI_GESTION.items():
            fila[nombre_kpi] = int(grupo[columna].fillna(0).sum()) if columna in grupo.columns else None
        filas.append(fila)
    return filas


def _guardar_historico_kpis_gestion(df_hoy, fecha_corte):
    """
    Guarda/actualiza data/historico/kpis_gestion_por_proyecto.csv: una fila por proyecto y
    fecha de corte con los 5 indicadores de la seccion "Indicadores de Gestión" (granularidad por proyecto
    unicamente, sin torre ni año -- igual que kpis_por_proyecto.csv, se usa con el mismo
    "gate" de cobertura completa para la variacion semanal/comite, ver JS mas abajo).

    Ademas de guardar el corte de HOY (a partir de `df_hoy`, ya en memoria), rellena
    automaticamente cualquier fecha pasada que todavia no este en el historico, leyendo los
    snapshots completos ya guardados en data/historico/clientes_detallado_*.parquet (ver
    5_no_escriturados_staging.py) -- asi el comparativo semanal/comite funciona desde el
    primer dia que se activa esta seccion, sin tener que esperar semanas a que se acumule.
    """
    ruta = os.path.join(RUTA_HISTORICO, 'kpis_gestion_por_proyecto.csv')
    if os.path.exists(ruta):
        existente = pd.read_csv(ruta, encoding='utf-8-sig')
        existente['proyecto'] = existente['proyecto'].astype(str).str.strip()
    else:
        existente = pd.DataFrame(columns=COLUMNAS_HISTORICO_KPI_GESTION)
    fechas_ya_guardadas = set(existente['fecha_corte'].astype(str).unique()) - {fecha_corte}

    filas_hoy = _calcular_kpis_gestion_por_proyecto(df_hoy)
    for fila in filas_hoy:
        fila['fecha_corte'] = fecha_corte

    filas_backfill = []
    for ruta_snapshot in sorted(glob(os.path.join(RUTA_HISTORICO, 'clientes_detallado_*.parquet'))):
        nombre = os.path.basename(ruta_snapshot)
        fecha_snapshot = nombre[len('clientes_detallado_'):-len('.parquet')]
        fecha_snapshot = f"{fecha_snapshot[:4]}-{fecha_snapshot[4:6]}-{fecha_snapshot[6:]}"
        if fecha_snapshot == fecha_corte or fecha_snapshot in fechas_ya_guardadas:
            continue
        df_snapshot = pd.read_parquet(ruta_snapshot)
        for fila in _calcular_kpis_gestion_por_proyecto(df_snapshot):
            fila['fecha_corte'] = fecha_snapshot
            filas_backfill.append(fila)

    nuevo = pd.DataFrame(filas_hoy + filas_backfill)
    nuevo = nuevo[COLUMNAS_HISTORICO_KPI_GESTION] if len(nuevo) else pd.DataFrame(columns=COLUMNAS_HISTORICO_KPI_GESTION)

    fechas_nuevas = set(nuevo['fecha_corte'].astype(str).unique())
    existente = existente[~existente['fecha_corte'].astype(str).isin(fechas_nuevas)]
    historico = pd.concat([existente, nuevo], ignore_index=True)
    historico.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f"Historico de KPI de gestion actualizado en {ruta} ({len(nuevo)} filas nuevas/rellenadas, {len(historico)} filas totales)")
    return ruta


def _guardar_historico_kpis_gestion_atadas(df_hoy, fecha_corte):
    """
    Igual que _guardar_historico_kpis_gestion, pero SOLO sobre las unidades con
    unidades_atadas == 1 -- para que el comparativo semanal/comite de "Indicadores de
    Gestión" tambien funcione cuando el filtro "Unidades atadas" esta en 'Atadas' (antes no
    habia ninguna base de comparacion para ese caso, ver JS: HISTORICO_KPI_GESTION_ATADAS_TODO).

    A diferencia de _guardar_historico_kpis_gestion, esta NO se puede rellenar con
    snapshots pasados (data/historico/clientes_detallado_*.parquet): esos snapshots se
    guardan en 5_no_escriturados_staging.py ANTES de que corra actualizar_unidades_atadas.py
    (que es quien calcula la columna 'unidades_atadas'), asi que ningun snapshot historico
    -- ni siquiera el de hoy -- trae esa columna. Por eso el comparativo para 'Atadas' arranca
    de cero desde el dia que se activa esta seccion (necesita al menos un corte mas para que
    aparezca una variacion).
    """
    ruta = os.path.join(RUTA_HISTORICO, 'kpis_gestion_atadas_por_proyecto.csv')
    if os.path.exists(ruta):
        existente = pd.read_csv(ruta, encoding='utf-8-sig')
        existente['proyecto'] = existente['proyecto'].astype(str).str.strip()
    else:
        existente = pd.DataFrame(columns=COLUMNAS_HISTORICO_KPI_GESTION)

    if 'unidades_atadas' in df_hoy.columns:
        df_atadas = df_hoy[df_hoy['unidades_atadas'] == 1]
    else:
        df_atadas = df_hoy.iloc[0:0]
    filas_hoy = _calcular_kpis_gestion_por_proyecto(df_atadas)
    for fila in filas_hoy:
        fila['fecha_corte'] = fecha_corte
    nuevo = (
        pd.DataFrame(filas_hoy)[COLUMNAS_HISTORICO_KPI_GESTION] if filas_hoy
        else pd.DataFrame(columns=COLUMNAS_HISTORICO_KPI_GESTION)
    )

    existente = existente[existente['fecha_corte'].astype(str) != fecha_corte]
    historico = pd.concat([existente, nuevo], ignore_index=True)
    historico.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f"Historico de KPI de gestion (solo atadas) actualizado en {ruta} "
          f"({len(nuevo)} filas de hoy, {len(historico)} filas totales)")
    return ruta


def _fig_funnel(div_id, stages, values, titulo):
    fig = go.Figure(go.Funnel(
        y=stages,
        x=values,
        textinfo='value+percent initial',
        textposition='inside',
        marker=dict(color=[COLOR_VERDE_OSCURO] + [COLOR_PENDIENTE] * (len(stages) - 1)),
    ))
    altura = 90 + 75 * len(stages)
    fig.update_layout(title=titulo, margin=dict(t=60, b=20, l=190), height=altura, autosize=True)
    return fig.to_html(
        full_html=False, include_plotlyjs=False, div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
        default_width='100%',
    )


def _fig_barras_proyecto(div_id, proyectos, valores):
    fig = go.Figure(go.Bar(
        x=valores, y=proyectos, orientation='h',
        marker_color=COLOR_VERDE, text=valores, textposition='outside',
    ))
    fig.update_layout(
        title='Apartamentos no escriturados por proyecto',
        xaxis_title='Cantidad de apartamentos',
        margin=dict(l=220, t=60, r=40, b=40),
        height=max(320, 60 + 40 * max(len(proyectos), 1)),
        autosize=True,
    )
    return fig.to_html(
        full_html=False, include_plotlyjs='inline', div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
    )


def _fig_barras_apiladas_por_mes(div_id, registros, campo_categoria, orden_apilado, colores, titulo):
    """
    Barra apilada por mes proyectado de escrituracion, contando `registros` segun el valor de
    `campo_categoria` (ej. 'categoria' o 'subcategoria'). Generica para reutilizarla con
    distintos esquemas de categorizacion (categoria principal, subcategoria de gestion, etc.).
    Primera traza de `orden_apilado` = base de la barra (queda abajo).
    """
    df = pd.DataFrame(registros)
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=titulo, xaxis_title='Mes de escrituración', yaxis_title='Cantidad de clientes')
        return fig.to_html(
            full_html=False, include_plotlyjs='inline', div_id=div_id,
            config={'displaylogo': False, 'responsive': True},
        )

    legend_rank = {categoria: i + 1 for i, categoria in enumerate(orden_apilado)}
    periodos = list(dict.fromkeys(df['periodo'].tolist()))
    fig = go.Figure()
    for categoria in orden_apilado:
        valores = [len(df[(df['periodo'] == periodo) & (df[campo_categoria] == categoria)]) for periodo in periodos]
        fig.add_trace(go.Bar(
            name=categoria,
            x=periodos,
            y=valores,
            text=[str(v) if v > 0 else '' for v in valores],
            textposition='inside',
            insidetextanchor='middle',
            # Sin esto, Plotly rota el numero a vertical cuando el segmento es angosto.
            # Con textangle=0 se fuerza horizontal siempre; si de verdad no cabe, se oculta
            # (en vez de rotarse), y con letra un poco mas chica caben mas numeros sin rotar.
            textangle=0,
            textfont=dict(size=11),
            marker_color=colores.get(categoria, COLOR_PENDIENTE),
            legendrank=legend_rank.get(categoria, 99),
        ))

    fig.update_traces(marker_line_width=0)

    # Total de unidades a escriturar por mes, como rotulo encima de cada barra apilada.
    totales_por_mes = [len(df[df['periodo'] == periodo]) for periodo in periodos]
    anotaciones_totales = [
        dict(x=periodo, y=total, text=f"<b>{total}</b>", showarrow=False, yshift=10,
             font=dict(color=COLOR_VERDE_OSCURO, size=13))
        for periodo, total in zip(periodos, totales_por_mes)
    ]

    fig.update_layout(
        title=titulo,
        xaxis_title='Mes de escrituración',
        yaxis_title='Cantidad de clientes',
        barmode='stack',
        legend_title='Categoría',
        margin=dict(t=60, b=40, l=40, r=20),
        height=430,
        autosize=True,
        template='plotly_white',
        annotations=anotaciones_totales,
    )
    return fig.to_html(
        full_html=False, include_plotlyjs='inline', div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
    )


def _sumar_metricas(lista_metricas):
    subsidio = [0] * len(ETAPAS_SUBSIDIO)
    credito = [0] * len(ETAPAS_CREDITO)
    escrituradas = 0
    for m in lista_metricas:
        subsidio = [a + b for a, b in zip(subsidio, m['subsidio'])]
        credito = [a + b for a, b in zip(credito, m['credito'])]
        escrituradas += m['escrituradas']
    return {'subsidio': subsidio, 'credito': credito, 'escrituradas': escrituradas}


def run():
    ruta_csv = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    df = pd.read_csv(ruta_csv)
    fecha_corte = df['fecha_corte'].iloc[0] if 'fecha_corte' in df.columns and len(df) else datetime.now().strftime('%Y-%m-%d')

    proyectos = sorted(df['proyecto'].dropna().unique().tolist())
    # Solo años de clientes NO escriturados: el filtro de año es para ubicar pendientes, un año
    # donde ya todo esta escriturado no aporta nada util y solo ensucia el selector (ver
    # tambien la restriccion equivalente del respaldo de fecha en 5_no_escriturados_staging.py).
    anios_presentes = sorted({
        int(a) for a in df.loc[df['escriturado'] == 0, 'escritura_programada_anio'].dropna().unique()
    })
    opciones_anio = [TODOS] + [str(a) for a in anios_presentes]
    anio_defecto = str(ANIO_OBJETIVO_ESCRITURA) if str(ANIO_OBJETIVO_ESCRITURA) in opciones_anio else TODOS

    # Métricas de los embudos por cada (proyecto, año)
    datos = {}
    for proy in proyectos:
        df_proy = df[df['proyecto'] == proy]
        datos[proy] = {anio: _calcular_metricas(df_proy, anio) for anio in opciones_anio}

    pendientes = _tabla_pendientes(df)
    categoria_tramites = _tabla_categoria_tramites(df)
    clientes_funnel = _tabla_clientes_funnel(df)
    torres_por_proyecto = _torres_por_proyecto(df)

    # Guarda el corte de hoy en los 3 historicos (categorias, KPI de embudo, KPI de gestion) y
    # los relee COMPLETOS (todas las fechas, no solo "el corte anterior"): el selector
    # Semanal/Comité elige del lado del cliente (JS) la fecha mas cercana a "hace 7 dias"
    # (semanal) o el corte de comite del mes (ver data/referencia/cortes_comite.csv) segun lo
    # que el usuario tenga marcado, asi que aca ya no se precalcula un unico corte anterior
    # como antes.
    ruta_historico_cat = _guardar_historico_categoria_principal(categoria_tramites, fecha_corte)
    hist_cat = pd.read_csv(ruta_historico_cat, encoding='utf-8-sig')
    hist_cat['proyecto'] = hist_cat['proyecto'].astype(str).str.strip()
    # 'anio' vuelve del CSV como float (ej. 2026.0, o NaN para "Sin fecha proyectada") -- se
    # normaliza a string para que las comparaciones "===" contra el filtro de año en JS
    # (siempre string, viene del <select>) funcionen igual que con CATEGORIA_TRAMITES.
    hist_cat['anio'] = hist_cat['anio'].apply(lambda v: None if pd.isna(v) else str(int(v)))
    historico_categoria_todo = hist_cat.to_dict('records')
    fechas_hist_cat = sorted(hist_cat['fecha_corte'].astype(str).unique().tolist())

    # Igual que arriba, pero para los 6 KPI de las tarjetas originales (embudo).
    ruta_historico_kpi = _guardar_historico_kpis(proyectos, datos, opciones_anio, fecha_corte)
    hist_kpi = pd.read_csv(ruta_historico_kpi, encoding='utf-8-sig')
    hist_kpi['proyecto'] = hist_kpi['proyecto'].astype(str).str.strip()
    hist_kpi['anio'] = hist_kpi['anio'].astype(str)
    historico_kpi_todo = hist_kpi.to_dict('records')
    fechas_hist_kpi = sorted(hist_kpi['fecha_corte'].astype(str).unique().tolist())

    # Igual, pero para los 5 KPI nuevos de la seccion "Indicadores de Gestión" (ver
    # _guardar_historico_kpis_gestion -- sin desglose por año, por diseño).
    ruta_historico_kpi_gestion = _guardar_historico_kpis_gestion(df, fecha_corte)
    hist_kpi_gestion = pd.read_csv(ruta_historico_kpi_gestion, encoding='utf-8-sig')
    hist_kpi_gestion['proyecto'] = hist_kpi_gestion['proyecto'].astype(str).str.strip()
    historico_kpi_gestion_todo = hist_kpi_gestion.to_dict('records')
    fechas_hist_kpi_gestion = sorted(hist_kpi_gestion['fecha_corte'].astype(str).unique().tolist())

    # Version SOLO de las unidades atadas del mismo historico de arriba, para que el
    # comparativo de "Indicadores de Gestión" tambien funcione con el filtro "Unidades
    # atadas" en 'Atadas' (ver _guardar_historico_kpis_gestion_atadas -- no se puede rellenar
    # con corridas pasadas, arranca de cero desde hoy).
    ruta_historico_kpi_gestion_atadas = _guardar_historico_kpis_gestion_atadas(df, fecha_corte)
    hist_kpi_gestion_atadas = pd.read_csv(ruta_historico_kpi_gestion_atadas, encoding='utf-8-sig')
    hist_kpi_gestion_atadas['proyecto'] = hist_kpi_gestion_atadas['proyecto'].astype(str).str.strip()
    historico_kpi_gestion_atadas_todo = hist_kpi_gestion_atadas.to_dict('records')
    fechas_hist_kpi_gestion_atadas = sorted(hist_kpi_gestion_atadas['fecha_corte'].astype(str).unique().tolist())

    # Corte de comite del mes (ver data/referencia/cortes_comite.csv) -- base del comparativo
    # COMITE en las 4 fuentes de arriba. Se valida contra CADA UNA por separado: no asumir que
    # porque existe en una ya existe en las demas (ya paso -- ver historial de este archivo,
    # el gráfico de categorias se quedo comparando contra otra fecha sin que nadie se diera
    # cuenta porque indicadores_por_proyecto.csv no tenia el corte que si tenia kpis_por_proyecto.csv).
    fecha_corte_comite = _fecha_corte_comite(fecha_corte)
    if fecha_corte_comite:
        fuentes_historico_comite = {
            'categorias (indicadores_por_proyecto.csv)': fechas_hist_cat,
            'KPI del embudo (kpis_por_proyecto.csv)': fechas_hist_kpi,
            'Indicadores de Gestión (kpis_gestion_por_proyecto.csv)': fechas_hist_kpi_gestion,
            'Indicadores de Gestión, solo atadas (kpis_gestion_atadas_por_proyecto.csv)': fechas_hist_kpi_gestion_atadas,
        }
        for nombre_fuente, fechas_disponibles in fuentes_historico_comite.items():
            if fecha_corte_comite not in fechas_disponibles:
                print(f"ADVERTENCIA: el corte de comite {fecha_corte_comite} "
                      f"(data/referencia/cortes_comite.csv) no existe en el historico de "
                      f"{nombre_fuente}. El comparativo comite de esa seccion caera al "
                      f"automatico. Fechas disponibles: {fechas_disponibles}")

    # Poblacion del "Corte anterior" (no escriturados al momento del corte de comite),
    # reclasificada por su estado DE HOY -- 2da columna "Corte anterior - Estado actual" de
    # "Clientes por categoría y mes proyectado" (ver _tabla_estado_actual_corte_anterior). []
    # si no hay corte de comite definido o se perdio el snapshot de ese dia.
    estado_actual_corte_anterior = _tabla_estado_actual_corte_anterior(fecha_corte_comite)

    # Ajuste SOLO de presentacion (no se guarda en ningun archivo): 'VERDELIMA' llega en
    # mayusculas desde Smarthome; se muestra en el dashboard como "Verdelima", igual que el
    # resto de proyectos "Verde*" (Verdeoliva, Verdepino, Verdevivo). Se aplica DESPUES de
    # guardar/leer el historico (arriba), para no romper la comparacion contra corridas
    # anteriores ya guardadas en disco con el nombre original.
    NOMBRES_PROYECTO_DISPLAY = {'VERDELIMA': 'Verdelima'}

    def _nombre_display(proyecto):
        return NOMBRES_PROYECTO_DISPLAY.get(proyecto, proyecto)

    proyectos = sorted(_nombre_display(p) for p in proyectos)
    datos = {_nombre_display(p): v for p, v in datos.items()}
    for _r in pendientes:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in categoria_tramites:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in clientes_funnel:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in estado_actual_corte_anterior:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    torres_por_proyecto = {_nombre_display(p): v for p, v in torres_por_proyecto.items()}
    for _r in historico_categoria_todo:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in historico_kpi_todo:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in historico_kpi_gestion_todo:
        _r['proyecto'] = _nombre_display(_r['proyecto'])
    for _r in historico_kpi_gestion_atadas_todo:
        _r['proyecto'] = _nombre_display(_r['proyecto'])

    metricas_iniciales = _sumar_metricas([datos[p][anio_defecto] for p in proyectos])

    # Inicialización de la gráfica de barras
    items_iniciales = [{'proyecto': p, 'valor': datos[p][anio_defecto]['subsidio'][1]} for p in proyectos]
    items_iniciales.sort(key=lambda x: x['valor'])
    proyectos_init = [x['proyecto'] for x in items_iniciales]
    valores_init = [x['valor'] for x in items_iniciales]

    div_funnel_subsidio = _fig_funnel('fig_subsidio', ETAPAS_SUBSIDIO, metricas_iniciales['subsidio'], 'Embudo de Subsidio')
    div_funnel_credito = _fig_funnel('fig_credito', ETAPAS_CREDITO, metricas_iniciales['credito'], 'Embudo de Crédito')
    div_barras_proyecto = _fig_barras_proyecto('fig_proyecto', proyectos_init, valores_init)

    # El detalle por subcategoria incluye todo lo que no es ni 'Sin Radicados' ni 'Listo'
    # (o sea, tiene subcategoria asignada -- ver MATRIZ_CATEGORIA).
    registros_detalle_iniciales = [r for r in categoria_tramites if r['subcategoria']]
    div_categoria_principal = _fig_barras_apiladas_por_mes(
        'fig_categoria_principal', categoria_tramites, 'categoria',
        ORDEN_CATEGORIA_PRINCIPAL, COLORES_CATEGORIA_PRINCIPAL,
        'Clientes por categoría y mes proyectado',
    )
    div_subcategoria_gestion = _fig_barras_apiladas_por_mes(
        'fig_subcategoria_gestion', registros_detalle_iniciales, 'subcategoria',
        ORDEN_SUBCATEGORIA_GESTION, COLORES_SUBCATEGORIA_GESTION,
        'Detalle de combinación Subsidio/Crédito por mes proyectado',
    )

    checkboxes_proyecto_html = "".join(
        f'<label class="ms-opcion"><input type="checkbox" class="chk-proyecto" value="{p}" checked> {p}</label>'
        for p in proyectos
    )
    opciones_anio_html = "".join(
        f'<option value="{a}"{" selected" if a == anio_defecto else ""}>{a}</option>' for a in opciones_anio
    )

    s = metricas_iniciales['subsidio']
    c = metricas_iniciales['credito']
    total_escrituradas_iniciales = metricas_iniciales['escrituradas']

    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe Pendientes por Escriturar - {fecha_corte}</title>
<style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 24px; background: #f5f6f8; color: #222; }}
    .encabezado {{ display: flex; align-items: center; gap: 14px; margin-bottom: 4px; }}
    .logo-dot {{ width: 14px; height: 14px; border-radius: 50%; background: {COLOR_VERDE}; display: inline-block; }}
    h1 {{ margin: 0; }}
    .subtitulo {{ color: #555; margin-top: 4px; margin-bottom: 20px; }}
    .filtros {{ display: flex; gap: 24px; align-items: center; background: #fff; border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.15); padding: 14px 20px; margin-bottom: 24px;
                border-left: 4px solid {COLOR_VERDE}; }}
    .filtros label {{ font-weight: bold; margin-right: 8px; }}
    .filtros select {{ font-size: 14px; padding: 6px 10px; border-radius: 4px; border: 1px solid #ccc; }}
    .ms-wrap {{ position: relative; display: inline-block; }}
    .ms-boton {{ font-size: 14px; padding: 6px 12px; border-radius: 4px; border: 1px solid #ccc; background: #fff; cursor: pointer; }}
    .ms-panel {{ position: absolute; top: 110%; left: 0; z-index: 10; background: #fff; border: 1px solid #ccc;
                 border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); padding: 10px 14px; min-width: 240px;
                 max-height: 300px; overflow-y: auto; }}
    .ms-opcion {{ display: block; font-weight: normal; padding: 3px 0; white-space: nowrap; }}
    .ms-acciones {{ display: flex; gap: 10px; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid #eee; }}
    .ms-acciones a {{ font-size: 12px; color: {COLOR_VERDE_OSCURO}; cursor: pointer; text-decoration: underline; }}
    .kpi-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 32px; }}
    .kpi-card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
                 padding: 16px 20px; min-width: 150px; flex: 1; text-align: center; border-top: 3px solid {COLOR_VERDE}; }}
    .kpi-valor {{ font-size: 26px; font-weight: bold; color: {COLOR_VERDE_OSCURO}; }}
    .kpi-etiqueta {{ font-size: 13px; color: #555; margin-top: 4px; }}
    .kpi-delta {{ font-size: 12px; color: #777; margin-top: 6px; min-height: 14px; }}
    .kpi-card-gestion {{ border-top-color: {COLOR_PENDIENTE}; }}
    .kpi-card-gestion .kpi-valor {{ font-size: 20px; min-height: 26px; }}
    .seccion {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
                padding: 16px; margin-bottom: 24px; }}
    .fila-embudos {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }}
    .fila-embudos > div {{ min-width: 0; overflow: hidden; }}
    .fila-embudos > div > div {{ width: 100% !important; }}
    @media (max-width: 820px) {{
        .fila-embudos {{ grid-template-columns: 1fr; }}
    }}
    h2 {{ margin-top: 0; color: {COLOR_VERDE_OSCURO}; }}
    .titulo-grafica {{ margin: 0 0 4px 0; font-size: 15px; color: {COLOR_VERDE_OSCURO}; text-align: center; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    thead th {{ text-align: left; background: {COLOR_VERDE}; color: #fff; padding: 8px 10px; position: sticky; top: 0; }}
    tbody td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
    .categoria-badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: bold; color: #fff; }}
    tr.grupo-mes td {{ background: #eef5ef; font-weight: bold; color: {COLOR_VERDE_OSCURO}; padding-top: 12px; }}
    .tabla-contenedor {{ max-height: 480px; overflow-y: auto; border: 1px solid #eee; border-radius: 6px; }}
    #tablaContador {{ color: #555; font-size: 13px; margin-bottom: 8px; }}
    .encabezado-tabla {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
    .encabezado-tabla h2 {{ margin: 0; }}
</style>
</head>
<body>
<div class="encabezado"><span class="logo-dot"></span><span class="logo-dot"></span><h1>Informe de Pendientes por Escriturar</h1></div>
<p class="subtitulo">Corte: {fecha_corte}<span id="notaCorteAnterior"></span></p>

<div class="filtros">
    <div><label for="filtroAnio">Año proyectado:</label>
        <select id="filtroAnio">{opciones_anio_html}</select></div>
    <div class="ms-wrap">
        <label>Proyecto:</label>
        <button type="button" class="ms-boton" id="btnFiltroProyecto">Todos ▾</button>
        <div class="ms-panel" id="panelFiltroProyecto" style="display:none;">
            <div class="ms-acciones">
                <a id="lnkTodosProyectos">Todos</a>
                <a id="lnkNingunProyecto">Ninguno</a>
            </div>
            {checkboxes_proyecto_html}
        </div>
    </div>
    <div class="ms-wrap">
        <label>Torre:</label>
        <button type="button" class="ms-boton" id="btnFiltroTorre">Todos ▾</button>
        <div class="ms-panel" id="panelFiltroTorre" style="display:none;">
            <div class="ms-acciones">
                <a id="lnkTodosTorres">Todos</a>
                <a id="lnkNingunaTorre">Ninguno</a>
            </div>
            <div id="checkboxesTorre"></div>
        </div>
    </div>
    <div><label for="filtroAtadas">Unidades atadas:</label>
        <select id="filtroAtadas">
            <option value="Todos" selected>Todos</option>
            <option value="Atadas">Atadas</option>
        </select></div>
    <div><label for="filtroComparativo">Comparativo:</label>
        <select id="filtroComparativo">
            <option value="semanal">Semanal</option>
            <option value="comite" selected>Comité</option>
        </select></div>
</div>

<div class="kpi-row" id="kpiRow">
    <div class="kpi-card"><div class="kpi-valor" id="kpi-0">{total_escrituradas_iniciales:,}</div><div class="kpi-etiqueta">Total Unidades Escrituradas</div><div class="kpi-delta" id="kpi-delta-0"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-1">{s[1]:,}</div><div class="kpi-etiqueta">No escriturados</div><div class="kpi-delta" id="kpi-delta-1"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-2">{s[2]:,}</div><div class="kpi-etiqueta">Requieren subsidio</div><div class="kpi-delta" id="kpi-delta-2"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-3">{s[3]:,}</div><div class="kpi-etiqueta">Subsidio sin aprobar</div><div class="kpi-delta" id="kpi-delta-3"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-5">{c[2]:,}</div><div class="kpi-etiqueta">Requieren crédito</div><div class="kpi-delta" id="kpi-delta-5"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-6">{c[3]:,}</div><div class="kpi-etiqueta">Crédito sin aprobar</div><div class="kpi-delta" id="kpi-delta-6"></div></div>
</div>

<h2>Indicadores de Gestión</h2>
<div class="kpi-row" id="kpiRowGestion">
    <div class="kpi-card kpi-card-gestion"><div class="kpi-valor" id="kpi-gestion-0"></div><div class="kpi-etiqueta">Total Unidades Escrituradas</div></div>
    <div class="kpi-card kpi-card-gestion"><div class="kpi-valor" id="kpi-gestion-1"></div><div class="kpi-etiqueta">Unidades con Subsidio Radicado</div></div>
    <div class="kpi-card kpi-card-gestion"><div class="kpi-valor" id="kpi-gestion-2"></div><div class="kpi-etiqueta">Unidades con Crédito Radicado</div></div>
    <div class="kpi-card kpi-card-gestion"><div class="kpi-valor" id="kpi-gestion-3"></div><div class="kpi-etiqueta">Unidades con Subsidio Aprobado</div></div>
    <div class="kpi-card kpi-card-gestion"><div class="kpi-valor" id="kpi-gestion-4"></div><div class="kpi-etiqueta">Unidades con Crédito Aprobado</div></div>
</div>

<div class="seccion">{div_barras_proyecto}</div>

<div class="seccion">
<div class="fila-embudos">
<div>{div_funnel_subsidio}</div>
<div>{div_funnel_credito}</div>
</div>
</div>

<div class="seccion">
<h2>Clientes por categoría y mes proyectado</h2>
{div_categoria_principal}
</div>

<div class="seccion">
<h2>Detalle de combinación Subsidio/Crédito por mes proyectado</h2>
{div_subcategoria_gestion}
</div>

<div class="seccion">
<div class="encabezado-tabla">
<h2>Clientes pendientes de aprobación (subsidio y/o crédito)</h2>
<button type="button" class="ms-boton" id="btnDescargarNoEscriturados">⬇ Descargar no escriturados (CSV)</button>
</div>
<p id="tablaContador"></p>
<div class="tabla-contenedor">
<table>
<thead><tr><th>Proyecto</th><th>Módulo</th><th>Cliente</th><th>Pendiente</th><th>Categoría</th></tr></thead>
<tbody id="tablaPendientesBody"></tbody>
</table>
</div>
</div>

<script>
const DATOS = {json.dumps(datos)};
const PENDIENTES = {json.dumps(pendientes)};
const CATEGORIA_TRAMITES = {json.dumps(categoria_tramites)};
const TODOS_PROYECTOS = {json.dumps(proyectos)};
// Filtro de torre: se rearma cada vez que cambia la seleccion de proyecto (ver
// renderizarPanelTorres mas abajo), porque el numero de torre se repite entre proyectos.
const TORRES_POR_PROYECTO = {json.dumps(torres_por_proyecto)};
const SIN_TORRE = {json.dumps(SIN_TORRE)};
// Un registro por cliente (TODOS, no solo no escriturados) para recalcular embudos/KPI en
// vivo respetando proyecto+torre+año -- el precalculo DATOS[proy][anio] no tiene dimension
// de torre, asi que ya no se usa para la actualizacion en vivo (solo para el historico).
const CLIENTES_FUNNEL = {json.dumps(clientes_funnel)};
const COLORES_CATEGORIA_TABLA = {json.dumps(COLORES_CATEGORIA_TABLA)};
const ORDEN_CATEGORIA_PRINCIPAL = {json.dumps(ORDEN_CATEGORIA_PRINCIPAL)};
const COLORES_CATEGORIA_PRINCIPAL = {json.dumps(COLORES_CATEGORIA_PRINCIPAL)};
const ORDEN_SUBCATEGORIA_GESTION = {json.dumps(ORDEN_SUBCATEGORIA_GESTION)};
const COLORES_SUBCATEGORIA_GESTION = {json.dumps(COLORES_SUBCATEGORIA_GESTION)};

// Fecha de "hoy" segun el corte de los datos (no la fecha real del navegador) -- de aca se
// elige, del lado del cliente, el corte anterior semanal (restando 7 dias) o de comite (ver
// fechaCorteAnteriorSegunVista mas abajo).
const FECHA_CORTE = {json.dumps(fecha_corte)};
// Fecha del corte de comite de este mes (ver data/referencia/cortes_comite.csv y
// _fecha_corte_comite en Python) -- si no es null, el comparativo COMITE compara contra
// esta fecha en vez del automatico. No afecta 'semanal'. Null si el mes en curso todavia no
// tiene fila en ese archivo (comite aun no definido/corrido).
const FECHA_CORTE_COMITE = {json.dumps(fecha_corte_comite)};

// Historico COMPLETO (todas las fechas de corte guardadas hasta hoy) de las fuentes con
// comparativo semanal/comite. Ninguna tiene desglose por torre (por eso todas exigen
// cobertura completa de torre, ver seleccionCubreTodasLasTorres):
//   HISTORICO_CATEGORIA_TODO         -- proyecto + año + mes proyectado (grafica de categorias).
//   HISTORICO_KPI_TODO               -- proyecto + año (tarjetas KPI del embudo).
//   HISTORICO_KPI_GESTION_TODO       -- solo proyecto, sobre TODAS las unidades (tarjetas de
//                                        "Indicadores de Gestión" con filtro atadas = 'Todos').
//   HISTORICO_KPI_GESTION_ATADAS_TODO -- igual, pero solo sobre unidades_atadas == 1 (mismas
//                                        tarjetas con el filtro en 'Atadas'). Arranca vacio el
//                                        primer dia -- no se puede rellenar con corridas
//                                        pasadas (ver _guardar_historico_kpis_gestion_atadas).
const HISTORICO_CATEGORIA_TODO = {json.dumps(historico_categoria_todo)};
// Clientes que NO estaban escriturados en el corte de comite (misma poblacion que arma la
// barra "Corte anterior" de arriba), uno por cliente -- se usan para la 2da columna "Corte
// anterior - Estado actual" de esa grafica (ver _tabla_estado_actual_corte_anterior en Python
// y estadoActualCorteAnteriorFiltrado en JS mas abajo), reclasificandolos segun su categoria
// DE HOY (via CATEGORIA_TRAMITES). [] si no hay corte de comite definido o se perdio el
// snapshot de ese dia -- esa 2da columna simplemente no aparece.
const ESTADO_ACTUAL_CORTE_ANTERIOR = {json.dumps(estado_actual_corte_anterior)};
const HISTORICO_KPI_TODO = {json.dumps(historico_kpi_todo)};
const HISTORICO_KPI_GESTION_TODO = {json.dumps(historico_kpi_gestion_todo)};
const HISTORICO_KPI_GESTION_ATADAS_TODO = {json.dumps(historico_kpi_gestion_atadas_todo)};

// id de tarjeta KPI -> indice en el arreglo `kpis` de actualizar() (los ids no son
// consecutivos: no existe kpi-4, ese es "Subsidio sin radicar" que solo se muestra en el embudo).
const IDS_KPI = [0, 1, 2, 3, 5, 6];
// id de tarjeta KPI -> nombre de indicador en el historico de KPI (mismo orden que IDS_KPI).
// kpi-0 usa 'Total Escrituradas' (no 'Vendidos'): la tarjeta muestra unidades escrituradas
// filtradas por año de escritura real, ver calcularMetricasFuncional.
const NOMBRES_KPI_HISTORICO = {{
    0: 'Total Escrituradas', 1: 'No escriturados', 2: 'Requieren subsidio', 3: 'Subsidio sin aprobar',
    5: 'Requieren crédito', 6: 'Crédito sin aprobar'
}};

// Tarjeta de "Indicadores de Gestión" (indice = orden en el HTML) -> nombre del indicador en el
// historico + campo correspondiente en CLIENTES_FUNNEL (para el valor "de hoy").
const KPIS_GESTION = [
    {{ nombreHistorico: 'TotalEscrituradas', campoCliente: 'escriturado' }},
    {{ nombreHistorico: 'SubsidioRadicado', campoCliente: 'subsidio_radicado' }},
    {{ nombreHistorico: 'CreditoRadicado', campoCliente: 'credito_radicado' }},
    {{ nombreHistorico: 'SubsidioAprobado', campoCliente: 'subsidio_aprobado' }},
    {{ nombreHistorico: 'CreditoAprobado', campoCliente: 'credito_aprobado' }},
];

function proyectosSeleccionados() {{
    const marcadas = Array.from(document.querySelectorAll('.chk-proyecto:checked')).map(c => c.value);
    return marcadas;
}}

// --- Filtro de torre: depende de cuales proyectos esten marcados (el numero de torre se
// repite entre proyectos), asi que el panel se rearma cada vez que cambia esa seleccion. ---

function torresDisponibles(seleccionProyectos) {{
    const torres = [];
    seleccionProyectos.forEach(p => {{
        (TORRES_POR_PROYECTO[p] || []).forEach(t => {{ if (!torres.includes(t)) torres.push(t); }});
    }});
    torres.sort((a, b) => {{
        const na = a === SIN_TORRE ? Infinity : parseInt(a.split(' ')[1], 10);
        const nb = b === SIN_TORRE ? Infinity : parseInt(b.split(' ')[1], 10);
        return na - nb;
    }});
    return torres;
}}

function renderizarPanelTorres(seleccionProyectos) {{
    // Se reinicia a "todas marcadas" cada vez que cambia el proyecto -- no se intenta
    // conservar una seleccion parcial de torres entre proyectos distintos.
    const torres = torresDisponibles(seleccionProyectos);
    const contenedor = document.getElementById('checkboxesTorre');
    contenedor.innerHTML = torres.map(t =>
        `<label class="ms-opcion"><input type="checkbox" class="chk-torre" value="${{t}}" checked> ${{t}}</label>`
    ).join('');
    contenedor.querySelectorAll('.chk-torre').forEach(chk => chk.addEventListener('change', actualizar));
}}

function torresSeleccionadas() {{
    return Array.from(document.querySelectorAll('.chk-torre:checked')).map(c => c.value);
}}

function actualizarBotonTorre(seleccionProyectos, seleccionTorres) {{
    const disponibles = torresDisponibles(seleccionProyectos);
    const boton = document.getElementById('btnFiltroTorre');
    if (seleccionTorres.length === disponibles.length) {{
        boton.textContent = 'Todos ▾';
    }} else if (seleccionTorres.length === 1) {{
        boton.textContent = seleccionTorres[0] + ' ▾';
    }} else if (seleccionTorres.length === 0) {{
        boton.textContent = 'Ninguno ▾';
    }} else {{
        boton.textContent = seleccionTorres.length + ' seleccionadas ▾';
    }}
}}

// El historico (comparativo semanal/comite) solo se guarda por proyecto (+año en 2 de las 3
// fuentes), sin desglose por torre ni por unidades atadas -- si la torre es un subconjunto, o
// el filtro de atadas no esta en "Todos", ya no hay una base valida de comparacion, asi que
// esas mejoras se ocultan (ver mas abajo) en vez de mostrar un numero que en realidad
// corresponde a un universo mas amplio que el filtrado.
function seleccionCubreTodasLasTorres(seleccionProyectos, seleccionTorres) {{
    const disponibles = torresDisponibles(seleccionProyectos);
    return disponibles.length === seleccionTorres.length && disponibles.every(t => seleccionTorres.includes(t));
}}

function hayCoberturaHistorico(seleccionProyectos, seleccionTorres, filtroAtadas) {{
    return seleccionCubreTodasLasTorres(seleccionProyectos, seleccionTorres) && filtroAtadas === 'Todos';
}}

// --- Filtro de "Unidades atadas": independiente de la categoria (ver MATRIZ_CATEGORIA en
// Python) -- 'Todos' no filtra nada, 'Atadas' deja solo unidades_atadas === 1. Se aplica en
// TODO el dashboard (embudos, KPIs, graficas de categoria y tabla), igual que el de torre. ---
function filtroAtadasSeleccionado() {{
    return document.getElementById('filtroAtadas').value;
}}

function pasaFiltroAtadas(registro, filtroAtadas) {{
    return filtroAtadas === 'Atadas' ? registro.unidades_atadas === 1 : true;
}}

// --- "Corte anterior - Estado actual" (2da columna de "Clientes por categoría y mes
// proyectado", ver ESTADO_ACTUAL_CORTE_ANTERIOR): los mismos clientes no escriturados del
// corte de comité, reclasificados por su categoria/atadas DE HOY -- se busca por id_prospecto
// en CATEGORIA_TRAMITES (que ya trae el estado de hoy de TODOS los clientes). Si un
// id_prospecto ya no aparece ahi (ej. desistimiento), queda como "Desistidos". ---
const LOOKUP_CATEGORIA_HOY = {{}};
CATEGORIA_TRAMITES.forEach(c => {{ LOOKUP_CATEGORIA_HOY[c.id_prospecto] = c; }});

function estadoActualCategoria(idProspecto) {{
    const c = LOOKUP_CATEGORIA_HOY[idProspecto];
    return c ? c.categoria : 'Desistidos';
}}

function pasaFiltroAtadasHoy(idProspecto, filtroAtadas) {{
    const c = LOOKUP_CATEGORIA_HOY[idProspecto];
    if (!c) return filtroAtadas !== 'Atadas';
    return pasaFiltroAtadas(c, filtroAtadas);
}}

function granularidadSeleccionada() {{
    return document.getElementById('filtroComparativo').value;
}}

// --- Comparativo Semanal/Comité: elige, de las fechas de corte ya guardadas en el
// historico, la fecha contra la que se compara HOY (FECHA_CORTE, el corte de los datos, no
// la fecha real del navegador):
//   'semanal' -> la mas cercana a "hace 7 dias".
//   'comite' -> el corte de comite del mes (FECHA_CORTE_COMITE, ver data/referencia/
//                cortes_comite.csv), o si todavia no esta definido para este mes, cae al
//                automatico: el PRIMER corte guardado del mes en curso (o del mes anterior
//                con datos, si este mes todavia no tiene ninguno).
// ---
function restarDias(fechaStr, dias) {{
    const d = new Date(fechaStr + 'T00:00:00');
    d.setDate(d.getDate() - dias);
    return d.toISOString().slice(0, 10);
}}

function fechasDisponiblesHistorico(historico) {{
    return [...new Set(historico.map(p => String(p.fecha_corte)))];
}}

function fechaCorteAnteriorSegunVista(fechasDisponibles, granularidad) {{
    const fechas = fechasDisponibles.filter(f => f !== FECHA_CORTE).sort();
    if (fechas.length === 0) return null;

    if (granularidad === 'comite') {{
        // Corte de comite del mes (ver data/referencia/cortes_comite.csv): si esta definido
        // para este mes y existe en esta fuente de historico, gana sobre el calculo
        // automatico de mas abajo -- es la base real del comparativo comite.
        if (FECHA_CORTE_COMITE && fechas.includes(FECHA_CORTE_COMITE)) {{
            return FECHA_CORTE_COMITE;
        }}

        // Sin corte de comite definido para este mes (o no disponible en esta fuente en
        // particular): primer corte guardado con el mismo año-mes que FECHA_CORTE ('YYYY-MM').
        const mesActual = FECHA_CORTE.slice(0, 7);
        const delMesActual = fechas.filter(f => f.slice(0, 7) === mesActual);
        if (delMesActual.length) return delMesActual[0];

        // Si hoy es el primer corte del mes (todavia no hay otro este mes), se usa el primer
        // corte del mes mas reciente ANTERIOR que si tenga datos (ej. si hoy es 5-oct y el mes
        // aun no tiene ningun otro corte, se compara contra el primero de septiembre) -- apenas
        // exista un corte de este mes, el comparativo vuelve automaticamente a "desde el 1 de
        // este mes", sin necesidad de ningun ajuste manual.
        const mesesAnteriores = fechas.filter(f => f.slice(0, 7) < mesActual);
        if (mesesAnteriores.length === 0) return null;
        const ultimoMesConDatos = mesesAnteriores[mesesAnteriores.length - 1].slice(0, 7);
        return mesesAnteriores.find(f => f.slice(0, 7) === ultimoMesConDatos);
    }}

    // 'semanal': la fecha disponible mas reciente que sea <= "hace 7 dias"; si el historico
    // todavia es muy corto y ninguna califica, se usa la mas antigua disponible en vez de no
    // comparar contra nada.
    const objetivo = restarDias(FECHA_CORTE, 7);
    const candidatas = fechas.filter(f => f <= objetivo);
    return candidatas.length ? candidatas[candidatas.length - 1] : fechas[0];
}}

function clientesFunnelFiltrados(seleccionProyectos, seleccionTorres, filtroAtadas) {{
    return CLIENTES_FUNNEL.filter(c =>
        seleccionProyectos.includes(c.proyecto) && seleccionTorres.includes(c.torre) &&
        pasaFiltroAtadas(c, filtroAtadas)
    );
}}

function calcularMetricasFuncional(clientes, anio) {{
    const totalAptos = clientes.length;

    // Unidades ESCRITURADAS, filtradas por el año de la escritura REAL (anio_escritura) -- no
    // por el año proyectado, que casi nunca esta diligenciado para unidades ya escrituradas.
    let escrituradas = clientes.filter(c => c.escriturado === 1);
    if (anio !== '{TODOS}') escrituradas = escrituradas.filter(c => c.anio_escritura === anio);
    const nEscrituradas = escrituradas.length;

    let noEscriturados = clientes.filter(c => c.escriturado === 0);
    if (anio !== '{TODOS}') noEscriturados = noEscriturados.filter(c => c.anio === anio);
    const nNoEscriturados = noEscriturados.length;

    const reqSubsidio = noEscriturados.filter(c => c.subsidio === 1);
    const subsidioSinAprobar = reqSubsidio.filter(c => c.subsidio_aprobado === 0);
    const subsidioSinRadicar = subsidioSinAprobar.filter(c => c.subsidio_radicado === 0);

    const reqCredito = noEscriturados.filter(c => c.credito === 1);
    const creditoSinAprobar = reqCredito.filter(c => c.credito_aprobado === 0);
    const creditoSinRadicar = creditoSinAprobar.filter(c => c.credito_radicado === 0);

    return {{
        subsidio: [totalAptos, nNoEscriturados, reqSubsidio.length, subsidioSinAprobar.length, subsidioSinRadicar.length],
        credito: [totalAptos, nNoEscriturados, reqCredito.length, creditoSinAprobar.length, creditoSinRadicar.length],
        escrituradas: nEscrituradas,
    }};
}}

function sumarMetricas(seleccionProyectos, seleccionTorres, filtroAtadas, anio) {{
    return calcularMetricasFuncional(clientesFunnelFiltrados(seleccionProyectos, seleccionTorres, filtroAtadas), anio);
}}

// --- Nueva sección "Indicadores de Gestión": 5 indicadores independientes (una misma unidad puede
// contar en varios a la vez) sobre TODOS los clientes filtrados (escriturados o no, sin
// filtro de año -- ver comentario en Python junto a COLUMNAS_KPI_GESTION). ---
function actualizarKpisGestion(seleccionProyectos, seleccionTorres, filtroAtadas) {{
    const clientes = clientesFunnelFiltrados(seleccionProyectos, seleccionTorres, filtroAtadas);

    // A diferencia de las otras 2 comparaciones (que solo tienen historico "sin atadas" y por
    // eso exigen filtroAtadas === 'Todos'), aca hay una fuente de historico por cada valor del
    // filtro -- asi que la unica condicion para el comparativo es la cobertura de torre.
    const fuenteHistorico = filtroAtadas === 'Atadas' ? HISTORICO_KPI_GESTION_ATADAS_TODO : HISTORICO_KPI_GESTION_TODO;
    const cubreTodasLasTorres = seleccionCubreTodasLasTorres(seleccionProyectos, seleccionTorres);
    const granularidad = granularidadSeleccionada();
    const fechaAnterior = cubreTodasLasTorres
        ? fechaCorteAnteriorSegunVista(fechasDisponiblesHistorico(fuenteHistorico), granularidad)
        : null;
    const filasAnterior = fechaAnterior ? fuenteHistorico.filter(p =>
        String(p.fecha_corte) === fechaAnterior && seleccionProyectos.includes(p.proyecto)
    ) : [];

    // Estas tarjetas solo muestran la DIFERENCIA vs. el corte semanal/comite, no el
    // totalizado -- por eso, sin comparativo disponible (sin cobertura, o historico
    // insuficiente todavia), se deja un texto neutro en vez de un numero.
    KPIS_GESTION.forEach((kpi, idx) => {{
        const valor = clientes.filter(c => c[kpi.campoCliente] === 1).length;
        const elValor = document.getElementById('kpi-gestion-' + idx);
        if (!elValor) return;

        if (filasAnterior.length === 0) {{ elValor.textContent = 'Sin comparativo'; return; }}
        const anterior = filasAnterior.reduce((acc, p) => acc + (p[kpi.nombreHistorico] || 0), 0);
        const delta = valor - anterior;
        if (delta === 0) {{
            elValor.textContent = '● sin cambio';
        }} else {{
            const signo = delta > 0 ? '▲' : '▼';
            elValor.textContent = `${{signo}} ${{delta > 0 ? '+' : ''}}${{delta}}`;
        }}
    }});
}}

function actualizarBotonProyecto(seleccion) {{
    const boton = document.getElementById('btnFiltroProyecto');
    if (seleccion.length === TODOS_PROYECTOS.length) {{
        boton.textContent = 'Todos ▾';
    }} else if (seleccion.length === 1) {{
        boton.textContent = seleccion[0] + ' ▾';
    }} else if (seleccion.length === 0) {{
        boton.textContent = 'Ninguno ▾';
    }} else {{
        boton.textContent = seleccion.length + ' seleccionados ▾';
    }}
}}

function actualizarTabla(seleccionProyectos, seleccionTorres, filtroAtadas, anio) {{
    const filtrados = PENDIENTES.filter(p =>
        seleccionProyectos.includes(p.proyecto) && seleccionTorres.includes(p.torre) &&
        pasaFiltroAtadas(p, filtroAtadas) &&
        (anio === '{TODOS}' || p.anio === anio)
    );

    const tbody = document.getElementById('tablaPendientesBody');
    tbody.innerHTML = '';
    let grupoActual = null;
    filtrados.forEach(p => {{
        if (p.periodo !== grupoActual) {{
            grupoActual = p.periodo;
            const trGrupo = document.createElement('tr');
            trGrupo.className = 'grupo-mes';
            trGrupo.innerHTML = `<td colspan="5">${{p.periodo}}</td>`;
            tbody.appendChild(trGrupo);
        }}
        const tr = document.createElement('tr');
        const colorBadge = COLORES_CATEGORIA_TABLA[p.categoria] || '#999';
        tr.innerHTML = `<td>${{p.proyecto}}</td><td>${{p.modulo}}</td><td>${{p.cliente}}</td><td>${{p.motivo}}</td><td><span class="categoria-badge" style="background:${{colorBadge}}">${{p.categoria}}</span></td>`;
        tbody.appendChild(tr);
    }});
    document.getElementById('tablaContador').textContent = filtrados.length.toLocaleString('es-CO') + ' clientes pendientes';
}}

// --- Descarga de "no escriturados" segun el filtro activo (proyecto/torre/año/atadas) -- a
// diferencia de la tabla de arriba (que excluye a los "Listo"), esta descarga incluye a TODOS
// los no escriturados del filtro, con su categoria (subcategoria de detalle cuando aplica). ---
function _categoriaParaDescarga(p) {{
    return p.subcategoria || p.categoria;
}}

function _csvEscape(valor) {{
    const texto = String(valor == null ? '' : valor);
    if (/[",\\n]/.test(texto)) {{
        return '"' + texto.replace(/"/g, '""') + '"';
    }}
    return texto;
}}

function descargarNoEscriturados() {{
    const seleccionProyectos = proyectosSeleccionados();
    const seleccionTorres = torresSeleccionadas();
    const filtroAtadas = filtroAtadasSeleccionado();
    const anio = document.getElementById('filtroAnio').value;

    const filtrados = CATEGORIA_TRAMITES.filter(p =>
        seleccionProyectos.includes(p.proyecto) && seleccionTorres.includes(p.torre) &&
        pasaFiltroAtadas(p, filtroAtadas) &&
        (anio === '{TODOS}' || p.anio === anio)
    );

    const encabezados = ['Año-Mes Escrituración Programada', 'Proyecto', 'Módulo', 'Cliente', 'Categoría'];
    const filas = filtrados.map(p => [p.periodo, p.proyecto, p.modulo, p.cliente, _categoriaParaDescarga(p)]);

    // BOM al inicio para que Excel en Windows reconozca UTF-8 y muestre bien tildes/ñ (mismo
    // truco que utf-8-sig en los CSV que genera Python en el resto del pipeline).
    const lineas = [encabezados, ...filas].map(fila => fila.map(_csvEscape).join(','));
    const csv = '﻿' + lineas.join('\\r\\n');

    const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = `no_escriturados_${{FECHA_CORTE}}.csv`;
    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);
    URL.revokeObjectURL(url);
}}

function actualizarGraficaBarras(seleccionProyectos, seleccionTorres, filtroAtadas, anio) {{
    // Filtrar aptos no escriturados para cada proyecto en la selección actual (respetando
    // torre -- por eso ya no se usa el precalculo DATOS[proy][anio], que no tiene esa dimension).
    let items = seleccionProyectos.map(p => ({{
        proyecto: p,
        valor: calcularMetricasFuncional(clientesFunnelFiltrados([p], seleccionTorres, filtroAtadas), anio).subsidio[1]
    }}));

    // Orden ascendente para que en barra horizontal la barra más larga quede arriba
    items.sort((a, b) => a.valor - b.valor);

    const proyectos = items.map(d => d.proyecto);
    const valores = items.map(d => d.valor);

    Plotly.restyle('fig_proyecto', {{
        x: [valores],
        y: [proyectos],
        text: [valores]
    }}, [0]);

    // Reajustar altura dinámica para mantener proporciones limpias
    const nuevaAltura = Math.max(250, 60 + 35 * proyectos.length);
    Plotly.relayout('fig_proyecto', {{ height: nuevaAltura }});
}}

function _actualizarBarraApiladaPorMes(divId, filtrados, campo, ordenApilado, colores, tituloTexto) {{
    // Primera traza = base de la barra apilada (queda abajo).
    const legendRank = {{}};
    ordenApilado.forEach((c, i) => {{ legendRank[c] = i + 1; }});

    const periodos = [...new Set(filtrados.map(p => p.periodo))];
    const traces = ordenApilado.map(c => {{
        const valores = periodos.map(periodo =>
            filtrados.filter(p => p.periodo === periodo && p[campo] === c).length
        );
        return {{
            type: 'bar',
            name: c,
            x: periodos,
            y: valores,
            text: valores.map(v => v > 0 ? String(v) : ''),
            textposition: 'inside',
            insidetextanchor: 'middle',
            textangle: 0,
            textfont: {{ size: 11 }},
            marker: {{ color: colores[c] }},
            legendrank: legendRank[c]
        }};
    }});

    // Total de unidades a escriturar por mes, como rotulo encima de cada barra apilada.
    const anotacionesTotales = periodos.map(periodo => {{
        const total = filtrados.filter(p => p.periodo === periodo).length;
        return {{
            x: periodo, y: total, text: `<b>${{total}}</b>`, showarrow: false, yshift: 10,
            font: {{ color: '{COLOR_VERDE_OSCURO}', size: 13 }}
        }};
    }});

    const layout = {{
        barmode: 'stack',
        title: tituloTexto,
        xaxis: {{ title: 'Mes de escrituración' }},
        yaxis: {{ title: 'Cantidad de clientes' }},
        legend: {{ title: {{ text: 'Categoría' }} }},
        margin: {{ t: 60, b: 40, l: 40, r: 20 }},
        height: 430,
        template: 'plotly_white',
        annotations: anotacionesTotales
    }};

    Plotly.react(divId, traces, layout);
}}

function _actualizarCategoriaPrincipalConComparativo(divId, actualFiltrado, anteriorFiltrado, estadoActualFiltrado, fechaAnterior, ordenApilado, colores, tituloTexto) {{
    // Primera traza = base de la barra apilada (queda abajo).
    const legendRank = {{}};
    ordenApilado.forEach((c, i) => {{ legendRank[c] = i + 1; }});

    // Periodos de los 3 cortes, en orden cronologico (campo 'orden' de cada registro). Si un
    // mes solo existe en el corte anterior (ya no quedan clientes ahi hoy), igual se muestra
    // para no perder la comparacion.
    const ordenPorPeriodo = {{}};
    actualFiltrado.forEach(p => {{ ordenPorPeriodo[p.periodo] = p.orden; }});
    anteriorFiltrado.forEach(p => {{ if (!(p.periodo in ordenPorPeriodo)) ordenPorPeriodo[p.periodo] = p.orden; }});
    estadoActualFiltrado.forEach(p => {{ if (!(p.periodo in ordenPorPeriodo)) ordenPorPeriodo[p.periodo] = p.orden; }});
    const periodos = Object.keys(ordenPorPeriodo).sort((a, b) => ordenPorPeriodo[a] - ordenPorPeriodo[b]);

    const hayComparativo = anteriorFiltrado.length > 0;

    if (!hayComparativo) {{
        // Sin corte anterior disponible todavia (ej. primer dia de este esquema): barra
        // simple por mes, igual que antes de tener comparativo.
        const traces = ordenApilado.map(c => {{
            const valores = periodos.map(periodo =>
                actualFiltrado.filter(p => p.periodo === periodo && p.categoria === c).length
            );
            return {{
                type: 'bar', name: c, x: periodos, y: valores,
                text: valores.map(v => v > 0 ? String(v) : ''),
                textposition: 'inside', insidetextanchor: 'middle', textangle: 0,
                textfont: {{ size: 11 }}, marker: {{ color: colores[c] }}, legendrank: legendRank[c]
            }};
        }});
        const anotacionesTotales = periodos.map(periodo => {{
            const total = actualFiltrado.filter(p => p.periodo === periodo).length;
            return {{
                x: periodo, y: total, text: `<b>${{total}}</b>`, showarrow: false, yshift: 10,
                font: {{ color: '{COLOR_VERDE_OSCURO}', size: 13 }}
            }};
        }});
        Plotly.react(divId, traces, {{
            barmode: 'stack', title: tituloTexto,
            xaxis: {{ title: 'Mes de escrituración' }}, yaxis: {{ title: 'Cantidad de clientes' }},
            legend: {{ title: {{ text: 'Categoría' }} }}, margin: {{ t: 60, b: 40, l: 40, r: 20 }},
            height: 430, template: 'plotly_white', annotations: anotacionesTotales
        }});
        return;
    }}

    const hayEstadoActual = estadoActualFiltrado.length > 0;

    // Con comparativo: eje x de 2 (o 3, si hay "Corte anterior - Estado actual") niveles (mes,
    // grupo), lado a lado dentro de cada mes, cada uno apilado por categoria.
    const grupoActual = 'Hoy';
    const grupoAnterior = `Corte anterior (${{fechaAnterior}})`;
    const grupoEstadoActual = `Corte anterior (${{fechaAnterior}}) - Estado actual`;

    const nivel0 = [];
    const nivel1 = [];
    const opacidades = [];
    const bordeAncho = [];
    const bordeColor = [];
    const etiquetasHover = [];
    periodos.forEach(periodo => {{
        nivel0.push(periodo, periodo);
        // "Corte anterior" va primero, "Hoy" al final -- misma lectura izquierda->derecha que
        // el orden cronologico (lo viejo antes que lo nuevo). Si hay "Estado actual" va en medio:
        // mismos clientes del corte anterior, pero con su categoria de hoy.
        // El segundo nivel del eje x se deja en blanco (valores distintos pero invisibles, para
        // que Plotly siga separando las barras de cada mes): en el eje solo se ve el mes, y el
        // detalle de cada grupo queda en el hover (ver mas abajo).
        if (hayEstadoActual) {{
            nivel0.push(periodo);
            nivel1.push('', ' ', '  ');
            // Mismo relleno (color y opacidad) que "Corte anterior" -- se distingue solo por un
            // borde solido (Plotly no soporta borde punteado en barras: 'dash' se ignora y
            // queda solido, y una trama de relleno tapaba los numeros).
            opacidades.push(0.45, 0.45, 1);
            bordeAncho.push(0, 1.5, 0);
            bordeColor.push('rgba(0,0,0,0)', '#3a3a3a', 'rgba(0,0,0,0)');
            etiquetasHover.push(
                `${{periodo}} · ${{grupoAnterior}}`,
                `${{periodo}} · ${{grupoEstadoActual}}`,
                `${{periodo}} · ${{grupoActual}}`
            );
        }} else {{
            nivel1.push('', ' ');
            opacidades.push(0.45, 1);
            bordeAncho.push(0, 0);
            bordeColor.push('rgba(0,0,0,0)', 'rgba(0,0,0,0)');
            etiquetasHover.push(`${{periodo}} · ${{grupoAnterior}}`, `${{periodo}} · ${{grupoActual}}`);
        }}
    }});

    const traces = ordenApilado.map(c => {{
        const valores = [];
        periodos.forEach(periodo => {{
            const suma = anteriorFiltrado
                .filter(p => p.periodo === periodo)
                .reduce((acc, p) => acc + (p[c] || 0), 0);
            valores.push(suma);
            if (hayEstadoActual) {{
                valores.push(estadoActualFiltrado.filter(p => p.periodo === periodo && p.categoria === c).length);
            }}
            valores.push(actualFiltrado.filter(p => p.periodo === periodo && p.categoria === c).length);
        }});
        return {{
            type: 'bar', name: c, x: [nivel0, nivel1], y: valores,
            text: valores.map(v => v > 0 ? String(v) : ''),
            textposition: 'inside', insidetextanchor: 'middle', textangle: 0,
            textfont: {{ size: 11 }},
            marker: {{ color: colores[c], opacity: opacidades, line: {{ width: bordeAncho, color: bordeColor }} }},
            legendrank: legendRank[c],
            customdata: etiquetasHover,
            hovertemplate: '%{{customdata}}<br>' + c + ': %{{y}}<extra></extra>'
        }};
    }});

    const anotacionesTotales = [];
    periodos.forEach(periodo => {{
        const totalActual = actualFiltrado.filter(p => p.periodo === periodo).length;
        const totalAnterior = anteriorFiltrado
            .filter(p => p.periodo === periodo)
            .reduce((acc, p) => acc + ordenApilado.reduce((s, c) => s + (p[c] || 0), 0), 0);
        anotacionesTotales.push({{
            x: [periodo, hayEstadoActual ? '  ' : ' '], y: totalActual, text: `<b>${{totalActual}}</b>`, showarrow: false,
            yshift: 10, font: {{ color: '{COLOR_VERDE_OSCURO}', size: 13 }}
        }});
        anotacionesTotales.push({{
            x: [periodo, ''], y: totalAnterior, text: `<b>${{totalAnterior}}</b>`, showarrow: false,
            yshift: 10, font: {{ color: '#888', size: 13 }}
        }});
        if (hayEstadoActual) {{
            const totalEstadoActual = estadoActualFiltrado.filter(p => p.periodo === periodo).length;
            anotacionesTotales.push({{
                x: [periodo, ' '], y: totalEstadoActual, text: `<b>${{totalEstadoActual}}</b>`, showarrow: false,
                yshift: 10, font: {{ color: '#555', size: 13 }}
            }});
        }}
    }});

    Plotly.react(divId, traces, {{
        barmode: 'stack', title: tituloTexto,
        xaxis: {{ title: 'Mes de escrituración' }}, yaxis: {{ title: 'Cantidad de clientes' }},
        legend: {{ title: {{ text: 'Categoría' }} }}, margin: {{ t: 60, b: 40, l: 40, r: 20 }},
        height: 430, template: 'plotly_white', annotations: anotacionesTotales
    }});
}}

function actualizarGraficaCategoriaPrincipal(seleccionProyectos, seleccionTorres, filtroAtadas, anio) {{
    const filtrados = CATEGORIA_TRAMITES.filter(p =>
        seleccionProyectos.includes(p.proyecto) && seleccionTorres.includes(p.torre) &&
        pasaFiltroAtadas(p, filtroAtadas) &&
        (anio === '{TODOS}' || p.anio === anio)
    );
    // El historico no tiene desglose por torre ni por unidades atadas -- si cualquiera de los
    // 2 filtros deja fuera algo, se omite el comparativo (cae al fallback de barra simple
    // dentro de _actualizarCategoriaPrincipalConComparativo).
    const cubreTodo = hayCoberturaHistorico(seleccionProyectos, seleccionTorres, filtroAtadas);
    const granularidad = granularidadSeleccionada();
    const fechaAnterior = cubreTodo
        ? fechaCorteAnteriorSegunVista(fechasDisponiblesHistorico(HISTORICO_CATEGORIA_TODO), granularidad)
        : null;
    const anteriorFiltrado = fechaAnterior ? HISTORICO_CATEGORIA_TODO.filter(p =>
        String(p.fecha_corte) === fechaAnterior &&
        seleccionProyectos.includes(p.proyecto) &&
        (anio === '{TODOS}' || p.anio === anio)
    ) : [];

    // "Corte anterior - Estado actual": solo tiene sentido cuando el corte anterior mostrado
    // ES el corte de comité (ESTADO_ACTUAL_CORTE_ANTERIOR viene de ese snapshot exacto -- ver
    // _tabla_estado_actual_corte_anterior en Python). Si la vista esta en "Semanal" o el corte
    // anterior cae en otra fecha, esta 2da columna no aplica y se omite.
    const estadoActualFiltrado = (fechaAnterior && FECHA_CORTE_COMITE && fechaAnterior === FECHA_CORTE_COMITE)
        ? ESTADO_ACTUAL_CORTE_ANTERIOR.filter(p =>
            seleccionProyectos.includes(p.proyecto) && seleccionTorres.includes(p.torre) &&
            (anio === '{TODOS}' || p.anio === anio) &&
            pasaFiltroAtadasHoy(p.id_prospecto, filtroAtadas)
        ).map(p => ({{ periodo: p.periodo, orden: p.orden, categoria: estadoActualCategoria(p.id_prospecto) }}))
        : [];

    const ordenApiladoChart = estadoActualFiltrado.length > 0
        ? ORDEN_CATEGORIA_PRINCIPAL.concat(['Desistidos'])
        : ORDEN_CATEGORIA_PRINCIPAL;
    const coloresChart = estadoActualFiltrado.length > 0
        ? {{ ...COLORES_CATEGORIA_PRINCIPAL, 'Desistidos': '{COLOR_FUERA_REPORTE}' }}
        : COLORES_CATEGORIA_PRINCIPAL;

    _actualizarCategoriaPrincipalConComparativo(
        'fig_categoria_principal', filtrados, anteriorFiltrado, estadoActualFiltrado, fechaAnterior,
        ordenApiladoChart, coloresChart,
        'Clientes por categoría y mes proyectado'
    );
}}

function actualizarGraficaSubcategoriaGestion(seleccionProyectos, seleccionTorres, filtroAtadas, anio) {{
    // Todo lo que no es ni 'Sin Radicados' ni 'Listo' (tiene subcategoria asignada).
    const filtrados = CATEGORIA_TRAMITES.filter(p =>
        seleccionProyectos.includes(p.proyecto) && seleccionTorres.includes(p.torre) &&
        pasaFiltroAtadas(p, filtroAtadas) &&
        (anio === '{TODOS}' || p.anio === anio) &&
        p.subcategoria
    );
    _actualizarBarraApiladaPorMes(
        'fig_subcategoria_gestion', filtrados, 'subcategoria',
        ORDEN_SUBCATEGORIA_GESTION, COLORES_SUBCATEGORIA_GESTION,
        'Detalle de combinación Subsidio/Crédito por mes proyectado'
    );
}}

function actualizarDeltasKpi(seleccionProyectos, seleccionTorres, filtroAtadas, anio, kpis) {{
    const limpiar = () => IDS_KPI.forEach(idx => {{
        const el = document.getElementById('kpi-delta-' + idx);
        if (el) el.textContent = '';
    }});

    // Igual que en la grafica de categoria: el historico de KPI no tiene desglose por torre ni
    // por unidades atadas, asi que la variacion solo se muestra con cobertura completa de
    // ambos filtros.
    if (!hayCoberturaHistorico(seleccionProyectos, seleccionTorres, filtroAtadas)) {{
        limpiar();
        return null;
    }}

    const granularidad = granularidadSeleccionada();
    const fechaAnterior = fechaCorteAnteriorSegunVista(fechasDisponiblesHistorico(HISTORICO_KPI_TODO), granularidad);
    if (!fechaAnterior) {{
        limpiar();
        return null;
    }}

    // El historico de KPI guarda una fila por proyecto y por cada año (incluido 'Todos'), asi
    // que el filtro de año se compara igual que en DATOS -- sin necesidad de un caso especial
    // para 'Todos'.
    const filasAnterior = HISTORICO_KPI_TODO.filter(p =>
        String(p.fecha_corte) === fechaAnterior && seleccionProyectos.includes(p.proyecto) && p.anio === anio
    );
    if (filasAnterior.length === 0) {{
        limpiar();
        return null;
    }}

    IDS_KPI.forEach((idx, pos) => {{
        const indicador = NOMBRES_KPI_HISTORICO[idx];
        const anterior = filasAnterior.reduce((acc, p) => acc + (p[indicador] || 0), 0);
        const el = document.getElementById('kpi-delta-' + idx);
        if (!el) return;

        const delta = kpis[pos] - anterior;
        if (delta === 0) {{
            el.textContent = '● sin cambio';
        }} else {{
            const signo = delta > 0 ? '▲' : '▼';
            el.textContent = `${{signo}} ${{delta > 0 ? '+' : ''}}${{delta}}`;
        }}
    }});
    return fechaAnterior;
}}

function actualizarNotaCorteAnterior(fechaAnterior) {{
    const el = document.getElementById('notaCorteAnterior');
    if (!el) return;
    el.textContent = fechaAnterior ? ` · Variación calculada contra el corte del ${{fechaAnterior}}` : '';
}}

function actualizar() {{
    const seleccionProyectos = proyectosSeleccionados();
    const seleccionTorres = torresSeleccionadas();
    const filtroAtadas = filtroAtadasSeleccionado();
    const anio = document.getElementById('filtroAnio').value;
    const m = sumarMetricas(seleccionProyectos, seleccionTorres, filtroAtadas, anio);

    // 1. Actualizar Embudos
    Plotly.restyle('fig_subsidio', {{x: [m.subsidio]}}, [0]);
    Plotly.restyle('fig_credito', {{x: [m.credito]}}, [0]);

    // 2. Actualizar Gráfica de Barras por Proyecto
    actualizarGraficaBarras(seleccionProyectos, seleccionTorres, filtroAtadas, anio);

    // 3. Actualizar Gráfica de categorías por mes (principal + detalle)
    actualizarGraficaCategoriaPrincipal(seleccionProyectos, seleccionTorres, filtroAtadas, anio);
    actualizarGraficaSubcategoriaGestion(seleccionProyectos, seleccionTorres, filtroAtadas, anio);

    // 4. Actualizar KPIs
    // OJO: los ids de las tarjetas no son consecutivos (falta kpi-4), por eso se usa
    // IDS_KPI en vez del indice del forEach para saber a que tarjeta va cada valor.
    // kpi-0 usa m.escrituradas (Total Unidades Escrituradas), no m.subsidio[0] (eso sigue
    // siendo "Vendidos" -- la base del embudo, que no cambio).
    const kpis = [m.escrituradas, m.subsidio[1], m.subsidio[2], m.subsidio[3], m.credito[2], m.credito[3]];
    kpis.forEach((v, pos) => {{
        const el = document.getElementById('kpi-' + IDS_KPI[pos]);
        if (el) el.textContent = v.toLocaleString('es-CO');
    }});

    // 4b. Variacion vs. el corte semanal/comite (si aplica -- ver hayCoberturaHistorico).
    const fechaAnteriorKpi = actualizarDeltasKpi(seleccionProyectos, seleccionTorres, filtroAtadas, anio, kpis);
    actualizarNotaCorteAnterior(fechaAnteriorKpi);

    // 4c. Nueva sección "Indicadores de Gestión" (valor + variacion semanal/comite).
    actualizarKpisGestion(seleccionProyectos, seleccionTorres, filtroAtadas);

    // 5. Actualizar Estado de Controles y Tabla
    actualizarBotonProyecto(seleccionProyectos);
    actualizarBotonTorre(seleccionProyectos, seleccionTorres);
    actualizarTabla(seleccionProyectos, seleccionTorres, filtroAtadas, anio);
}}

// Al cambiar el proyecto, el panel de torre se rearma (torres del/de los proyecto(s) nuevo(s),
// todas marcadas) antes de recalcular todo -- por eso estos 3 disparadores usan este wrapper
// en vez de llamar actualizar() directo.
function alCambiarProyecto() {{
    renderizarPanelTorres(proyectosSeleccionados());
    actualizar();
}}

document.getElementById('filtroAnio').addEventListener('change', actualizar);
document.getElementById('filtroAtadas').addEventListener('change', actualizar);
document.getElementById('filtroComparativo').addEventListener('change', actualizar);
document.getElementById('btnDescargarNoEscriturados').addEventListener('click', descargarNoEscriturados);

document.querySelectorAll('.chk-proyecto').forEach(chk => chk.addEventListener('change', alCambiarProyecto));

document.getElementById('lnkTodosProyectos').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = true);
    alCambiarProyecto();
}});
document.getElementById('lnkNingunProyecto').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = false);
    alCambiarProyecto();
}});

const btnFiltroProyecto = document.getElementById('btnFiltroProyecto');
const panelFiltroProyecto = document.getElementById('panelFiltroProyecto');
btnFiltroProyecto.addEventListener('click', (ev) => {{
    ev.stopPropagation();
    panelFiltroProyecto.style.display = (panelFiltroProyecto.style.display === 'none') ? 'block' : 'none';
}});

const btnFiltroTorre = document.getElementById('btnFiltroTorre');
const panelFiltroTorre = document.getElementById('panelFiltroTorre');
btnFiltroTorre.addEventListener('click', (ev) => {{
    ev.stopPropagation();
    panelFiltroTorre.style.display = (panelFiltroTorre.style.display === 'none') ? 'block' : 'none';
}});
document.getElementById('lnkTodosTorres').addEventListener('click', () => {{
    document.querySelectorAll('.chk-torre').forEach(c => c.checked = true);
    actualizar();
}});
document.getElementById('lnkNingunaTorre').addEventListener('click', () => {{
    document.querySelectorAll('.chk-torre').forEach(c => c.checked = false);
    actualizar();
}});

document.addEventListener('click', (ev) => {{
    if (!panelFiltroProyecto.contains(ev.target) && ev.target !== btnFiltroProyecto) {{
        panelFiltroProyecto.style.display = 'none';
    }}
    if (!panelFiltroTorre.contains(ev.target) && ev.target !== btnFiltroTorre) {{
        panelFiltroTorre.style.display = 'none';
    }}
}});

// Renderizado inicial: primero arma el panel de torre para los proyectos ya marcados
// (todos, por defecto), despues calcula todo lo demas.
renderizarPanelTorres(proyectosSeleccionados());
actualizar();
</script>

</body>
</html>"""

    os.makedirs(RUTA_REPORTES, exist_ok=True)
    fecha_archivo = datetime.now().strftime('%Y%m%d')
    ruta_salida = os.path.join(RUTA_REPORTES, f"informe_escrituracion_{fecha_archivo}.html")
    with open(ruta_salida, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Informe generado en {ruta_salida}")

    # Genera los CSV de detalle para IA (ver generar_detalle_ia.py) como parte normal de cada
    # actualizacion del dashboard -- import local (no al inicio del archivo) porque ese script
    # a su vez importa este modulo (6_dashboard) para reusar _clasificar_tramites; haciendolo
    # aca, cuando run() ya esta siendo llamado, 6_dashboard.py ya termino de cargar por completo
    # y no hay problema de import circular.
    try:
        import generar_detalle_ia
        generar_detalle_ia.run()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudieron generar los CSV de detalle para IA ({e}). "
              "El informe HTML no se ve afectado.")

    return ruta_salida


if __name__ == "__main__":
    run()