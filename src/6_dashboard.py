import json
import os
from collections import defaultdict
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from api_utils import RUTA_ANALYTICS, RUTA_REPORTES, RUTA_HISTORICO, ANIO_OBJETIVO_ESCRITURA

# --- Paleta base: un color con nombre por cada significado, usado en todo el archivo. ---
# Cambiar un color de verdad es cambiar UNA sola linea aca; todo lo demas abajo son mapas
# de "etiqueta -> color de esta paleta", no colores nuevos.
COLOR_VERDE = '#2E8B45'           # bien / listo
COLOR_VERDE_OSCURO = '#1B5E20'    # texto y acentos (titulos, encabezados)
COLOR_PENDIENTE = '#E8A33D'       # ambar -- pendiente / en gestion (embudos y categorias)
COLOR_ROJO = '#C62828'            # mal -- sin cartas / sin avance
COLOR_MORADO = '#6A1B9A'          # bloqueo -- unidad atada
COLOR_AZUL = '#1f77b4'            # informativo -- en aprobaciones / no escriturados
COLOR_GRIS = '#C3C2B7'            # gris neutro, para texto secundario
COLOR_CARBON = '#2C2C2A'        # terracota -- pendiente radicar credito

TODOS = 'Todos'

# Esquema de 3 categorias para "Clientes por categoria y mes proyectado" (independiente del
# esquema de 6 categorias de arriba). Orden: mejor (bottom del apilado) -> peor (top).
ORDEN_CATEGORIA_PRINCIPAL = ['Listos', 'En Gestión', 'Sin Cartas']
COLORES_CATEGORIA_PRINCIPAL = {
    'Listos': COLOR_VERDE_OSCURO,
    'En Gestión': COLOR_PENDIENTE,
    'Sin Cartas': COLOR_ROJO,
}

# Subcategorias del detalle de "En Gestión". "Unidad Atada" va primero (base/piso de la
# barra apilada) porque es un bloqueo de identificacion aparte, no un tema de avance de
# subsidio/credito. "Pendiente radicar subsidio" usa el mismo ambar que "En Gestión" para
# relacionarla visualmente con esa categoria.
ORDEN_SUBCATEGORIA_GESTION = ['Unidad Atada', 'En aprobaciones', 'Pendiente radicar subsidio', 'Pendiente radicar crédito']
COLORES_SUBCATEGORIA_GESTION = {
    'Unidad Atada': COLOR_CARBON,
    'En aprobaciones': COLOR_GRIS,
    'Pendiente radicar subsidio': COLOR_MORADO,
    'Pendiente radicar crédito': COLOR_AZUL,
}

# Colores para los badges de la tabla de "Clientes pendientes de aprobación": mismas
# categorias que la seccion de "en gestion" (subcategorias) + "Sin Cartas" para los que
# todavia no tienen ni una radicacion.
COLORES_CATEGORIA_TABLA = {**COLORES_SUBCATEGORIA_GESTION, 'Sin Cartas': COLOR_ROJO}

ETAPAS_SUBSIDIO = ['Vendidos', 'No escriturados', 'Requieren subsidio', 'Subsidio sin aprobar', 'Subsidio sin radicar']
ETAPAS_CREDITO = ['Vendidos', 'No escriturados', 'Requieren crédito', 'Crédito sin aprobar', 'Crédito sin radicar']

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _calcular_metricas(df_proyecto, anio):
    """Métricas de los dos embudos para un subconjunto ya filtrado por proyecto y un año dado."""
    total_aptos = len(df_proyecto)

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
    }


def _motivo_pendiente(row):
    partes = []
    if row['subsidio'] == 1 and row['subsidio_aprobado'] == 0:
        partes.append('Subsidio')
    if row['credito'] == 1 and row['credito_aprobado'] == 0:
        partes.append('Crédito')
    return ' y '.join(partes)


