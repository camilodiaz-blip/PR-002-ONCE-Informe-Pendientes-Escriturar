"""
Genera un informe HTML autocontenido (Plotly embebido) a partir de
data/analytics/conversaciones_detalle_por_cliente.csv -- filtrable por proyecto.

El CSV trae 2 categorias separadas (ultima_gestion_sistema/dias_gestion_sistema y
ultimo_seguimiento/dias_seguimiento, ver analisis_conversaciones.py), pero este informe NO
las distingue: se fusionan en un solo indicador "ultima_gestion" (el mas reciente de los 2,
sea cual sea) para que el dashboard hable de una sola cosa por cliente, no de 2 en paralelo.

Sigue el mismo patron que 6_dashboard.py: HTML renderizado en Python para el estado inicial +
JSON embebido + JS para recalcular todo al cambiar el filtro, sin volver a llamar al servidor.
"""
import json
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from api_utils import RUTA_ANALYTICS, RUTA_REPORTES

# Misma paleta de 6_dashboard.py, para que los informes se vean consistentes entre si.
COLOR_VERDE = '#2E8B45'
COLOR_VERDE_OSCURO = '#1B5E20'
COLOR_PENDIENTE = '#E8A33D'
COLOR_ROJO = '#C62828'
COLOR_MORADO = '#6A1B9A'

# Umbrales (solo para las graficas/KPI de este informe -- el CSV ya no los guarda como
# columna). Supuestos operativos, ajustables aca sin tocar el resto del codigo.
UMBRAL_RECIENTE_DIAS = 15
UMBRAL_CRITICO_DIAS = 45

ORDEN_TEMPERATURA = ['Reciente', 'Medio', 'Crítico']
COLORES_TEMPERATURA = {
    'Reciente': COLOR_VERDE,
    'Medio': COLOR_PENDIENTE,
    'Crítico': COLOR_ROJO,
}

TOP_N_ASESORES = 15

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _escritura_programada(anio, mes):
    if pd.isna(anio) or pd.isna(mes):
        return 'Sin fecha programada'
    return f"{MESES[int(mes)]} {int(anio)}"


def _fusionar_gestion(df):
    """
    Combina 'ultima_gestion_sistema'/'dias_gestion_sistema' y
    'ultimo_seguimiento'/'dias_seguimiento' en un solo par 'ultima_gestion'/'dias_gestion' --
    el que haya pasado MENOS dias (el mas reciente de los 2), sin importar si fue un evento de
    sistema o un seguimiento real. En empate, se deja el de sistema (arbitrario, no cambia el
    numero de dias).
    """
    df = df.copy()
    usar_sistema = df['dias_gestion_sistema'] <= df['dias_seguimiento']
    df['ultima_gestion'] = df['ultimo_seguimiento'].where(~usar_sistema, df['ultima_gestion_sistema'])
    df['dias_gestion'] = df['dias_seguimiento'].where(~usar_sistema, df['dias_gestion_sistema'])
    return df


def _temperatura(dias):
    if dias <= UMBRAL_RECIENTE_DIAS:
        return 'Reciente'
    if dias <= UMBRAL_CRITICO_DIAS:
        return 'Medio'
    return 'Crítico'


def _kpis(df):
    """KPI agregados sobre el subconjunto de clientes ya filtrado por proyecto."""
    total_clientes = len(df)
    if total_clientes == 0:
        return {'clientes': 0, 'promedio_dias_gestion': None, 'pct_reciente': 0, 'pct_critico': 0}

    promedio_dias_gestion = df['dias_gestion'].mean()
    pct_reciente = (df['dias_gestion'] <= UMBRAL_RECIENTE_DIAS).mean() * 100
    pct_critico = (df['dias_gestion'] > UMBRAL_CRITICO_DIAS).mean() * 100

    return {
        'clientes': total_clientes,
        'promedio_dias_gestion': round(promedio_dias_gestion, 1),
        'pct_reciente': round(pct_reciente, 1),
        'pct_critico': round(pct_critico, 1),
    }


