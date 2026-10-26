"""
Analisis de conversaciones por cliente: toma los eventos de CRM ya filtrados a los ultimos
meses (data/staging/conversaciones.parquet, ver cargue_conversaciones_staging.py) y produce
una fila por cliente con 2 categorias -- cual fue la ultima gestion del SISTEMA (back-office:
documentos, plan de pagos, tramites...) y cual fue el ultimo SEGUIMIENTO real (llamadas,
visitas, whatsapp, correos, notas de asesor...) -- y hace cuantos dias fue cada una.

Implementa la clasificacion de eventos descrita en PROMPT_detalle_por_cliente.md, adaptado a
las convenciones de este proyecto (sin argparse, usa las rutas centralizadas de api_utils.py)
y con 2 diferencias deliberadas: la fila final se identifica por proyecto + modulo (mas util
para el negocio) en vez del prospectId crudo, y ya no se distingue "gestion humana" vs.
"automatizada" dentro del seguimiento -- esa division no aportaba (mucho de lo etiquetado como
automatico por `action` resulta ser una interaccion real al leer `content`); en su lugar se
reportan las 2 categorias de arriba (sistema vs. seguimiento) con su propia recencia.
"""
import json
import os
import re
import unicodedata

import pandas as pd

from api_utils import RUTA_STAGING, RUTA_ANALYTICS

# Largo minimo (caracteres) de un `content` sin clasificar para tratarlo como nota humana
# (SEGUIMIENTO_MANUAL) en vez de dejarlo en SIN_CLASIFICAR -- ver _clasificar_eventos.
UMBRAL_LONGITUD_NOTA_MANUAL = 25

