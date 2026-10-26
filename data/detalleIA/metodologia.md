# Metodología — Informe de Pendientes por Escriturar

Este documento explica cómo se calcula cada dato del informe, para que cualquier IA (o persona)
pueda responder preguntas sobre el detalle de la información usando los archivos de esta misma
carpeta (`detalle_clientes.csv` y `cambios_vs_comite.csv`), sin tener que adivinar las reglas de
negocio.

El análisis con IA de este proceso arranca con el corte de comité de **septiembre de 2026**. No
hace falta revisar información anterior a esa fecha.

## 1. Qué es cada archivo

- **`detalle_clientes.csv`**: una fila por cliente/apartamento, con su categoría ya calculada
  (hoy, y en el corte del comité del mes). No hay que re-derivar ninguna regla: la columna
  `categoria_hoy` ya tiene el resultado final.
- **`cambios_vs_comite.csv`**: solo los clientes cuya categoría, estado de escrituración o
  condición de "unidad atada" **cambió** entre el corte de comité y hoy. Es el archivo correcto
  para responder "¿qué cambió?" o "¿a qué corresponde esta diferencia?" — ya viene calculado,
  no hay que comparar dos tablas distintas a mano.
- **`metodologia.md`** (este archivo): las reglas de negocio.

## 2. La categoría de cada cliente

Cada cliente no escriturado se clasifica según el estado de su **Subsidio** y su **Crédito**, cada
uno con 3 estados posibles:

| Estado | Significado |
|---|---|
| `NR` (No Radicado) | No se ha radicado nada de ese trámite |
| `R` (Radicado) | Ya se radicó, pendiente de aprobación |
| `A` (Aprobado) | Ya está aprobado — o el cliente no requiere ese trámite (se cuenta como resuelto) |

La combinación de los dos estados determina la categoría:

| Crédito | Subsidio | Categoría | Subcategoría (detalle) |
|---|---|---|---|
| NR | NR | **Sin Radicados** | — |
| R | NR | **Pdt un Radicado** | Subsidio (No radicado)-Credito (radicado) |
| A | NR | **Pdt un Radicado** | Subsidio (No radicado)-Credito (aprobado) |
| NR | R | **Pdt un Radicado** | Subsidio (radicado)-Credito (No radicado) |
| R | R | **Radicados** | Subsidio (radicado)-Credito (radicado) |
| A | R | **Radicados** | Subsidio (radicado)-Credito (aprobado) |
| NR | A | **Pdt un Radicado** | Subsidio (aprobado)-Credito (No radicado) |
| R | A | **Radicados** | Subsidio (aprobado)-Credito (radicado) |
| A | A | **Listo** | — |

Un cliente ya escriturado siempre queda en `Listo` (ya no tiene nada pendiente). La categoría
**no** depende de si la unidad está marcada como "atada" (ver punto 4) — son dos cosas
independientes.

## 3. Año proyectado vs. año de escritura real

Hay dos campos de año distintos, y es fácil confundirlos:

- **`escritura_programada_anio`**: el año en que se *proyecta* escriturar (solo aplica a
  clientes aún no escriturados; para los ya escriturados casi siempre está vacío, porque es un
  campo de proyección a futuro, no de registro histórico).
- **Año de escritura real** (`fecha_escritura`): el año en que el cliente *efectivamente* se
  escrituró. Es el que se usa para el KPI "Total Unidades Escrituradas" del dashboard.

## 4. Unidades atadas

Una unidad "atada" es una unidad con algún bloqueo de identidad/trámite ajeno al avance normal
de subsidio/crédito. Se calcula de **dos fuentes independientes**, combinadas con un OR (si
cualquiera de las dos la marca, queda marcada):

1. **Estado de cuentas** (Drive): la identificación registrada para esa unidad en el archivo de
   estado de cuentas del proyecto no coincide con la identificación del cliente.
2. **Fiducia**: el cliente tiene un registro de "Rechazo de vinculación por parte de la fiducia"
   sin un registro posterior de "Legalización Fiducia".

**Ambas fuentes solo se evalúan para clientes NO escriturados** — una unidad ya escriturada
nunca se marca como atada, sin importar lo que digan esas otras fuentes.

## 5. Clientes desistidos (excluidos del informe)

Existe una lista de negocios que **se desistieron** de su compra (ver
`data/referencia/clientes_desistidos.csv`, mantenida a mano por el equipo). Esos clientes se
excluyen de todo el informe desde el momento en que se cargan los datos — no aparecen en
`detalle_clientes.csv` ni en ningún cálculo, porque en la práctica esas unidades no están
vendidas.

## 6. El corte de comité

El informe se compara mes a mes contra el corte que se presentó en el comité de ese mes — no
contra "el primero del mes" ni contra una ventana fija de días. Esa fecha vive en
`data/referencia/cortes_comite.csv` (una fila por mes: `anio_mes`, `fecha_corte_comite`) y la
actualiza el equipo de negocio a mano, apenas se sabe qué corte se presentó.

`detalle_clientes.csv` y `cambios_vs_comite.csv` comparan siempre contra esa misma fecha, para
quedar alineados con lo que muestra el dashboard HTML.

**Advertencia conocida**: la columna `unidades_atadas_comite` puede no reflejar exactamente el
estado del día del comité — el snapshot de datos de ese día se guarda en el pipeline *antes* de
calcularse `unidades_atadas`, así que puede traer el valor del día anterior. Es una limitación
conocida y aceptada, no un error de cálculo.

## 7. Preguntas típicas que estos archivos pueden responder

- **"¿Qué clientes cambiaron de categoría desde el comité?"** → filtrar `cambios_vs_comite.csv`
  donde `tipo_cambio` incluya "Categoria:".
- **"¿Cuántos clientes se escrituraron desde el comité?"** → filtrar `cambios_vs_comite.csv`
  donde `tipo_cambio` incluya "Se escrituro".
- **"¿Por qué el total de 'Sin Radicados' bajó?"** → cruzar `detalle_clientes.csv` filtrando
  `categoria_comite == 'Sin Radicados'` y ver en qué `categoria_hoy` quedó cada uno.
- **"¿Qué pasó con el cliente X?"** → buscar su fila en `detalle_clientes.csv` (por nombre,
  módulo o `id_prospecto`) y comparar las columnas `*_comite` contra las de hoy.