def _fig_temperatura(div_id, df):
    temperaturas = df['dias_gestion'].apply(_temperatura)
    conteo = temperaturas.value_counts().reindex(ORDEN_TEMPERATURA, fill_value=0)
    fig = go.Figure(go.Bar(
        x=conteo.values, y=conteo.index, orientation='h',
        marker_color=[COLORES_TEMPERATURA[t] for t in conteo.index],
        text=conteo.values, textposition='outside',
    ))
    # El titulo va en un <h2> por fuera (mas visible y confiable que el titulo interno de
    # Plotly -- ver nota en el JS, `Plotly.react` con title como string simple no lo renderiza
    # con la version de plotly.js embebida), asi que aca solo se libera el espacio de arriba.
    fig.update_layout(
        xaxis_title='Cantidad de clientes',
        margin=dict(l=100, t=20, r=40, b=40), height=260, autosize=True, template='plotly_white',
    )
    return fig.to_html(
        full_html=False, include_plotlyjs='inline', div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
    )


def _fig_gestion_proyecto(div_id, df):
    items = df.groupby('proyecto')['dias_gestion'].mean().round(1).sort_values()
    fig = go.Figure(go.Bar(
        x=items.values, y=items.index, orientation='h',
        marker_color=COLOR_MORADO, text=items.values, textposition='outside',
    ))
    fig.update_layout(
        xaxis_title='Días promedio sin gestión',
        margin=dict(l=220, t=20, r=40, b=40),
        height=max(260, 40 + 40 * max(len(items), 1)), autosize=True, template='plotly_white',
    )
    return fig.to_html(
        full_html=False, include_plotlyjs=False, div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
        default_width='100%',
    )


def _fig_gestion_asesor(div_id, df, top_n=TOP_N_ASESORES):
    # Solo los top_n con mas dias promedio sin gestion (los que mas necesitan atencion) -- con
    # muchos asesores, mostrarlos todos haria la grafica demasiado larga para ser util.
    items = df.groupby('asesor')['dias_gestion'].mean().round(1).sort_values(ascending=False).head(top_n)
    items = items.sort_values()
    fig = go.Figure(go.Bar(
        x=items.values, y=items.index, orientation='h',
        marker_color=COLOR_MORADO, text=items.values, textposition='outside',
    ))
    fig.update_layout(
        xaxis_title='Días promedio sin gestión',
        margin=dict(l=220, t=20, r=40, b=40),
        height=max(260, 30 + 30 * max(len(items), 1)), autosize=True, template='plotly_white',
    )
    return fig.to_html(
        full_html=False, include_plotlyjs=False, div_id=div_id,
        config={'displaylogo': False, 'responsive': True},
        default_width='100%',
    )


