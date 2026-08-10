# Informe de Pendientes por Escriturar — ONCE Constructora

Pipeline en Python que se conecta a la API de **Smart-Home** para generar un
informe de unidades vendidas que aún no se han escriturado, cuáles requieren subsidio y/o
crédito, y en qué etapa de aprobación/radicación va cada trámite. El resultado final es un
**dashboard HTML interactivo**.

## Cómo correrlo

Requiere el entorno virtual en `.venv/` (Python 3.14, con `pandas`, `requests`, `plotly`,
`pyarrow` instalados).

```powershell
.venv\Scripts\python.exe src\main.py
```

Esto corre el pipeline completo (pasos 1 a 6, ver abajo) y deja el informe en
`data/reportes/informe_escrituracion_<fecha>.html`, listo para acompartir.

Cada paso también se puede correr solo, por ejemplo para reprocesar únicamente el dashboard
sin volver a golpear la API:

```powershell
.venv\Scripts\python.exe src\6_dashboard.py
```

> **Nota:** si el paso 1 no logra refrescar todos los proyectos (falla de conexión con la
> API), `main.py` avisa cuáles quedaron con datos viejos y **pregunta por consola** si se
> quiere continuar de todas formas. Pensado para correrlo de forma manual/atendida — si algún
> día se programa para correr solo (Task Scheduler), ese `input()` hay que cambiarlo por una
> regla automática (ver nota en `main.py`).

## El pipeline, paso a paso

Todos los scripts viven en `src/`, se numeran en el orden en que se ejecutan, y cada uno
expone una función `run()` (por eso se pueden correr solos o encadenados desde `main.py`).

| # | Script | Qué hace | Sale a |
|---|---|---|---|
| 1 | `1_cargue_clientes_raw.py` | Trae todos los prospectos/ventas de cada proyecto (`getSales`, 1 llamada por proyecto, ~10 proyectos) | `data/raw/clientes/<proyecto>.parquet` |
| 2 | `2_cargue_clientes_staging.py` | Limpia y renombra columnas, calcula la bandera `escriturado` | `data/staging/clientes.parquet` |
| 3 | `3_cargue_pagos_raw.py` | Trae **todo** el histórico de pagos/plan de pagos en una sola llamada masiva (`GetPaymentsRecords`) | `data/raw/pagos/pagos_raw_<fecha>.parquet` |
| 4 | `4_no_escriturados__tareas_raw.py` | Trae las tareas/trámites (`getTasks`) de cada cliente no escriturado, una llamada por cliente | `data/raw/no_escriturados/tareas_tramites_<fecha>.parquet` |
| 5 | `5_no_escriturados_staging.py` | Cruza clientes + pagos (por Proyecto+Módulo) + tareas (por prospectId) para calcular subsidio/crédito requerido, aprobado y radicado | `data/analytics/clientes_detallado.csv` + snapshot en `data/historico/` |
| 6 | `6_dashboard.py` | Arma el HTML interactivo (embudos, barras, tabla de pendientes, variación vs. corte anterior) y actualiza el histórico de indicadores | `data/reportes/informe_escrituracion_<fecha>.html` + `data/historico/indicadores_por_proyecto.csv` |

`main.py` orquesta 1→2→3→4→5→6. 

`api_utils.py` es el módulo compartido: rutas absolutas centralizadas (para que no importe
desde qué carpeta se ejecute cada script), sesión HTTP con reintentos automáticos, helpers de
guardado/lectura de parquet versionado, y el filtro común de "clientes no escriturados".

## Configuración clave (`src/api_utils.py`)

- `ANIO_OBJETIVO_ESCRITURA`  — año de escrituración que usan por defecto el
  informe y el histórico de indicadores. Cambiarlo aquí afecta a los pasos 3, 4, 5 y 6.
