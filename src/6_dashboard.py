import json
import os
from collections import defaultdict
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from api_utils import RUTA_ANALYTICS, RUTA_REPORTES, RUTA_HISTORICO, ANIO_OBJETIVO_ESCRITURA

# Paleta corporativa Once Constructora (verde) + ámbar como color de alerta/pendiente.
COLOR_VERDE = '#2E8B45'
COLOR_VERDE_OSCURO = '#1B5E20'
COLOR_PENDIENTE = '#E8A33D'

# Un solo mapa de color por categoria, compartido entre la grafica de barras y los
# badges de la tabla de pendientes (Python y JS), para que nunca queden desincronizados.
COLORES_CATEGORIA = {
    'Listos': '#2E8B45',
    'Sin Crédito': "#0D2F66",
    'Falta 1 carta': '#E8A33D',
    'en Gestión': '#6C757D',
    'Sin Cartas': '#C62828',
}

TODOS = 'Todos'

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


def _categoria_cliente(row):
    necesita_subsidio = bool(row.get('subsidio', 0) == 1)
    necesita_credito = bool(row.get('credito', 0) == 1)
    subsidio_aprobado = bool(row.get('subsidio_aprobado', 0) == 1)
    credito_aprobado = bool(row.get('credito_aprobado', 0) == 1)
    subsidio_radicado = bool(row.get('subsidio_radicado', 0) == 1)
    credito_radicado = bool(row.get('credito_radicado', 0) == 1)

    if necesita_subsidio and subsidio_aprobado and necesita_credito and credito_aprobado:
        return 'Listos'
    if (not necesita_subsidio) and necesita_credito and not credito_aprobado:
        return 'Sin Crédito'
    if (necesita_subsidio and subsidio_aprobado) ^ (necesita_credito and credito_aprobado):
        return 'Falta 1 carta'
    if (necesita_subsidio and not subsidio_aprobado and subsidio_radicado) or (necesita_credito and not credito_aprobado and credito_radicado):
        return 'en Gestión'
    return 'Sin Cartas'


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
        registros.append({
            'proyecto': r['proyecto'],
            'anio': anio_str,
            'modulo': r['modulo'],
            'cliente': cliente,
            'motivo': _motivo_pendiente(r),
            'categoria': _categoria_cliente(r),
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


def _tabla_categorias(df):
    """Non-written clients requiring subsidy and/or credit, grouped by category."""
    no_esc = df[df['escriturado'] == 0].copy()
    con_requisito = no_esc[(no_esc['subsidio'] == 1) | (no_esc['credito'] == 1)].copy()

    registros = []
    for _, r in con_requisito.iterrows():
        anio_val = r['escritura_programada_anio']
        mes_val = r['escritura_programada_mes']
        if pd.isna(anio_val) or pd.isna(mes_val):
            anio_str, orden, periodo = None, 999999, 'Sin fecha proyectada'
        else:
            anio_str = str(int(anio_val))
            orden = int(anio_val) * 100 + int(mes_val)
            periodo = f"{MESES[int(mes_val)]} {anio_str}"

        registros.append({
            'proyecto': r['proyecto'],
            'anio': anio_str,
            'categoria': _categoria_cliente(r),
            'periodo': periodo,
            'orden': orden,
        })

    registros.sort(key=lambda x: (x['orden'], x['proyecto']))
    return registros


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


def _fig_barras_categorias(div_id, pendientes, titulo):
    df = pd.DataFrame(pendientes)
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=titulo, xaxis_title='Mes de escrituración', yaxis_title='Cantidad de clientes')
        return fig.to_html(
            full_html=False, include_plotlyjs='inline', div_id=div_id,
            config={'displaylogo': False, 'responsive': True},
        )

    # Primera traza = base de la barra apilada. Queremos "Sin Cartas" arriba y "Listos" abajo.
    orden_apilado = ['Listos', 'Sin Crédito', 'Falta 1 carta', 'en Gestión', 'Sin Cartas']
    legend_rank = {'Listos': 1, 'Sin Crédito': 2, 'Falta 1 carta': 3, 'en Gestión': 4, 'Sin Cartas': 5}
    periodos = list(dict.fromkeys(df['periodo'].tolist()))
    fig = go.Figure()
    for categoria in orden_apilado:
        valores = [len(df[(df['periodo'] == periodo) & (df['categoria'] == categoria)]) for periodo in periodos]
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
            marker_color=COLORES_CATEGORIA.get(categoria, COLOR_PENDIENTE),
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


# Indicadores que se siguen en la seccion de seguimiento historico, con un color propio
# (reutiliza los mismos colores de "Listos"/"Sin Cartas" para que se lean igual en todo el informe).
COLORES_SEGUIMIENTO = {
    'No escriturados': '#1f77b4',
    'Listos': COLORES_CATEGORIA['Listos'],
    'Sin Cartas': COLORES_CATEGORIA['Sin Cartas'],
}


def _serie_seguimiento(historico_por_proyecto, proyectos, fechas, indicador):
    return [
        sum(historico_por_proyecto.get(p, {}).get(f, {}).get(indicador, 0) for p in proyectos)
        for f in fechas
    ]


def _fig_seguimiento(div_id, fechas, series):
    # El titulo de cada grafica va en un <h3> por fuera (mas visible que el titulo interno
    # de Plotly), asi que aca no se pone titulo -- solo se libera el espacio que ocuparia arriba.
    fig = go.Figure()
    for nombre, valores in series.items():
        fig.add_trace(go.Scatter(
            x=fechas, y=valores, mode='lines+markers+text',
            name=nombre,
            line=dict(color=COLORES_SEGUIMIENTO.get(nombre), width=3),
            marker=dict(size=8),
            text=[str(v) for v in valores],
            textposition='top center',
        ))
    fig.update_layout(
        xaxis_title='Corte',
        yaxis_title='Cantidad de clientes',
        margin=dict(t=20, b=40, l=40, r=20),
        height=340,
        autosize=True,
        template='plotly_white',
    )
    return fig.to_html(
        full_html=False, include_plotlyjs=False, div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
        default_width='100%',
    )


def _sumar_metricas(lista_metricas):
    subsidio = [0] * len(ETAPAS_SUBSIDIO)
    credito = [0] * len(ETAPAS_CREDITO)
    for m in lista_metricas:
        subsidio = [a + b for a, b in zip(subsidio, m['subsidio'])]
        credito = [a + b for a, b in zip(credito, m['credito'])]
    return {'subsidio': subsidio, 'credito': credito}


# Columnas del historico de indicadores, en el orden pedido para el seguimiento semanal.
COLUMNAS_HISTORICO = [
    'fecha_corte', 'proyecto', 'anio', 'Vendidos', 'No escriturados',
    'Requieren subsidio', 'Subsidio sin aprobar', 'Subsidio sin radicar',
    'Requieren crédito', 'Crédito sin aprobar', 'Crédito sin radicar',
    'Listos', 'Sin Crédito', 'Falta 1 carta', 'en Gestión', 'Sin Cartas',
]


def _fila_historico_indicador(proy, datos, conteo_categorias, anio):
    """Los 13 indicadores del dashboard para un proyecto, en el año usado como alcance del corte."""
    s = datos[proy][anio]['subsidio']
    c = datos[proy][anio]['credito']
    cat = conteo_categorias.get(proy, {})
    return {
        'Vendidos': s[0],
        'No escriturados': s[1],
        'Requieren subsidio': s[2],
        'Subsidio sin aprobar': s[3],
        'Subsidio sin radicar': s[4],
        'Requieren crédito': c[2],
        'Crédito sin aprobar': c[3],
        'Crédito sin radicar': c[4],
        'Listos': cat.get('Listos', 0),
        'Sin Crédito': cat.get('Sin Crédito', 0),
        'Falta 1 carta': cat.get('Falta 1 carta', 0),
        'en Gestión': cat.get('en Gestión', 0),
        'Sin Cartas': cat.get('Sin Cartas', 0),
    }


def _guardar_historico_indicadores(proyectos, datos, categorias, anios, fecha_corte):
    """
    Agrega al historico de indicadores (data/historico/indicadores_por_proyecto.csv) una fila
    por proyecto POR CADA año disponible de escrituracion (incluido 'Todos'), con el snapshot
    de hoy. No genera ningun reporte nuevo -- solo deja la base para que un futuro script de
    seguimiento semanal la lea y compare la evolucion entre corridas (por proyecto y por año).

    Si ya existen filas con la misma fecha_corte, se reemplazan (evita duplicar si el
    dashboard se corre mas de una vez el mismo dia).
    """
    filas = []
    for anio in anios:
        conteo_categorias = defaultdict(lambda: defaultdict(int))
        for r in categorias:
            if anio != TODOS and r['anio'] != anio:
                continue
            conteo_categorias[r['proyecto']][r['categoria']] += 1

        for proy in proyectos:
            fila = _fila_historico_indicador(proy, datos, conteo_categorias, anio)
            fila['fecha_corte'] = fecha_corte
            fila['proyecto'] = proy
            fila['anio'] = anio
            filas.append(fila)

    nuevo = pd.DataFrame(filas)[COLUMNAS_HISTORICO]

    os.makedirs(RUTA_HISTORICO, exist_ok=True)
    ruta = os.path.join(RUTA_HISTORICO, 'indicadores_por_proyecto.csv')
    if os.path.exists(ruta):
        existente = pd.read_csv(ruta)
        if 'anio' not in existente.columns:
            # Migracion: las corridas anteriores a este cambio solo guardaban el año objetivo.
            existente['anio'] = str(ANIO_OBJETIVO_ESCRITURA)
        # Normaliza nombres de proyecto de corridas viejas (ej. "VERDELIMA " con espacio, de
        # antes de limpiar la fuente en 2_cargue_clientes_staging.py). Si no se hace esto, un
        # cambio de nombre como ese rompe la comparacion vs. el corte anterior: el proyecto
        # queda guardado con dos nombres distintos y la variacion del KPI se ve inflada.
        existente['proyecto'] = existente['proyecto'].astype(str).str.strip()
        existente = existente[existente['fecha_corte'] != fecha_corte]
        historico = pd.concat([existente, nuevo], ignore_index=True)
    else:
        historico = nuevo

    historico.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f"Historico de indicadores actualizado en {ruta} ({len(nuevo)} filas de hoy, {len(historico)} filas totales)")
    return ruta


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
    categorias = _tabla_categorias(df)

    # El historico ahora guarda una fila por proyecto POR CADA año disponible (no solo el
    # año objetivo), para que a futuro se pueda dar seguimiento a cualquier año, no solo 2026.
    ruta_historico_ind = _guardar_historico_indicadores(proyectos, datos, categorias, opciones_anio, fecha_corte)

    # Datos para la variacion vs. el corte anterior en las tarjetas KPI (ver JS mas abajo).
    # Las tarjetas KPI de hoy siguen atadas al año objetivo (anio_defecto), asi que la
    # variacion tambien se calcula solo con ese año -- aunque el CSV completo ya tiene todos.
    hist_ind = pd.read_csv(ruta_historico_ind, encoding='utf-8-sig')
    hist_ind_defecto = hist_ind[hist_ind['anio'] == anio_defecto]
    fechas_historico = sorted(hist_ind_defecto['fecha_corte'].unique().tolist())
    columnas_indicador = [c for c in COLUMNAS_HISTORICO if c not in ('fecha_corte', 'proyecto', 'anio')]
    historico_por_proyecto = {
        proy: {
            fila['fecha_corte']: {col: int(fila[col]) for col in columnas_indicador}
            for _, fila in hist_ind_defecto[hist_ind_defecto['proyecto'] == proy].iterrows()
        }
        for proy in proyectos
    }
    fecha_corte_anterior = fechas_historico[-2] if len(fechas_historico) >= 2 else None
    nota_corte_anterior = (
        f" · Variación de los KPI calculada contra el corte anterior ({fecha_corte_anterior})"
        if fecha_corte_anterior else ""
    )

    metricas_iniciales = _sumar_metricas([datos[p][anio_defecto] for p in proyectos])

    # Inicialización de la gráfica de barras
    items_iniciales = [{'proyecto': p, 'valor': datos[p][anio_defecto]['subsidio'][1]} for p in proyectos]
    items_iniciales.sort(key=lambda x: x['valor'])
    proyectos_init = [x['proyecto'] for x in items_iniciales]
    valores_init = [x['valor'] for x in items_iniciales]

    div_funnel_subsidio = _fig_funnel('fig_subsidio', ETAPAS_SUBSIDIO, metricas_iniciales['subsidio'], 'Embudo de Subsidio')
    div_funnel_credito = _fig_funnel('fig_credito', ETAPAS_CREDITO, metricas_iniciales['credito'], 'Embudo de Crédito')
    div_barras_proyecto = _fig_barras_proyecto('fig_proyecto', proyectos_init, valores_init)
    div_barras_categorias = _fig_barras_categorias('fig_categorias', categorias, 'Clientes no escriturados por categoria y mes proyectado')

    # Seccion de seguimiento historico: evolucion de No escriturados / Listos / Sin Cartas
    # entre cortes. Igual que la variacion de los KPI, solo tiene datos reales para el año
    # objetivo (anio_defecto) -- por eso usa el mismo historico_por_proyecto ya filtrado a ese año.
    # "No escriturados" queda en su propia grafica (a la izquierda) porque esta en una escala
    # bastante mas grande que "Listos"/"Sin Cartas" -- juntarlas aplastaria estas ultimas.
    serie_no_escriturados_inicial = {
        'No escriturados': _serie_seguimiento(historico_por_proyecto, proyectos, fechas_historico, 'No escriturados')
    }
    series_listos_sin_cartas_iniciales = {
        ind: _serie_seguimiento(historico_por_proyecto, proyectos, fechas_historico, ind)
        for ind in ['Listos', 'Sin Cartas']
    }
    div_seguimiento_no_escriturados = _fig_seguimiento(
        'fig_seguimiento_no_escriturados', fechas_historico, serie_no_escriturados_inicial
    )
    div_seguimiento_listos_sin_cartas = _fig_seguimiento(
        'fig_seguimiento_listos_sin_cartas', fechas_historico, series_listos_sin_cartas_iniciales
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
{div_barras_categorias}
</div>

<!--
<div class="seccion">
<h2>Seguimiento</h2>
<p id="seguimientoNota" style="color:#777;font-size:13px;"></p>
<div class="fila-embudos">
<div><h3 class="titulo-grafica">No escriturados</h3>{div_seguimiento_no_escriturados}</div>
<div><h3 class="titulo-grafica">Listos vs. Sin Cartas</h3>{div_seguimiento_listos_sin_cartas}</div>
</div>
</div>-->

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
const CATEGORIAS = {json.dumps(categorias)};
const TODOS_PROYECTOS = {json.dumps(proyectos)};
const COLORES_CATEGORIA = {json.dumps(COLORES_CATEGORIA)};

// Historico de indicadores por proyecto (para la variacion vs. el corte anterior en los KPI).
const HISTORICO_POR_PROYECTO = {json.dumps(historico_por_proyecto)};
const FECHAS_HISTORICO = {json.dumps(fechas_historico)};
const ANIO_DEFECTO_HISTORICO = {json.dumps(anio_defecto)};
// id de tarjeta KPI -> nombre de indicador en el historico (los ids no son consecutivos:
// no existe kpi-4, ese es "Subsidio sin radicar" que solo se muestra en el embudo).
const IDS_KPI = [0, 1, 2, 3, 5, 6];
const MAPEO_KPI_HISTORICO = {{
    0: 'Vendidos', 1: 'No escriturados', 2: 'Requieren subsidio', 3: 'Subsidio sin aprobar',
    5: 'Requieren crédito', 6: 'Crédito sin aprobar'
}};

// Seccion de seguimiento historico (evolucion de indicadores clave entre cortes).
const COLORES_SEGUIMIENTO = {json.dumps(COLORES_SEGUIMIENTO)};

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
        const colorBadge = COLORES_CATEGORIA[p.categoria] || '#999';
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

function actualizarGraficaCategorias(seleccion, anio) {{
    const filtrados = CATEGORIAS.filter(p =>
        seleccion.includes(p.proyecto) &&
        (anio === '{TODOS}' || p.anio === anio)
    );

    // Primera traza = base de la barra apilada. Queremos "Sin Cartas" arriba y "Listos" abajo.
    const ordenApilado = ['Listos', 'Sin Crédito', 'Falta 1 carta', 'en Gestión', 'Sin Cartas'];
    const legendRank = {{
        'Listos': 1,
        'Sin Crédito': 2,
        'Falta 1 carta': 3,
        'en Gestión': 4,
        'Sin Cartas': 5
    }};

    const periodos = [...new Set(filtrados.map(p => p.periodo))];
    const traces = ordenApilado.map(c => {{
        const valores = periodos.map(periodo =>
            filtrados.filter(p => p.periodo === periodo && p.categoria === c).length
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
            marker: {{ color: COLORES_CATEGORIA[c] }},
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
        title: 'Clientes no escriturados por categoria y mes proyectado',
        xaxis: {{ title: 'Mes de escrituración' }},
        yaxis: {{ title: 'Cantidad de clientes' }},
        legend: {{ title: {{ text: 'Categoría' }} }},
        margin: {{ t: 60, b: 40, l: 40, r: 20 }},
        height: 430,
        template: 'plotly_white',
        annotations: anotacionesTotales
    }};

    Plotly.react('fig_categorias', traces, layout);
}}

function actualizarDeltasKpi(seleccion, anio, kpis) {{
    const limpiar = () => IDS_KPI.forEach(idx => {{
        const el = document.getElementById('kpi-delta-' + idx);
        if (el) el.textContent = '';
    }});

    // El historico solo registra el año objetivo -- si el usuario esta viendo otro año
    // (o "Todos"), o todavia no hay un corte anterior con que comparar, no hay nada que mostrar.
    if (anio !== ANIO_DEFECTO_HISTORICO || FECHAS_HISTORICO.length < 2) {{
        limpiar();
        return;
    }}

    const fechaAnterior = FECHAS_HISTORICO[FECHAS_HISTORICO.length - 2];

    IDS_KPI.forEach((idx, pos) => {{
        const indicador = MAPEO_KPI_HISTORICO[idx];
        let anterior = 0;
        seleccion.forEach(p => {{
            const historicoProyecto = HISTORICO_POR_PROYECTO[p] || {{}};
            const filaAnterior = historicoProyecto[fechaAnterior] || {{}};
            anterior += filaAnterior[indicador] || 0;
        }});

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

function _tracesSeguimiento(seleccion, indicadores) {{
    return indicadores.map(indicador => {{
        const valores = FECHAS_HISTORICO.map(fecha => {{
            let suma = 0;
            seleccion.forEach(p => {{
                const historicoProyecto = HISTORICO_POR_PROYECTO[p] || {{}};
                suma += (historicoProyecto[fecha] || {{}})[indicador] || 0;
            }});
            return suma;
        }});
        return {{
            type: 'scatter', mode: 'lines+markers+text',
            name: indicador, x: FECHAS_HISTORICO, y: valores,
            line: {{color: COLORES_SEGUIMIENTO[indicador], width: 3}},
            marker: {{size: 8}},
            text: valores.map(v => String(v)),
            textposition: 'top center'
        }};
    }});
}}

function actualizarGraficaSeguimiento(seleccion, anio) {{
    const idsGraficas = ['fig_seguimiento_no_escriturados', 'fig_seguimiento_listos_sin_cartas'];

    // La seccion "Seguimiento" puede estar oculta/comentada en el HTML (<!-- ... -->). Si sus
    // graficas no existen en el DOM, no hay nada que actualizar -- salir aca evita que
    // Plotly.react truene ("No DOM element...") y detenga el resto de actualizar() a mitad
    // de camino, incluida la tabla de pendientes que va despues.
    if (!idsGraficas.every(id => document.getElementById(id))) {{
        return;
    }}

    const nota = document.getElementById('seguimientoNota');

    // El historico solo tiene datos reales para el año objetivo -- igual que la variacion
    // de los KPI. Con otro año seleccionado, o sin al menos 2 cortes, no hay nada que mostrar.
    if (anio !== ANIO_DEFECTO_HISTORICO) {{
        if (nota) nota.textContent = `El seguimiento histórico solo está disponible para el año objetivo (${{ANIO_DEFECTO_HISTORICO}}).`;
        idsGraficas.forEach(id => Plotly.react(id, [], {{template: 'plotly_white'}}));
        return;
    }}
    if (FECHAS_HISTORICO.length < 2) {{
        if (nota) nota.textContent = 'Aún no hay suficientes cortes guardados para mostrar una tendencia.';
        idsGraficas.forEach(id => Plotly.react(id, [], {{template: 'plotly_white'}}));
        return;
    }}
    if (nota) nota.textContent = '';

    // El titulo de cada grafica va en el <h3> de afuera, no aca.
    const layoutBase = {{
        xaxis: {{title: 'Corte'}},
        yaxis: {{title: 'Cantidad de clientes'}},
        margin: {{t: 20, b: 40, l: 40, r: 20}},
        template: 'plotly_white'
    }};

    Plotly.react('fig_seguimiento_no_escriturados', _tracesSeguimiento(seleccion, ['No escriturados']), layoutBase);
    Plotly.react('fig_seguimiento_listos_sin_cartas', _tracesSeguimiento(seleccion, ['Listos', 'Sin Cartas']), layoutBase);
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

    // 3. Actualizar Gráfica de categorías por mes
    actualizarGraficaCategorias(seleccion, anio);

    // 3b. Actualizar seguimiento histórico
    actualizarGraficaSeguimiento(seleccion, anio);

    // 4. Actualizar KPIs
    // OJO: los ids de las tarjetas no son consecutivos (falta kpi-4), por eso se usa
    // IDS_KPI en vez del indice del forEach para saber a que tarjeta va cada valor.
    const kpis = [m.subsidio[0], m.subsidio[1], m.subsidio[2], m.subsidio[3], m.credito[2], m.credito[3]];
    kpis.forEach((v, pos) => {{
        const el = document.getElementById('kpi-' + IDS_KPI[pos]);
        if (el) el.textContent = v.toLocaleString('es-CO');
    }});

    // 4b. Variacion vs. el corte anterior (solo si el año filtrado es el que registra el
    // historico, y ya hay al menos 2 cortes guardados para comparar).
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