def _tabla_pendientes(df):
    """Clientes no escriturados con subsidio y/o crédito pendiente de aprobar."""
    no_esc = df[df['escriturado'] == 0].copy()
    pend_subsidio = (no_esc['subsidio'] == 1) & (no_esc['subsidio_aprobado'] == 0)
    pend_credito = (no_esc['credito'] == 1) & (no_esc['credito_aprobado'] == 0)
    pendientes = no_esc[pend_subsidio | pend_credito].copy()

    registros = []
    for _, r in pendientes.iterrows():
        anio_val = r['escritura_programada_anio']
        mes_val = r['escritura_programada_mes']
        if pd.isna(anio_val) or pd.isna(mes_val):
            anio_str, orden, periodo = None, 999999, 'Sin fecha proyectada'
        else:
            anio_str = str(int(anio_val))
            orden = int(anio_val) * 100 + int(mes_val)
            periodo = f"{MESES[int(mes_val)]} {anio_str}"

        cliente = f"{str(r['nombre'] or '').strip()} {str(r['apellido'] or '').strip()}".strip()
        # La categoria que se muestra en la tabla usa el mismo esquema que la seccion "en
        # gestion": si el cliente cae en "En Gestión", se muestra su subcategoria puntual
        # (Unidad Atada / En aprobaciones / Pendiente radicar subsidio o crédito) en vez del
        # nombre generico "En Gestión". Si no, se muestra la categoria principal (Sin Cartas
        # -- nunca deberia salir "Listos" aqui, porque estos clientes SI tienen algo pendiente).
        categoria_principal, subcategoria = _clasificar_tramites(r)
        categoria_mostrar = subcategoria if categoria_principal == 'En Gestión' else categoria_principal
        registros.append({
            'proyecto': r['proyecto'],
            'anio': anio_str,
            'modulo': r['modulo'],
            'cliente': cliente,
            'motivo': _motivo_pendiente(r),
            'categoria': categoria_mostrar,
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


def _estado_tramite(necesita, aprobado, radicado):
    """
    Estado de un tramite (subsidio o credito), como valor ordinal:
        2 = aprobado, o no se requiere (regla base: lo que no se requiere cuenta como ya
            resuelto, no hay nada que gestionar ahi).
        1 = radicado, pendiente de aprobar.
        0 = sin radicar (no ha arrancado nada).
    """
    if not necesita or aprobado:
        return 2
    if radicado:
        return 1
    return 0


def _clasificar_tramites(row):
    """
    Clasifica a un cliente en 3 categorias -- 'Listos', 'Sin Cartas' o 'En Gestión' -- y, si
    queda en 'En Gestión', ademas en una subcategoria. El orden de las preguntas importa:

    0) ¿la unidad esta atada (identificacion no coincide con estado_cuentas)? Si es asi, es
       un bloqueo que no tiene que ver con el avance de subsidio/credito -- entra directo a
       "En Gestión", subcategoria "Unidad Atada".
    1) ¿todo aprobado (o no se requiere)? -> Listos. Aqui entra tambien el cliente de
       contado, que no requiere ni subsidio ni credito.
    2) ¿no hay ni una sola radicacion de lo que SI se requiere? -> Sin Cartas.
    3) lo demas -> En Gestión, con subcategoria segun cual tramite le falta radicar
       (nunca faltan los dos a la vez dentro de "En Gestión": si faltaran los dos, seria
       "Sin Cartas" por el punto 2).

    Retorna (categoria, subcategoria) -- subcategoria es None si categoria no es 'En Gestión'.
    """
    if bool(row.get('unidades_atadas', 0) == 1):
        return 'En Gestión', 'Unidad Atada'

    necesita_subsidio = bool(row.get('subsidio', 0) == 1)
    necesita_credito = bool(row.get('credito', 0) == 1)
    e_subsidio = _estado_tramite(necesita_subsidio, row.get('subsidio_aprobado', 0) == 1, row.get('subsidio_radicado', 0) == 1)
    e_credito = _estado_tramite(necesita_credito, row.get('credito_aprobado', 0) == 1, row.get('credito_radicado', 0) == 1)

    if e_subsidio == 2 and e_credito == 2:
        return 'Listos', None

    nada_radicado = (not necesita_subsidio or e_subsidio == 0) and (not necesita_credito or e_credito == 0)
    if nada_radicado:
        return 'Sin Cartas', None

    if necesita_credito and e_credito == 0:
        subcategoria = 'Pendiente radicar crédito'
    elif necesita_subsidio and e_subsidio == 0:
        subcategoria = 'Pendiente radicar subsidio'
    else:
        subcategoria = 'En aprobaciones'
    return 'En Gestión', subcategoria


def _tabla_categoria_tramites(df):
    """
    Registros (uno por cliente no escriturado) con la categoria/subcategoria de avance de
    tramites (ver _clasificar_tramites). Incluye tambien a los clientes que no requieren ni
    subsidio ni credito (cliente de contado), porque la regla los clasifica como 'Listos' de
    entrada.
    """
    no_esc = df[df['escriturado'] == 0].copy()

    registros = []
    for _, r in no_esc.iterrows():
        anio_val = r['escritura_programada_anio']
        mes_val = r['escritura_programada_mes']
        if pd.isna(anio_val) or pd.isna(mes_val):
            anio_str, orden, periodo = None, 999999, 'Sin fecha proyectada'
        else:
            anio_str = str(int(anio_val))
            orden = int(anio_val) * 100 + int(mes_val)
            periodo = f"{MESES[int(mes_val)]} {anio_str}"

        categoria, subcategoria = _clasificar_tramites(r)
        registros.append({
            'proyecto': r['proyecto'],
            'anio': anio_str,
            'categoria': categoria,
            'subcategoria': subcategoria,
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


# Columnas del historico de categorias por mes proyectado (para el comparativo de "corte
# anterior" en la grafica "Clientes por categoría y mes proyectado"). Granularidad: una fila
# por proyecto + año (del cliente) + mes proyectado -- no hace falta por cliente, solo los
# totales de las 3 categorias principales.
COLUMNAS_HISTORICO_CATEGORIA = [
    'fecha_corte', 'proyecto', 'anio', 'periodo', 'orden', 'Listos', 'En Gestión', 'Sin Cartas',
]


def _tabla_historico_categoria_principal(categoria_tramites):
    """Agrega los registros (uno por cliente) de _tabla_categoria_tramites en conteos de las
    3 categorias principales por proyecto + año + mes proyectado."""
    conteos = defaultdict(lambda: defaultdict(int))
    ordenes = {}
    for r in categoria_tramites:
        clave = (r['proyecto'], r['anio'], r['periodo'])
        conteos[clave][r['categoria']] += 1
        ordenes[clave] = r['orden']

    filas = []
    for (proyecto, anio, periodo), cats in conteos.items():
        filas.append({
            'proyecto': proyecto,
            'anio': anio,
            'periodo': periodo,
            'orden': ordenes[(proyecto, anio, periodo)],
            'Listos': cats.get('Listos', 0),
            'En Gestión': cats.get('En Gestión', 0),
            'Sin Cartas': cats.get('Sin Cartas', 0),
        })
    return filas


def _guardar_historico_categoria_principal(categoria_tramites, fecha_corte):
    """
    Agrega al historico (data/historico/indicadores_por_proyecto.csv) una fila por proyecto +
    año + mes proyectado con el conteo de hoy de las 3 categorias principales (Listos / En
    Gestión / Sin Cartas). Sirve para el comparativo "corte anterior" que se agrega a la
    grafica "Clientes por categoría y mes proyectado" (ver JS mas abajo).

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
        # El esquema anterior (6 categorias, sin desglose por mes proyectado) es incompatible
        # con este -- se descarta en vez de migrarse, porque no hay forma de reconstruir el
        # desglose mensual de corridas pasadas a partir de esos totales agregados.
        if 'periodo' not in existente.columns:
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
    'Requieren crédito', 'Crédito sin aprobar',
]


def _fila_historico_kpi(proy, datos, anio):
    """Los 6 KPI que se muestran en las tarjetas, para un proyecto y un año (u 'Todos')."""
    s = datos[proy][anio]['subsidio']
    c = datos[proy][anio]['credito']
    return {
        'Vendidos': s[0],
        'No escriturados': s[1],
        'Requieren subsidio': s[2],
        'Subsidio sin aprobar': s[3],
        'Requieren crédito': c[2],
        'Crédito sin aprobar': c[3],
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
    for m in lista_metricas:
        subsidio = [a + b for a, b in zip(subsidio, m['subsidio'])]
        credito = [a + b for a, b in zip(credito, m['credito'])]
    return {'subsidio': subsidio, 'credito': credito}


def run():
    ruta_csv = os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv")
    df = pd.read_csv(ruta_csv)
    fecha_corte = df['fecha_corte'].iloc[0] if 'fecha_corte' in df.columns and len(df) else datetime.now().strftime('%Y-%m-%d')

    proyectos = sorted(df['proyecto'].dropna().unique().tolist())
    anios_presentes = sorted({int(a) for a in df['escritura_programada_anio'].dropna().unique()})
    opciones_anio = [TODOS] + [str(a) for a in anios_presentes]
    anio_defecto = str(ANIO_OBJETIVO_ESCRITURA) if str(ANIO_OBJETIVO_ESCRITURA) in opciones_anio else TODOS

    # Métricas de los embudos por cada (proyecto, año)
    datos = {}
    for proy in proyectos:
        df_proy = df[df['proyecto'] == proy]
        datos[proy] = {anio: _calcular_metricas(df_proy, anio) for anio in opciones_anio}

    pendientes = _tabla_pendientes(df)
    categoria_tramites = _tabla_categoria_tramites(df)

    # Guarda el corte de hoy en el historico y recupera el corte anterior (si existe) para el
    # comparativo de la grafica "Clientes por categoría y mes proyectado" (ver JS mas abajo).
    ruta_historico_cat = _guardar_historico_categoria_principal(categoria_tramites, fecha_corte)
    hist_cat = pd.read_csv(ruta_historico_cat, encoding='utf-8-sig')
    hist_cat['proyecto'] = hist_cat['proyecto'].astype(str).str.strip()
    # 'anio' vuelve del CSV como float (ej. 2026.0, o NaN para "Sin fecha proyectada") -- se
    # normaliza a string para que las comparaciones "===" contra el filtro de año en JS
    # (siempre string, viene del <select>) funcionen igual que con CATEGORIA_TRAMITES.
    hist_cat['anio'] = hist_cat['anio'].apply(lambda v: None if pd.isna(v) else str(int(v)))
    fechas_hist_cat = sorted(hist_cat['fecha_corte'].astype(str).unique().tolist())
    fecha_corte_anterior = fechas_hist_cat[-2] if len(fechas_hist_cat) >= 2 else None
    if fecha_corte_anterior:
        columnas_comparativo = ['proyecto', 'anio', 'periodo', 'orden', 'Listos', 'En Gestión', 'Sin Cartas']
        historico_categoria_anterior = (
            hist_cat[hist_cat['fecha_corte'].astype(str) == fecha_corte_anterior][columnas_comparativo]
            .to_dict('records')
        )
    else:
        historico_categoria_anterior = []

    # Igual que arriba, pero para los 6 KPI de las tarjetas (variacion vs. el corte anterior).
    ruta_historico_kpi = _guardar_historico_kpis(proyectos, datos, opciones_anio, fecha_corte)
    hist_kpi = pd.read_csv(ruta_historico_kpi, encoding='utf-8-sig')
    hist_kpi['proyecto'] = hist_kpi['proyecto'].astype(str).str.strip()
    hist_kpi['anio'] = hist_kpi['anio'].astype(str)
    fechas_hist_kpi = sorted(hist_kpi['fecha_corte'].astype(str).unique().tolist())
    fecha_corte_anterior_kpi = fechas_hist_kpi[-2] if len(fechas_hist_kpi) >= 2 else None
    if fecha_corte_anterior_kpi:
        columnas_kpi = ['proyecto', 'anio'] + [c for c in COLUMNAS_HISTORICO_KPI if c not in ('fecha_corte', 'proyecto', 'anio')]
        historico_kpi_anterior = (
            hist_kpi[hist_kpi['fecha_corte'].astype(str) == fecha_corte_anterior_kpi][columnas_kpi]
            .to_dict('records')
        )
        nota_corte_anterior = f" · Variación calculada contra el corte anterior ({fecha_corte_anterior_kpi})"
    else:
        historico_kpi_anterior = []
        nota_corte_anterior = ""

    metricas_iniciales = _sumar_metricas([datos[p][anio_defecto] for p in proyectos])

    # Inicialización de la gráfica de barras
    items_iniciales = [{'proyecto': p, 'valor': datos[p][anio_defecto]['subsidio'][1]} for p in proyectos]
    items_iniciales.sort(key=lambda x: x['valor'])
    proyectos_init = [x['proyecto'] for x in items_iniciales]
    valores_init = [x['valor'] for x in items_iniciales]

    div_funnel_subsidio = _fig_funnel('fig_subsidio', ETAPAS_SUBSIDIO, metricas_iniciales['subsidio'], 'Embudo de Subsidio')
    div_funnel_credito = _fig_funnel('fig_credito', ETAPAS_CREDITO, metricas_iniciales['credito'], 'Embudo de Crédito')
    div_barras_proyecto = _fig_barras_proyecto('fig_proyecto', proyectos_init, valores_init)

    registros_gestion_iniciales = [r for r in categoria_tramites if r['categoria'] == 'En Gestión']
    div_categoria_principal = _fig_barras_apiladas_por_mes(
        'fig_categoria_principal', categoria_tramites, 'categoria',
        ORDEN_CATEGORIA_PRINCIPAL, COLORES_CATEGORIA_PRINCIPAL,
        'Clientes por categoría y mes proyectado',
    )
    div_subcategoria_gestion = _fig_barras_apiladas_por_mes(
        'fig_subcategoria_gestion', registros_gestion_iniciales, 'subcategoria',
        ORDEN_SUBCATEGORIA_GESTION, COLORES_SUBCATEGORIA_GESTION,
        'Detalle de clientes en gestión por mes proyectado',
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
</style>
</head>
<body>
<div class="encabezado"><span class="logo-dot"></span><span class="logo-dot"></span><h1>Informe de Pendientes por Escriturar</h1></div>
<p class="subtitulo">Corte: {fecha_corte}{nota_corte_anterior}</p>

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
</div>

<div class="kpi-row" id="kpiRow">
    <div class="kpi-card"><div class="kpi-valor" id="kpi-0">{s[0]:,}</div><div class="kpi-etiqueta">Vendidos</div><div class="kpi-delta" id="kpi-delta-0"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-1">{s[1]:,}</div><div class="kpi-etiqueta">No escriturados</div><div class="kpi-delta" id="kpi-delta-1"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-2">{s[2]:,}</div><div class="kpi-etiqueta">Requieren subsidio</div><div class="kpi-delta" id="kpi-delta-2"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-3">{s[3]:,}</div><div class="kpi-etiqueta">Subsidio sin aprobar</div><div class="kpi-delta" id="kpi-delta-3"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-5">{c[2]:,}</div><div class="kpi-etiqueta">Requieren crédito</div><div class="kpi-delta" id="kpi-delta-5"></div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-6">{c[3]:,}</div><div class="kpi-etiqueta">Crédito sin aprobar</div><div class="kpi-delta" id="kpi-delta-6"></div></div>
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
<h2>Detalle de clientes en gestión por mes proyectado</h2>
{div_subcategoria_gestion}
</div>

<div class="seccion">
<h2>Clientes pendientes de aprobación (subsidio y/o crédito)</h2>
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
const COLORES_CATEGORIA_TABLA = {json.dumps(COLORES_CATEGORIA_TABLA)};
const ORDEN_CATEGORIA_PRINCIPAL = {json.dumps(ORDEN_CATEGORIA_PRINCIPAL)};
const COLORES_CATEGORIA_PRINCIPAL = {json.dumps(COLORES_CATEGORIA_PRINCIPAL)};
const ORDEN_SUBCATEGORIA_GESTION = {json.dumps(ORDEN_SUBCATEGORIA_GESTION)};
const COLORES_SUBCATEGORIA_GESTION = {json.dumps(COLORES_SUBCATEGORIA_GESTION)};

// Comparativo "corte anterior" para la grafica "Clientes por categoría y mes proyectado"
// (ver _actualizarCategoriaPrincipalConComparativo mas abajo). Vacio si todavia no hay un
// corte previo guardado en el historico (ej. la primera corrida con este esquema).
const FECHA_CORTE_ANTERIOR_CATEGORIA = {json.dumps(fecha_corte_anterior)};
const HISTORICO_CATEGORIA_ANTERIOR = {json.dumps(historico_categoria_anterior)};

// id de tarjeta KPI -> indice en el arreglo `kpis` de actualizar() (los ids no son
// consecutivos: no existe kpi-4, ese es "Subsidio sin radicar" que solo se muestra en el embudo).
const IDS_KPI = [0, 1, 2, 3, 5, 6];
// id de tarjeta KPI -> nombre de indicador en el historico de KPI (mismo orden que IDS_KPI).
const NOMBRES_KPI_HISTORICO = {{
    0: 'Vendidos', 1: 'No escriturados', 2: 'Requieren subsidio', 3: 'Subsidio sin aprobar',
    5: 'Requieren crédito', 6: 'Crédito sin aprobar'
}};

// Corte anterior para la variacion de las tarjetas KPI (ver actualizarDeltasKpi mas abajo).
// Vacio si todavia no hay un corte previo guardado en el historico.
const HISTORICO_KPI_ANTERIOR = {json.dumps(historico_kpi_anterior)};

function proyectosSeleccionados() {{
    const marcadas = Array.from(document.querySelectorAll('.chk-proyecto:checked')).map(c => c.value);
    return marcadas;
}}

function sumarMetricas(seleccion, anio) {{
    const subsidio = [0, 0, 0, 0, 0];
    const credito = [0, 0, 0, 0, 0];
    seleccion.forEach(p => {{
        const m = DATOS[p][anio];
        m.subsidio.forEach((v, i) => subsidio[i] += v);
        m.credito.forEach((v, i) => credito[i] += v);
    }});
    return {{subsidio, credito}};
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

function actualizarTabla(seleccion, anio) {{
    const filtrados = PENDIENTES.filter(p =>
        seleccion.includes(p.proyecto) &&
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

function actualizarGraficaBarras(seleccion, anio) {{
    // Filtrar aptos no escriturados para cada proyecto en la selección actual
    let items = seleccion.map(p => ({{
        proyecto: p,
        valor: DATOS[p][anio].subsidio[1] // posición 1 es n_no_escriturados
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

function _actualizarCategoriaPrincipalConComparativo(divId, actualFiltrado, anteriorFiltrado, ordenApilado, colores, tituloTexto) {{
    // Primera traza = base de la barra apilada (queda abajo).
    const legendRank = {{}};
    ordenApilado.forEach((c, i) => {{ legendRank[c] = i + 1; }});

    // Periodos de ambos cortes, en orden cronologico (campo 'orden' de cada registro). Si un
    // mes solo existe en el corte anterior (ya no quedan clientes ahi hoy), igual se muestra
    // para no perder la comparacion.
    const ordenPorPeriodo = {{}};
    actualFiltrado.forEach(p => {{ ordenPorPeriodo[p.periodo] = p.orden; }});
    anteriorFiltrado.forEach(p => {{ if (!(p.periodo in ordenPorPeriodo)) ordenPorPeriodo[p.periodo] = p.orden; }});
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

    // Con comparativo: eje x de 2 niveles (mes, grupo) -- 'Hoy' y 'Corte anterior (fecha)'
    // lado a lado dentro de cada mes, cada uno apilado por categoria.
    const grupoActual = 'Hoy';
    const grupoAnterior = `Corte anterior (${{FECHA_CORTE_ANTERIOR_CATEGORIA}})`;

    const nivel0 = [];
    const nivel1 = [];
    const opacidades = [];
    const etiquetasHover = [];
    periodos.forEach(periodo => {{
        nivel0.push(periodo, periodo);
        // "Corte anterior" va primero, "Hoy" despues -- misma lectura izquierda->derecha que
        // el orden cronologico (lo viejo antes que lo nuevo).
        // El segundo nivel del eje x se deja en blanco (2 valores distintos pero invisibles,
        // para que Plotly siga separando las 2 barras de cada mes): en el eje solo se ve el
        // mes, y el detalle "Corte anterior" / "Hoy" queda en el hover (ver mas abajo).
        nivel1.push('', ' ');
        opacidades.push(0.45, 1);
        etiquetasHover.push(`${{periodo}} · ${{grupoAnterior}}`, `${{periodo}} · ${{grupoActual}}`);
    }});

    const traces = ordenApilado.map(c => {{
        const valores = [];
        periodos.forEach(periodo => {{
            const suma = anteriorFiltrado
                .filter(p => p.periodo === periodo)
                .reduce((acc, p) => acc + (p[c] || 0), 0);
            valores.push(suma);
            valores.push(actualFiltrado.filter(p => p.periodo === periodo && p.categoria === c).length);
        }});
        return {{
            type: 'bar', name: c, x: [nivel0, nivel1], y: valores,
            text: valores.map(v => v > 0 ? String(v) : ''),
            textposition: 'inside', insidetextanchor: 'middle', textangle: 0,
            textfont: {{ size: 11 }}, marker: {{ color: colores[c], opacity: opacidades }}, legendrank: legendRank[c],
            customdata: etiquetasHover,
            hovertemplate: '%{{customdata}}<br>' + c + ': %{{y}}<extra></extra>'
        }};
    }});

    const anotacionesTotales = [];
    periodos.forEach(periodo => {{
        const totalActual = actualFiltrado.filter(p => p.periodo === periodo).length;
        const totalAnterior = anteriorFiltrado
            .filter(p => p.periodo === periodo)
            .reduce((acc, p) => acc + (p['Listos'] || 0) + (p['En Gestión'] || 0) + (p['Sin Cartas'] || 0), 0);
        anotacionesTotales.push({{
            x: [periodo, ' '], y: totalActual, text: `<b>${{totalActual}}</b>`, showarrow: false,
            yshift: 10, font: {{ color: '{COLOR_VERDE_OSCURO}', size: 13 }}
        }});
        anotacionesTotales.push({{
            x: [periodo, ''], y: totalAnterior, text: `<b>${{totalAnterior}}</b>`, showarrow: false,
            yshift: 10, font: {{ color: '#888', size: 13 }}
        }});
    }});

    Plotly.react(divId, traces, {{
        barmode: 'stack', title: tituloTexto,
        xaxis: {{ title: 'Mes de escrituración' }}, yaxis: {{ title: 'Cantidad de clientes' }},
        legend: {{ title: {{ text: 'Categoría' }} }}, margin: {{ t: 60, b: 40, l: 40, r: 20 }},
        height: 430, template: 'plotly_white', annotations: anotacionesTotales
    }});
}}

function actualizarGraficaCategoriaPrincipal(seleccion, anio) {{
    const filtrados = CATEGORIA_TRAMITES.filter(p =>
        seleccion.includes(p.proyecto) &&
        (anio === '{TODOS}' || p.anio === anio)
    );
    const anteriorFiltrado = HISTORICO_CATEGORIA_ANTERIOR.filter(p =>
        seleccion.includes(p.proyecto) &&
        (anio === '{TODOS}' || p.anio === anio)
    );
    _actualizarCategoriaPrincipalConComparativo(
        'fig_categoria_principal', filtrados, anteriorFiltrado,
        ORDEN_CATEGORIA_PRINCIPAL, COLORES_CATEGORIA_PRINCIPAL,
        'Clientes por categoría y mes proyectado'
    );
}}

function actualizarGraficaSubcategoriaGestion(seleccion, anio) {{
    const filtrados = CATEGORIA_TRAMITES.filter(p =>
        seleccion.includes(p.proyecto) &&
        (anio === '{TODOS}' || p.anio === anio) &&
        p.categoria === 'En Gestión'
    );
    _actualizarBarraApiladaPorMes(
        'fig_subcategoria_gestion', filtrados, 'subcategoria',
        ORDEN_SUBCATEGORIA_GESTION, COLORES_SUBCATEGORIA_GESTION,
        'Detalle de clientes en gestión por mes proyectado'
    );
}}

function actualizarDeltasKpi(seleccion, anio, kpis) {{
    const limpiar = () => IDS_KPI.forEach(idx => {{
        const el = document.getElementById('kpi-delta-' + idx);
        if (el) el.textContent = '';
    }});

    // El historico de KPI guarda una fila por proyecto y por cada año (incluido 'Todos'), asi
    // que el filtro de año se compara igual que en DATOS -- sin necesidad de un caso especial
    // para 'Todos'.
    const filasAnterior = HISTORICO_KPI_ANTERIOR.filter(p =>
        seleccion.includes(p.proyecto) && p.anio === anio
    );
    if (filasAnterior.length === 0) {{
        limpiar();
        return;
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
}}

function actualizar() {{
    const seleccion = proyectosSeleccionados();
    const anio = document.getElementById('filtroAnio').value;
    const m = sumarMetricas(seleccion, anio);

    // 1. Actualizar Embudos
    Plotly.restyle('fig_subsidio', {{x: [m.subsidio]}}, [0]);
    Plotly.restyle('fig_credito', {{x: [m.credito]}}, [0]);

    // 2. Actualizar Gráfica de Barras por Proyecto
    actualizarGraficaBarras(seleccion, anio);

    // 3. Actualizar Gráfica de categorías por mes (principal + detalle de en gestión)
    actualizarGraficaCategoriaPrincipal(seleccion, anio);
    actualizarGraficaSubcategoriaGestion(seleccion, anio);

    // 4. Actualizar KPIs
    // OJO: los ids de las tarjetas no son consecutivos (falta kpi-4), por eso se usa
    // IDS_KPI en vez del indice del forEach para saber a que tarjeta va cada valor.
    const kpis = [m.subsidio[0], m.subsidio[1], m.subsidio[2], m.subsidio[3], m.credito[2], m.credito[3]];
    kpis.forEach((v, pos) => {{
        const el = document.getElementById('kpi-' + IDS_KPI[pos]);
        if (el) el.textContent = v.toLocaleString('es-CO');
    }});

    // 4b. Variacion vs. el corte anterior (si ya hay un corte previo guardado).
    actualizarDeltasKpi(seleccion, anio, kpis);

    // 5. Actualizar Estado de Controles y Tabla
    actualizarBotonProyecto(seleccion);
    actualizarTabla(seleccion, anio);
}}

document.getElementById('filtroAnio').addEventListener('change', actualizar);

document.querySelectorAll('.chk-proyecto').forEach(chk => chk.addEventListener('change', actualizar));

document.getElementById('lnkTodosProyectos').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = true);
    actualizar();
}});
document.getElementById('lnkNingunProyecto').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = false);
    actualizar();
}});

const btnFiltroProyecto = document.getElementById('btnFiltroProyecto');
const panelFiltroProyecto = document.getElementById('panelFiltroProyecto');
btnFiltroProyecto.addEventListener('click', (ev) => {{
    ev.stopPropagation();
    panelFiltroProyecto.style.display = (panelFiltroProyecto.style.display === 'none') ? 'block' : 'none';
}});
document.addEventListener('click', (ev) => {{
    if (!panelFiltroProyecto.contains(ev.target) && ev.target !== btnFiltroProyecto) {{
        panelFiltroProyecto.style.display = 'none';
    }}
}});

// Renderizado inicial
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
    return ruta_salida


if __name__ == "__main__":
    run()