- `MAX_WORKERS` (8) — concurrencia para el paso 4 (~cientos/miles de clientes).
- `MAX_WORKERS_RAFAGA_CORTA` (3) + `ESPERA_ENTRE_LANZAMIENTOS` — concurrencia reducida y
  escalonada para el paso 1 (solo ~10 proyectos): con 8 conexiones casi simultáneas el
  servidor de Smarthome llegó a cortar la conexión (`ConnectionResetError`); con pocos ítems
  no hay necesidad de tanto paralelismo.

## Carpeta `data/`

```
data/
├── raw/
│   ├── clientes/<proyecto>.parquet          # se sobreescribe cada corrida
│   ├── pagos/pagos_raw_<fecha>.parquet       # snapshot versionado, nunca se sobreescribe
│   └── no_escriturados/tareas_tramites_<fecha>.parquet
├── staging/clientes.parquet
├── analytics/clientes_detallado.csv          # "foto" actual, para negocio (Excel)
├── historico/
│   ├── clientes_detallado_<fecha>.parquet    # snapshot completo por corrida
│   └── indicadores_por_proyecto.csv          # historico de KPIs por proyecto y por año
└── reportes/informe_escrituracion_<fecha>.html
```

Los archivos versionados (`_<fecha>.parquet`) nunca se sobreescriben entre corridas — cada
paso lee siempre la **versión más reciente** (`leer_ultimo_parquet`). Esto permite comparar
entre cortes y evita que una corrida fallida corrompa el histórico completo.

## El dashboard (`data/reportes/informe_escrituracion_<fecha>.html`)

Archivo HTML **autocontenido** (Plotly embebido, sin conexión a internet ni servidor) —
se abre con doble clic en cualquier navegador y queda totalmente interactivo. Incluye:

- **Filtros**: año proyectado de escritura, y proyecto (selección múltiple).
- **KPIs** con variación vs. el corte anterior (▲/▼), tomada de
  `indicadores_por_proyecto.csv`. La variación solo se muestra cuando el año filtrado es el
  año objetivo (`ANIO_OBJETIVO_ESCRITURA`) — el histórico por otros años/"Todos" existe, pero
  esta comparación puntual en los KPI todavía está atada al año objetivo.
- **Barra** de apartamentos no escriturados por proyecto.
- **Embudo de Subsidio** y **Embudo de Crédito**, cada uno con 5 etapas: Vendidos → No
  escriturados → Requieren subsidio/crédito → Sin aprobar → Sin radicar.
- **Barra apilada** de clientes por categoría (Listos / Sin Crédito / Falta 1 carta / en
  Gestión / Sin Cartas) y mes proyectado de escrituración, con el total de cada mes rotulado
  encima de la barra.
- **Tabla** de clientes pendientes de aprobación (subsidio y/o crédito), agrupada por mes
  proyectado.

Todos los gráficos y la tabla responden a los filtros vía JavaScript embebido — no hace falta
un servidor (Dash) para que sea interactivo; por eso se eligió Plotly + HTML estático sobre
Dash, que sí necesitaría infraestructura corriendo para compartirse por correo.

## Limitaciones conocidas


- **Alcance del histórico de KPIs**: `indicadores_por_proyecto.csv` guarda una fila por
  proyecto **por cada año disponible** (no solo el año objetivo), pero la variación mostrada
  en las tarjetas KPI del dashboard sigue comparando solo dentro del año objetivo.
- **Datos de subsidio/crédito por cliente** dependen de que el paso 3 (pagos) y el paso 4
  (tareas) se hayan corrido con el mismo alcance de clientes que el paso 5 espera — si el
  paso 1 falla para algún proyecto (ver aviso de `main.py`), esos clientes seguirán
  reflejando datos de la corrida anterior.
- Nombres de proyecto con tildes (ej. "Mañanitas") pueden verse raros en la consola de
  algunas terminales — es solo un problema de despliegue del terminal, los archivos en sí
  están correctamente en UTF-8. Los espacios extra que traía la API en algunos nombres de
  proyecto (ej. `"VERDELIMA "`) ya se limpian en `2_cargue_clientes_staging.py`.

