import os
import re
import pandas as pd
from glob import glob

from api_utils import RUTA_RAW_CLIENTES, RUTA_STAGING, RUTA_REFERENCIA

# La API de Smarthome no trae la torre como campo separado (moduleCode/moduleAddress vienen
# vacios) -- viene embebida como texto libre en 'modulo' (ej. "Torre 5 Apto 1107",
# "TORRE 1 Apto 0203"). Se extrae con esta regex; validado contra los 10 proyectos: 94.7% de
# las filas calzan, el resto son casas (sin torre, ej. "Las Mañanitas Casas") o registros
# atipicos -- en esos casos 'torre' queda vacio en vez de forzar un valor.
_RE_TORRE = re.compile(r'torre\s*0*(\d+)', re.IGNORECASE)


def _extraer_torre(modulo):
    m = _RE_TORRE.search(str(modulo))
    return f"Torre {int(m.group(1))}" if m else None


def _excluir_desistidos(df):
    """
    Quita del staging a los clientes que ya desistieron de su compra (lista mantenida a mano
    en data/referencia/clientes_desistidos.csv, cruzada por id_prospecto -- unico identificador
    confiable, el nombre/modulo puede tener variaciones de formato).

    Smarthome no borra ni marca estos registros de ninguna forma identificable automaticamente
    (siguen con una 'etapa_venta' de venta normal), asi que esos apartamentos en realidad NO
    estan vendidos y no deberian aparecer en ningun calculo del informe -- se filtran aca, en
    el staging, para que ya no lleguen a ningun paso de adelante (pagos, tareas, dashboard).
    """
    ruta = os.path.join(RUTA_REFERENCIA, "clientes_desistidos.csv")
    if not os.path.exists(ruta):
        return df

    desistidos = pd.read_csv(ruta, encoding='utf-8-sig')
    ids_desistidos = set(desistidos['id_prospecto'].astype(str).str.strip().str.lower())

    id_prospecto_limpio = df['id_prospecto'].astype(str).str.strip().str.lower()
    es_desistido = id_prospecto_limpio.isin(ids_desistidos)

    encontrados = id_prospecto_limpio[es_desistido].unique()
    no_encontrados = ids_desistidos - set(encontrados)
    print(f"Clientes desistidos excluidos del staging: {es_desistido.sum()} de {len(desistidos)} "
          f"en la lista de referencia.")
    if no_encontrados:
        print(f"ADVERTENCIA: {len(no_encontrados)} id_prospecto de clientes_desistidos.csv "
              "no se encontraron en el cargue actual (revisar si el id es correcto o si el "
              "cliente ya no aparece en ningun proyecto):")
        for id_prospecto in sorted(no_encontrados):
            print(f"  - {id_prospecto}")

    return df[~es_desistido].copy()


def run():
    #Cargue de clientes
    archivos = glob(os.path.join(RUTA_RAW_CLIENTES, "*.parquet"))
    df = pd.concat([pd.read_parquet(archivo) for archivo in archivos], ignore_index=True)

    df = df[['project', 'projectCode','prospectId','firstName','lastName','identificationNumber','module',
             'stageName','agreementNumber','registrationNumber','closeDate','deedDate','deedScheduledDate',
             'ownerId']]

    df['closeDate'] = pd.to_datetime(df['closeDate'], errors='coerce')
    df['deedDate'] = pd.to_datetime(df['deedDate'], errors='coerce')

    df.rename(columns={
        'project': 'proyecto',
        'projectCode': 'id_proyecto',
        'prospectId': 'id_prospecto',
        'firstName': 'nombre',
        'lastName': 'apellido',
        'identificationNumber': 'numero_identificacion',
        'module': 'modulo',
        'stageName': 'etapa_venta',
        'agreementNumber': 'encargo',
        'registrationNumber': 'numero_escritura',
        'closeDate': 'fecha_cierre',
        'deedDate': 'fecha_escritura',
        'deedScheduledDate':'fecha_escritura_programada',
        'ownerId': 'id_asesor'
    }, inplace=True)

    df['escriturado']=df['fecha_escritura'].notnull().astype(int)

    # La API de Smarthome entrega algunos nombres de proyecto/modulo con espacios de mas
    # (ej. "VERDELIMA " con espacio al final) -- se limpia aca, en el cargue inicial, para que
    # todo lo que viene despues (staging, cruces con pagos/tareas, dashboard, historico) ya
    # trabaje con el nombre correcto, sin tener que repetir el strip() en cada script.
    df['proyecto'] = df['proyecto'].astype(str).str.strip()
    df['modulo'] = df['modulo'].astype(str).str.strip()
    df['torre'] = df['modulo'].apply(_extraer_torre)

    df = _excluir_desistidos(df)

    os.makedirs(RUTA_STAGING, exist_ok=True)
    ruta_archivo = os.path.join(RUTA_STAGING, "clientes.parquet")
    df.to_parquet(ruta_archivo, index=False, compression='snappy')


if __name__ == "__main__":
    run()

