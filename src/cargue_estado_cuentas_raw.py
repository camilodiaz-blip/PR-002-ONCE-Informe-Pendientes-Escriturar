"""
Trae los archivos "EstadoCuenta_<proyecto>_..." de una carpeta de Google Drive (via cuenta de
servicio, ver google_drive_utils.py) y extrae, por cada proyecto, las columnas Proyecto,
Unidad, Identificacion y Cliente.

Cada archivo trae el proyecto en el nombre (ej. "EstadoCuenta_cristales__5-8-26.xlsx"), no en
una columna de la hoja -- el titulo dentro del Excel (fila 2) no es consistente entre
proyectos (unos traen "... - CRISTALES ET1YET2", otros "FAI VERDE OLIVA ET 1", sin un patron
comun), asi que el nombre de archivo es la fuente mas confiable para identificar el proyecto.

Si hay mas de un archivo para el mismo proyecto (varias versiones subidas en distintas
fechas), se toma solo la version mas reciente, por fecha de modificacion en Drive
(modifiedTime), no por la fecha que traiga el nombre del archivo.

Requiere las credenciales de la cuenta de servicio ya configuradas (ver
GOOGLE_APPLICATION_CREDENTIALS / google_drive_utils.py) y openpyxl instalado.
"""
import re
from datetime import datetime

import pandas as pd

import google_drive_utils as gdu
from api_utils import guardar_parquet_versionado, RUTA_RAW_ESTADO_CUENTAS

# ID de la carpeta de Drive de donde se traen los archivos de estado de cuenta.
CARPETA_DRIVE_ID = '1QITlecqAkvzVY3bdcLnIvDUsQg8z_ZiY'

# Clave del proyecto en el nombre de archivo -> nombre canonico, igual al usado en el resto
# del pipeline (columna 'proyecto' de clientes_detallado.csv), para que se pueda cruzar despues.
PROYECTOS_CONOCIDOS = {
    'cristales': 'Cristales',
    'candil': 'Candil',
    'oliva': 'Verdeoliva',
    'lima': 'VERDELIMA',
}

COLUMNAS_SALIDA = ['Proyecto', 'Unidad', 'Identificacion', 'Cliente']


def _extraer_clave_proyecto(nombre_archivo):
    """De 'EstadoCuenta_cristales__5-8-26.xlsx' extrae 'cristales'."""
    m = re.match(r'EstadoCuenta_+([a-zA-Z]+)', nombre_archivo)
    return m.group(1).lower() if m else None


def _archivos_mas_recientes_por_proyecto(archivos):
    """De una lista de archivos 'EstadoCuenta_*', se queda con el mas reciente por proyecto."""
    mas_reciente = {}
    for archivo in archivos:
        clave = _extraer_clave_proyecto(archivo['name'])
        if clave is None:
            print(f"Aviso: no se pudo identificar el proyecto en '{archivo['name']}', se omite.")
            continue
        actual = mas_reciente.get(clave)
        if actual is None or archivo['modifiedTime'] > actual['modifiedTime']:
            mas_reciente[clave] = archivo
    return mas_reciente


def _leer_estado_cuenta(archivo, clave_proyecto):
    """
    Lee un archivo de estado de cuenta y devuelve Proyecto/Unidad/Identificacion/Cliente.
    La hoja trae 3 filas de titulo antes del encabezado real (header=3), y dos columnas
    llamadas "Unidad": la primera es el texto ("Torre 1 Apto 1006", igual al 'modulo' que
    usa el resto del pipeline), la segunda es un codigo interno numerico -- se usa la primera.
    """
    proyecto = PROYECTOS_CONOCIDOS.get(clave_proyecto, clave_proyecto.capitalize())
    df = gdu.leer_excel(archivo['id'], header=3)
    df = df.rename(columns={'Identificación': 'Identificacion'})

    columnas_necesarias = ['Unidad', 'Identificacion', 'Cliente']
    columnas_faltantes = [c for c in columnas_necesarias if c not in df.columns]
    if columnas_faltantes:
        print(f"Aviso: columnas faltantes {columnas_faltantes} en '{archivo['name']}'.")

    resultado = df[[c for c in columnas_necesarias if c in df.columns]].copy()
    resultado = resultado.dropna(subset=['Unidad']) if 'Unidad' in resultado.columns else resultado
    resultado.insert(0, 'Proyecto', proyecto)
    resultado['archivo_origen'] = archivo['name']
    return resultado


def run():
    archivos = gdu.listar_archivos(CARPETA_DRIVE_ID)
    estado_cuenta = [a for a in archivos if a['name'].startswith('EstadoCuenta')]
    if not estado_cuenta:
        print("No se encontraron archivos 'EstadoCuenta' en la carpeta de Drive.")
        return None

    mas_recientes = _archivos_mas_recientes_por_proyecto(estado_cuenta)
    print(f"Proyectos encontrados: {sorted(mas_recientes.keys())}")

    tablas = []
    for clave, archivo in mas_recientes.items():
        print(f"Leyendo {archivo['name']} (proyecto: {clave})...")
        tablas.append(_leer_estado_cuenta(archivo, clave))

    resultado = pd.concat(tablas, ignore_index=True)
    resultado['raw_fecha_cargue'] = datetime.now().strftime('%Y%m%d')

    ruta = guardar_parquet_versionado(resultado, RUTA_RAW_ESTADO_CUENTAS, "estado_cuentas")
    print(f"Guardado en {ruta} ({len(resultado)} filas, {resultado['Proyecto'].nunique()} proyectos)")
    return ruta


if __name__ == "__main__":
    run()