# Reglas de clasificacion, en el orden en que se evaluan -- gana la PRIMERA que coincide.
# Cada tupla: (tipo_interaccion, canal, naturaleza, direccion, patron_regex).
# direccion=None equivale a "NA" en el prompt original.
REGLAS_CLASIFICACION = [
    # --- Bloque A: interacciones con el cliente ---
    ('LLAMADA', 'TELEFONO', 'INTERACCION', None,
     r'^llamada (?:realizada|recibida):'),
    ('WHATSAPP_SALIENTE', 'WHATSAPP', 'INTERACCION', 'SALIENTE',
     r'se ha enviado por whatsapp|se envia plantilla de whatsapp|se envio plantilla de whatsapp|plantilla de whatsapp'),
    ('WHATSAPP_ENTRANTE', 'WHATSAPP', 'INTERACCION', 'ENTRANTE',
     r'nuevo mensaje por whatsapp|solicitado contacto via whatsapp'),
    ('CORREO_APERTURA', 'CORREO', 'INTERACCION', 'ENTRANTE',
     r'se ha abierto el correo'),
    ('CORREO_SALIENTE', 'CORREO', 'INTERACCION', 'SALIENTE',
     # "enviado" se agrega a la conjugacion original (envio/envia) del prompt -- misma
     # categoria, solo le faltaba esa forma verbal ("se ha enviado un correo...").
     r'se (?:ha )?envi(?:o|a|ado) (?:un )?correo|envio de correo|correo de bienvenida|envio informacion - via mail|se genero envio de cotizacion|activacion - envio correo|se envia correo'),
    ('LEAD_BOT', 'CHAT_BOT', 'INTERACCION', 'ENTRANTE',
     r'desde el bot|contacto bot|marcado la opcion "contacto con asesor"'),
    ('REGISTRO_PROSPECTO', 'MIXTO', 'INTERACCION', 'ENTRANTE',
     r'^nuevo registro|se agrega el cliente al sistema|registro por importacion|cliente asignado desde modulo|se asigna lead'),
    ('CITA_AGENDADA', 'MIXTO', 'INTERACCION', 'SALIENTE',
     r'cita agendada|cita programada|visita programada|agendo cita|se ha programado una visita|visita presencial programada|visita virtual programada|llamada programada|peticion de llamada|visita pendiente|llamada confirmacion de cita|whatsapp confirmacion cita'),
    ('CITA_NO_ASISTIDA', 'PRESENCIAL', 'INTERACCION', None,
     r'no asistio a cita'),
    ('VISITA', 'PRESENCIAL', 'INTERACCION', 'ENTRANTE',
     r'visita sala de negocios|visito sala|visito la sala|atendido en sala|visita atendida|cita - presencia|oficina metropolis|visitara la sala'),
    ('COTIZACION', 'MIXTO', 'INTERACCION', 'SALIENTE',
     r'cotizacion realizada|cliente cotiza|se ha generado el documento de cotizacion|documento de cotizacion'),
    ('LLAMADA_SIN_CONTACTO', 'TELEFONO', 'INTERACCION', 'SALIENTE',
     r'no contesto'),
    ('LLAMADA', 'TELEFONO', 'INTERACCION', None,
     r'llamada realizada|llamada recibida|nueva llamada|llamada seguimiento|seguimiento - llamada|llamada/whatsapp|call center'),
    ('SEGUIMIENTO_COMERCIAL', 'MIXTO', 'INTERACCION', 'SALIENTE',
     r'informacion general|se amplio informacion|muy interesado|cliente retoma|seguimiento cliente digital|volver a llamar|contactar al cliente|whatsapp saludo|whatsapp seguimiento|whatsapp despedida'),
    ('DESCARTE', 'MIXTO', 'INTERACCION', None,
     r'no esta interesado|no interesado|dato errado|dar de baja|no tiene cierre financiero'),
    # --- Bloque B: back-office (canal SISTEMA, direccion NA para todas) ---
    ('PLAN_DE_PAGOS', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'plan de pagos|plan de pago|reasignado todos los pagos'),
    ('DOCUMENTO_GENERADO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'se ha generado el documento|ha sido guardado|documento de reasignacion'),
    ('TRAMITE', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'estado de tramites|comentario estado de tramites|los tramites han sido aprobados|legalizacion|escrituracion'),
    ('ACTUALIZACION_DATOS', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'se ha actualizado la informacion|se ha actualizado el detalle|actualizacion automatica|se ha actualizado el prospecto|se ha actualizado el usuario|se ha actualizado el score'),
    ('CARGUE_INTEGRACION', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'cargue automatico|via inte|salesmanago|portal de c|acceso web al portal|paso a paso de portal'),
    ('ESTADO_INMUEBLE', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'estado del inmueble|ha sido liberada|precio ofertado|adicional|se ha cambiado del modulo|la venta ha sido aprobada|reservad|separad'),
    ('REASIGNACION_ASESOR', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'ha sido reasignado|reasignad'),
    ('PAGO_REGISTRADO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'^pago |recibo de caja|se ha registrado el pago|abono'),
    ('CAMBIO_PROYECTO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'se ha cambiado al proyecto|cambio de proyecto|cambiado automaticamente el usuario'),
    ('NEGOCIACION', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'segundo comprador|la venta ha sido|negociacion|comprador'),
    ('CONSENTIMIENTO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'habeas ?data|autoriza tratamiento'),
    ('CARGUE_INTEGRACION', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'lahaus|automatizacion|lead processed|sala de venta qr'),
    # --- Reglas adicionales a las del prompt original: en esta base (cartera "Sin Radicados"
    # / "Pdt un Radicado", post-venta) estos 3 patrones concentran ~43% de lo que quedaba
    # SIN_CLASIFICAR y son claramente sistematicos (no notas libres), asi que se agregan en
    # vez de dejarlos fuera. ---
    ('DOCUMENTO_CARGADO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'se cargo el archivo'),
    ('PREAVISO_MORA', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'preaviso por mora'),
    ('DESISTIMIENTO', 'SISTEMA', 'GESTION_SISTEMA', None,
     r'desistimiento unilateral'),
]
# Compilar una sola vez, no en cada fila.
REGLAS_CLASIFICACION = [
    (tipo, canal, naturaleza, direccion, re.compile(patron))
    for tipo, canal, naturaleza, direccion, patron in REGLAS_CLASIFICACION
]

_RE_LLAMADA_LOG = re.compile(r'^llamada (realizada|recibida):', re.IGNORECASE)
_RE_JSON_BLOB = re.compile(r'\{.*\}', re.S)
_RE_DISPOSITION = re.compile(r'"disposition"\s*:\s*"([^"]*)"')
_RE_TIPO_LLAMADA = re.compile(r'"tipo"\s*:\s*"([^"]*)"')
_RE_DURATION = re.compile(r'"duration"\s*:\s*"?(\d+)"?')

MAPA_DIRECCION_LLAMADA = {'IN': 'ENTRANTE', 'OUT': 'SALIENTE', 'EXT': 'SALIENTE'}


def _normalizar_texto(valor):
    """Quita tildes (NFKD + descarta combinantes), colapsa espacios, pasa a minuscula."""
    texto = str(valor) if pd.notna(valor) else ''
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'\s+', ' ', texto.lower()).strip()
    return texto


def _clasificar_eventos(df):
    """Aplica REGLAS_CLASIFICACION en orden estricto (gana la primera que coincide) y agrega
    las columnas tipo_interaccion / canal / naturaleza / direccion."""
    texto = (
        df['action'].apply(_normalizar_texto) + ' || ' + df['content'].apply(_normalizar_texto)
    )

    tipo = pd.Series(pd.NA, index=df.index, dtype='object')
    canal = pd.Series(pd.NA, index=df.index, dtype='object')
    naturaleza = pd.Series(pd.NA, index=df.index, dtype='object')
    direccion = pd.Series(pd.NA, index=df.index, dtype='object')

    pendientes = pd.Series(True, index=df.index)
    for tipo_regla, canal_regla, naturaleza_regla, direccion_regla, patron in REGLAS_CLASIFICACION:
        if not pendientes.any():
            break
        coincide = pendientes & texto.str.contains(patron, na=False)
        tipo[coincide] = tipo_regla
        canal[coincide] = canal_regla
        naturaleza[coincide] = naturaleza_regla
        direccion[coincide] = direccion_regla
        pendientes &= ~coincide

    # De lo que no calzo con ninguna regla: si el contenido es una nota "larga" (no una
    # plantilla corta de sistema -- esas ya deberian haber calzado con alguna regla del Bloque
    # B), casi siempre es una nota libre de un asesor describiendo una interaccion real con el
    # cliente (llamada, correo, negociacion, seguimiento de mora), aunque `action` diga "Evento
    # del Sistema". Se valido con datos reales: de las notas sin clasificar, el 98.5% tiene 25+
    # caracteres y son narrativas humanas (ej. "cliente informa que...", "se llamo y dijo...");
    # las que quedan por debajo del umbral son ruido real ("ok", ".", "OK YA PAGO"). Por eso se
    # cuentan como interaccion humana generica en vez de quedar invisibles en SIN_CLASIFICAR.
    longitud_content = df['content'].fillna('').str.strip().str.len()
    es_nota_sustancial = pendientes & (longitud_content >= UMBRAL_LONGITUD_NOTA_MANUAL)
    tipo[es_nota_sustancial] = 'SEGUIMIENTO_MANUAL'
    canal[es_nota_sustancial] = 'MIXTO'
    naturaleza[es_nota_sustancial] = 'INTERACCION'
    pendientes &= ~es_nota_sustancial

    # Fallback final: lo que sigue pendiente es ruido real (notas triviales tipo "ok", ".").
    tipo[pendientes] = 'SIN_CLASIFICAR'
    canal[pendientes] = 'DESCONOCIDO'
    naturaleza[pendientes] = 'DESCONOCIDO'

    df = df.copy()
    df['tipo_interaccion'] = tipo
    df['canal'] = canal
    df['naturaleza'] = naturaleza
    df['direccion'] = direccion
    return df


def _extraer_datos_llamada(content):
    """Disposition/tipo/duration del JSON de central telefonica incrustado en `content`. Si el
    JSON viene truncado (json.loads falla, o ni siquiera se encuentra un bloque {...} completo),
    rescata los 3 campos por regex individual en vez de perder el evento completo."""
    match = _RE_JSON_BLOB.search(content)
    if match:
        try:
            data = json.loads(match.group(0))
            return data.get('disposition'), data.get('tipo'), data.get('duration')
        except (json.JSONDecodeError, ValueError):
            pass
    disposition = _RE_DISPOSITION.search(content)
    tipo = _RE_TIPO_LLAMADA.search(content)
    duration = _RE_DURATION.search(content)
    return (
        disposition.group(1) if disposition else None,
        tipo.group(1) if tipo else None,
        duration.group(1) if duration else None,
    )


def _enriquecer_llamadas(df):
    """Para eventos cuyo `content` es un log de central telefonica (`llamada realizada:`/
    `recibida:` seguido de un JSON), extrae duracion, sobrescribe direccion y reclasifica
    tipo_interaccion en LLAMADA_CONTESTADA / LLAMADA_NO_CONTESTADA segun `disposition`."""
    df = df.copy()
    df['duracion_seg'] = pd.NA

    contenido = df['content'].fillna('')
    es_llamada_log = contenido.str.match(_RE_LLAMADA_LOG)
    if not es_llamada_log.any():
        df['duracion_seg'] = pd.to_numeric(df['duracion_seg'], errors='coerce')
        return df

    detalle = contenido[es_llamada_log].apply(
        lambda c: pd.Series(_extraer_datos_llamada(c), index=['disposition', 'tipo_llamada', 'duration'])
    )

    df.loc[es_llamada_log, 'duracion_seg'] = pd.to_numeric(detalle['duration'], errors='coerce')

    direccion_nueva = detalle['tipo_llamada'].map(MAPA_DIRECCION_LLAMADA)
    direccion_actual = df.loc[es_llamada_log, 'direccion']
    df.loc[es_llamada_log, 'direccion'] = direccion_nueva.where(direccion_nueva.notna(), direccion_actual)

    contestada = detalle['disposition'].eq('ANSWERED')
    no_contestada = detalle['disposition'].notna() & ~contestada
    df.loc[detalle.index[contestada], 'tipo_interaccion'] = 'LLAMADA_CONTESTADA'
    df.loc[detalle.index[no_contestada], 'tipo_interaccion'] = 'LLAMADA_NO_CONTESTADA'

    df['duracion_seg'] = pd.to_numeric(df['duracion_seg'], errors='coerce')
    return df


def _ultimo_por_naturaleza(df, universo, fecha_corte, naturaleza, columna_tipo, columna_dias):
    """Para cada cliente, el tipo_interaccion y los dias transcurridos desde su evento mas
    reciente de una `naturaleza` puntual (INTERACCION o GESTION_SISTEMA). Vacio si el cliente
    no tiene ningun evento de esa naturaleza dentro de la ventana."""
    subset = df[df['naturaleza'] == naturaleza]
    ultimo = subset.sort_values('date').groupby('prospectId').tail(1).set_index('prospectId')
    tipo = ultimo['tipo_interaccion'].reindex(universo)
    dias = (fecha_corte - ultimo['date'].reindex(universo)).dt.days
    return pd.DataFrame({columna_tipo: tipo, columna_dias: dias}, index=universo)


def _resumen_por_cliente(df, fecha_corte):
    """Agrega `df` (un evento por fila, ya clasificado) a una fila por prospectId, incluyendo
    a los que no tuvieron ningun evento de alguna de las 2 naturalezas (nunca se pierden por
    un inner join). 2 categorias, cada una con su propio "hace cuanto":
      - ultima_gestion_sistema / dias_gestion_sistema: el back-office mas reciente (naturaleza
        GESTION_SISTEMA -- documentos, plan de pagos, tramites, etc.).
      - ultimo_seguimiento / dias_seguimiento: la interaccion real mas reciente (naturaleza
        INTERACCION -- llamadas, visitas, whatsapp, correos, notas de asesor, etc.).
    """
    universo = pd.Index(df['prospectId'].unique(), name='prospectId')

    resultado = pd.DataFrame(index=universo)
    resultado = resultado.join(_ultimo_por_naturaleza(
        df, universo, fecha_corte, 'GESTION_SISTEMA', 'ultima_gestion_sistema', 'dias_gestion_sistema'
    ))
    resultado = resultado.join(_ultimo_por_naturaleza(
        df, universo, fecha_corte, 'INTERACCION', 'ultimo_seguimiento', 'dias_seguimiento'
    ))

    return resultado.reset_index()


def run():
    ruta_entrada = os.path.join(RUTA_STAGING, "conversaciones.parquet")
    df = pd.read_parquet(ruta_entrada)
    total_eventos_entrada = len(df)
    clientes_entrada = df['prospectId'].nunique()

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    fecha_corte = df['date'].max()

    df = _clasificar_eventos(df)
    df = _enriquecer_llamadas(df)
    resumen = _resumen_por_cliente(df, fecha_corte)

    # Cruce con clientes_detallado.csv para traer proyecto + modulo (en vez del prospectId
    # crudo, que no dice nada por si solo para el negocio) y el asesor asignado.
    clientes = pd.read_csv(os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv"))
    clientes = clientes[['id_prospecto', 'proyecto', 'modulo', 'asesor']].drop_duplicates(subset='id_prospecto')
    resumen = resumen.merge(clientes, how='left', left_on='prospectId', right_on='id_prospecto')

    sin_match = resumen['proyecto'].isna().sum()
    if sin_match:
        print(f"ADVERTENCIA: {sin_match} clientes de conversaciones no se encontraron en "
              "clientes_detallado.csv (proyecto/modulo quedan vacios para esos).")

    columnas_finales = [
        'proyecto', 'modulo', 'asesor',
        'ultima_gestion_sistema', 'dias_gestion_sistema',
        'ultimo_seguimiento', 'dias_seguimiento',
    ]
    resumen = resumen[columnas_finales]
    resumen = resumen.sort_values('dias_seguimiento', ascending=False, na_position='first')

    os.makedirs(RUTA_ANALYTICS, exist_ok=True)
    ruta_salida = os.path.join(RUTA_ANALYTICS, "conversaciones_detalle_por_cliente.csv")
    resumen.to_csv(ruta_salida, index=False, encoding='utf-8-sig')

    # --- Validaciones (ver PROMPT_detalle_por_cliente.md, seccion 9) ---
    total_sin_clasificar = (df['tipo_interaccion'] == 'SIN_CLASIFICAR').sum()
    cobertura = 1 - (total_sin_clasificar / total_eventos_entrada) if total_eventos_entrada else 1
    if cobertura < 0.95:
        print(f"ADVERTENCIA: cobertura de clasificacion {cobertura:.1%} por debajo del 95% esperado.")

    clientes_con_seguimiento = int(resumen['ultimo_seguimiento'].notna().sum())
    clientes_con_evento_interaccion = df.loc[df['naturaleza'] == 'INTERACCION', 'prospectId'].nunique()
    clientes_con_gestion_sistema = int(resumen['ultima_gestion_sistema'].notna().sum())
    clientes_con_evento_sistema = df.loc[df['naturaleza'] == 'GESTION_SISTEMA', 'prospectId'].nunique()

    print("\n=== Validacion ===")
    print(f"Cobertura de clasificacion: {cobertura:.1%} "
          f"({total_eventos_entrada - total_sin_clasificar} de {total_eventos_entrada} eventos)")
    print(f"Clientes con 'ultimo_seguimiento': {clientes_con_seguimiento} "
          f"vs. clientes con algun evento naturaleza=='INTERACCION': {clientes_con_evento_interaccion} "
          f"({'OK' if clientes_con_seguimiento == clientes_con_evento_interaccion else 'DESAJUSTE'})")
    print(f"Clientes con 'ultima_gestion_sistema': {clientes_con_gestion_sistema} "
          f"vs. clientes con algun evento naturaleza=='GESTION_SISTEMA': {clientes_con_evento_sistema} "
          f"({'OK' if clientes_con_gestion_sistema == clientes_con_evento_sistema else 'DESAJUSTE'})")
    print(f"Clientes en el archivo de entrada: {clientes_entrada} "
          f"vs. filas en la salida: {len(resumen)} "
          f"({'OK' if clientes_entrada == len(resumen) else 'FALTAN CLIENTES'})")

    top_sin_clasificar = (
        df[df['tipo_interaccion'] == 'SIN_CLASIFICAR']['content'].value_counts().head(15)
    )
    print("\nTop 15 'content' mas frecuentes sin clasificar:")
    print(top_sin_clasificar.to_string())

    print("\n=== Resumen ===")
    print(f"Total de eventos procesados: {total_eventos_entrada}")
    print(f"Ventana efectiva: {df['date'].min()} a {df['date'].max()}")
    print("Ultima gestion en el sistema, por tipo (top 10):")
    print(resumen['ultima_gestion_sistema'].value_counts().head(10).to_string())
    print("\nUltimo seguimiento, por tipo (top 10):")
    print(resumen['ultimo_seguimiento'].value_counts().head(10).to_string())
    print(f"\nArchivo generado en {ruta_salida}")

    return ruta_salida


if __name__ == "__main__":
    run()