def run():
    ruta_csv = os.path.join(RUTA_ANALYTICS, "conversaciones_detalle_por_cliente.csv")
    df = pd.read_csv(ruta_csv, encoding='utf-8-sig')
    df = _fusionar_gestion(df)

    # Cruce con clientes_detallado.csv (por proyecto + modulo, unico por cliente) para traer el
    # mes/año de escrituracion programada -- el CSV de conversaciones ya no trae ese dato.
    clientes = pd.read_csv(os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv"))
    clientes = clientes[['proyecto', 'modulo', 'escritura_programada_anio', 'escritura_programada_mes']]
    clientes = clientes.drop_duplicates(subset=['proyecto', 'modulo'])
    df = df.merge(clientes, on=['proyecto', 'modulo'], how='left')
    df['escritura_programada'] = df.apply(
        lambda r: _escritura_programada(r['escritura_programada_anio'], r['escritura_programada_mes']), axis=1
    )

    # Solo las columnas que de verdad usa el dashboard -- las de sistema/seguimiento por
    # separado ya cumplieron su proposito (fusionarse en ultima_gestion/dias_gestion), no hace
    # falta llevarlas al HTML.
    columnas_dashboard = [
        'proyecto', 'modulo', 'asesor', 'escritura_programada', 'ultima_gestion', 'dias_gestion',
    ]
    df = df[columnas_dashboard]

    proyectos = sorted(df['proyecto'].dropna().unique().tolist())

    kpis_iniciales = _kpis(df)
    div_temperatura = _fig_temperatura('fig_temperatura', df)
    div_gestion_proyecto = _fig_gestion_proyecto('fig_gestion_proyecto', df)
    div_gestion_asesor = _fig_gestion_asesor('fig_gestion_asesor', df)

    checkboxes_proyecto_html = "".join(
        f'<label class="ms-opcion"><input type="checkbox" class="chk-proyecto" value="{p}" checked> {p}</label>'
        for p in proyectos
    )

    fecha_generacion = datetime.now().strftime('%Y-%m-%d')

    def _fmt_dias(v):
        return f"{v:.1f}" if v is not None else "—"

    def _fmt_pct(v):
        return f"{v:.1f}%" if v is not None else "—"

    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe de Conversaciones - {fecha_generacion}</title>
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
    .ms-wrap {{ position: relative; display: inline-block; }}
    .ms-boton {{ font-size: 14px; padding: 6px 12px; border-radius: 4px; border: 1px solid #ccc; background: #fff; cursor: pointer; }}
    .ms-panel {{ position: absolute; top: 110%; left: 0; z-index: 10; background: #fff; border: 1px solid #ccc;
                 border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); padding: 10px 14px; min-width: 260px;
                 max-height: 300px; overflow-y: auto; }}
    .ms-opcion {{ display: block; font-weight: normal; padding: 3px 0; white-space: nowrap; }}
    .ms-acciones {{ display: flex; gap: 10px; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid #eee; }}
    .ms-acciones a {{ font-size: 12px; color: {COLOR_VERDE_OSCURO}; cursor: pointer; text-decoration: underline; }}
    .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 32px; }}
    .kpi-card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
                 padding: 16px 20px; text-align: center; border-top: 3px solid {COLOR_VERDE}; }}
    .kpi-valor {{ font-size: 26px; font-weight: bold; color: {COLOR_VERDE_OSCURO}; }}
    .kpi-etiqueta {{ font-size: 13px; color: #555; margin-top: 4px; }}
    .seccion {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
                padding: 16px; margin-bottom: 24px; }}
    h2 {{ margin-top: 0; color: {COLOR_VERDE_OSCURO}; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    thead th {{ text-align: left; background: {COLOR_VERDE}; color: #fff; padding: 8px 10px; position: sticky; top: 0; }}
    tbody td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
    .dias-badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: bold; color: #fff; }}
    .tabla-contenedor {{ max-height: 520px; overflow-y: auto; border: 1px solid #eee; border-radius: 6px; }}
    #tablaContador {{ color: #555; font-size: 13px; margin-bottom: 8px; }}
</style>
</head>
<body>
<div class="encabezado"><span class="logo-dot"></span><h1>Informe de Conversaciones por Cliente</h1></div>
<p class="subtitulo">Generado: {fecha_generacion} · Última gestión registrada por cliente (ver data/staging/conversaciones.parquet)</p>

<div class="filtros">
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
    <div class="kpi-card"><div class="kpi-valor" id="kpi-clientes">{kpis_iniciales['clientes']:,}</div><div class="kpi-etiqueta">Clientes analizados</div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-dias-gestion">{_fmt_dias(kpis_iniciales['promedio_dias_gestion'])}</div><div class="kpi-etiqueta">Promedio días sin gestión</div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-reciente">{_fmt_pct(kpis_iniciales['pct_reciente'])}</div><div class="kpi-etiqueta">Gestión reciente (≤{UMBRAL_RECIENTE_DIAS}d)</div></div>
    <div class="kpi-card"><div class="kpi-valor" id="kpi-critico">{_fmt_pct(kpis_iniciales['pct_critico'])}</div><div class="kpi-etiqueta">Gestión crítica (&gt;{UMBRAL_CRITICO_DIAS}d)</div></div>
</div>

<div class="seccion">
<h2>Clientes por antigüedad de la gestión</h2>
{div_temperatura}
</div>

<div class="seccion">
<h2>Promedio de días sin gestión, por proyecto</h2>
{div_gestion_proyecto}
</div>

<div class="seccion">
<h2>Promedio de días sin gestión, por asesor (top {TOP_N_ASESORES})</h2>
{div_gestion_asesor}
</div>

<div class="seccion">
<h2>Detalle por proyecto y módulo</h2>
<p id="tablaContador"></p>
<div class="tabla-contenedor">
<table>
<thead><tr>
<th>Proyecto</th><th>Módulo</th><th>Asesor</th><th>Escritura programada</th>
<th>Última gestión</th><th>Días</th>
</tr></thead>
<tbody id="tablaDetalleBody"></tbody>
</table>
</div>
</div>

<script>
const CLIENTES = {df.to_json(orient='records', force_ascii=False)};
const TODOS_PROYECTOS = {json.dumps(proyectos)};
const COLORES_TEMPERATURA = {json.dumps(COLORES_TEMPERATURA)};
const ORDEN_TEMPERATURA = {json.dumps(ORDEN_TEMPERATURA)};
const UMBRAL_RECIENTE_DIAS = {UMBRAL_RECIENTE_DIAS};
const UMBRAL_CRITICO_DIAS = {UMBRAL_CRITICO_DIAS};
const TOP_N_ASESORES = {TOP_N_ASESORES};

function temperatura(dias) {{
    if (dias <= UMBRAL_RECIENTE_DIAS) return 'Reciente';
    if (dias <= UMBRAL_CRITICO_DIAS) return 'Medio';
    return 'Crítico';
}}

function proyectosSeleccionados() {{
    return Array.from(document.querySelectorAll('.chk-proyecto:checked')).map(c => c.value);
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

function promedio(valores) {{
    return valores.length ? valores.reduce((a, v) => a + v, 0) / valores.length : null;
}}

function calcularKpis(filtrados) {{
    const clientes = filtrados.length;
    if (!clientes) {{
        return {{ clientes: 0, promDiasGestion: null, pctReciente: 0, pctCritico: 0 }};
    }}
    const promDiasGestion = promedio(filtrados.map(c => c.dias_gestion));
    const pctReciente = filtrados.filter(c => c.dias_gestion <= UMBRAL_RECIENTE_DIAS).length / clientes * 100;
    const pctCritico = filtrados.filter(c => c.dias_gestion > UMBRAL_CRITICO_DIAS).length / clientes * 100;
    return {{ clientes, promDiasGestion, pctReciente, pctCritico }};
}}

function actualizarKpis(filtrados) {{
    const k = calcularKpis(filtrados);
    document.getElementById('kpi-clientes').textContent = k.clientes.toLocaleString('es-CO');
    document.getElementById('kpi-dias-gestion').textContent = k.promDiasGestion !== null ? k.promDiasGestion.toFixed(1) : '—';
    document.getElementById('kpi-reciente').textContent = k.pctReciente.toFixed(1) + '%';
    document.getElementById('kpi-critico').textContent = k.pctCritico.toFixed(1) + '%';
}}

function actualizarGraficaTemperatura(filtrados) {{
    const conteo = {{}};
    ORDEN_TEMPERATURA.forEach(t => {{ conteo[t] = 0; }});
    filtrados.forEach(c => {{ const t = temperatura(c.dias_gestion); conteo[t] = (conteo[t] || 0) + 1; }});

    Plotly.react('fig_temperatura', [{{
        type: 'bar', orientation: 'h',
        x: ORDEN_TEMPERATURA.map(t => conteo[t]), y: ORDEN_TEMPERATURA,
        marker: {{ color: ORDEN_TEMPERATURA.map(t => COLORES_TEMPERATURA[t]) }},
        text: ORDEN_TEMPERATURA.map(t => conteo[t]), textposition: 'outside',
    }}], {{
        xaxis: {{ title: 'Cantidad de clientes' }},
        margin: {{ l: 100, t: 20, r: 40, b: 40 }}, height: 260, template: 'plotly_white',
    }});
}}

function actualizarGraficaGestionProyecto(filtrados, seleccion) {{
    const items = seleccion.map(p => {{
        const valores = filtrados.filter(c => c.proyecto === p).map(c => c.dias_gestion);
        return {{ proyecto: p, valor: valores.length ? Math.round((promedio(valores)) * 10) / 10 : 0 }};
    }});
    items.sort((a, b) => a.valor - b.valor);

    Plotly.react('fig_gestion_proyecto', [{{
        type: 'bar', orientation: 'h',
        x: items.map(i => i.valor), y: items.map(i => i.proyecto),
        marker: {{ color: '{COLOR_MORADO}' }}, text: items.map(i => i.valor), textposition: 'outside',
    }}], {{
        xaxis: {{ title: 'Días promedio sin gestión' }},
        margin: {{ l: 220, t: 20, r: 40, b: 40 }},
        height: Math.max(260, 40 + 40 * Math.max(items.length, 1)), template: 'plotly_white',
    }});
}}

function actualizarGraficaGestionAsesor(filtrados) {{
    const acumulado = {{}};
    filtrados.forEach(c => {{
        (acumulado[c.asesor] = acumulado[c.asesor] || []).push(c.dias_gestion);
    }});
    let items = Object.keys(acumulado).map(asesor => ({{
        asesor, valor: Math.round(promedio(acumulado[asesor]) * 10) / 10,
    }}));
    items.sort((a, b) => b.valor - a.valor);
    items = items.slice(0, TOP_N_ASESORES);
    items.sort((a, b) => a.valor - b.valor);

    Plotly.react('fig_gestion_asesor', [{{
        type: 'bar', orientation: 'h',
        x: items.map(i => i.valor), y: items.map(i => i.asesor),
        marker: {{ color: '{COLOR_MORADO}' }}, text: items.map(i => i.valor), textposition: 'outside',
    }}], {{
        xaxis: {{ title: 'Días promedio sin gestión' }},
        margin: {{ l: 220, t: 20, r: 40, b: 40 }},
        height: Math.max(260, 30 + 30 * Math.max(items.length, 1)), template: 'plotly_white',
    }});
}}

function actualizarTabla(filtrados) {{
    const ordenados = [...filtrados].sort((a, b) => b.dias_gestion - a.dias_gestion);

    const tbody = document.getElementById('tablaDetalleBody');
    tbody.innerHTML = '';
    ordenados.forEach(c => {{
        const colorGestion = COLORES_TEMPERATURA[temperatura(c.dias_gestion)];
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${{c.proyecto}}</td><td>${{c.modulo}}</td><td>${{c.asesor}}</td><td>${{c.escritura_programada}}</td>` +
            `<td>${{c.ultima_gestion}}</td>` +
            `<td><span class="dias-badge" style="background:${{colorGestion}}">${{c.dias_gestion}}</span></td>`;
        tbody.appendChild(tr);
    }});
    document.getElementById('tablaContador').textContent =
        ordenados.length.toLocaleString('es-CO') + ' clientes';
}}

function actualizar() {{
    const seleccion = proyectosSeleccionados();
    const filtrados = CLIENTES.filter(c => seleccion.includes(c.proyecto));

    actualizarKpis(filtrados);
    actualizarGraficaTemperatura(filtrados);
    actualizarGraficaGestionProyecto(filtrados, seleccion);
    actualizarGraficaGestionAsesor(filtrados);
    actualizarBotonProyecto(seleccion);
    actualizarTabla(filtrados);
}}

const btnFiltroProyecto = document.getElementById('btnFiltroProyecto');
const panelFiltroProyecto = document.getElementById('panelFiltroProyecto');
btnFiltroProyecto.addEventListener('click', () => {{
    panelFiltroProyecto.style.display = panelFiltroProyecto.style.display === 'none' ? 'block' : 'none';
}});
document.addEventListener('click', (ev) => {{
    if (!ev.target.closest('.ms-wrap')) panelFiltroProyecto.style.display = 'none';
}});
document.getElementById('lnkTodosProyectos').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = true);
    actualizar();
}});
document.getElementById('lnkNingunProyecto').addEventListener('click', () => {{
    document.querySelectorAll('.chk-proyecto').forEach(c => c.checked = false);
    actualizar();
}});
document.querySelectorAll('.chk-proyecto').forEach(c => c.addEventListener('change', actualizar));

actualizar();
</script>
</body>
</html>"""

    os.makedirs(RUTA_REPORTES, exist_ok=True)
    ruta_salida = os.path.join(RUTA_REPORTES, f"informe_conversaciones_{datetime.now().strftime('%Y%m%d')}.html")
    with open(ruta_salida, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Informe de conversaciones generado en {ruta_salida}")
    return ruta_salida


if __name__ == "__main__":
    run()
