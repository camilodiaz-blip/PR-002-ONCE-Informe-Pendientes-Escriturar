"""
Sube el informe HTML mas reciente (data/reportes/informe_escrituracion_YYYYMMDD.html) a la
carpeta del comite del mes en Google Drive:

    Unidad compartida > COMITE DE PROYECTOS > "0NN INFORME <MES> <AA>"  (la de numero mas alto)

Ej. el 2026-11-23 la carpeta destino es "044 INFORME NOV 26". Si ese dia es un corte de comite
(data/referencia/cortes_comite.csv), el archivo se sube con el sufijo " Comité", igual que se
venia nombrando a mano (ej. "informe_escrituracion_20261104 Comité.html").
Si ya existe un archivo con el mismo nombre en la carpeta, se reemplaza (misma URL), no se duplica.

Uso:
    python publicar_informe_drive.py               # sube el informe mas reciente
    python publicar_informe_drive.py --prueba      # solo muestra que subiria y a donde
    python publicar_informe_drive.py <ruta.html>   # sube un informe especifico

Requisitos:
- Las mismas credenciales de cuenta de servicio de google_drive_utils.py
  (GOOGLE_APPLICATION_CREDENTIALS).
- La carpeta "COMITE DE PROYECTOS" compartida con el correo de la cuenta de servicio con permiso
  de "Colaborador" (Contributor) o superior -- con permiso de solo lectura no puede subir.
"""
import os
import re
import sys
from glob import glob

import pandas as pd

import google_drive_utils as gdu
from api_utils import RUTA_REPORTES, RUTA_REFERENCIA

# https://drive.google.com/drive/folders/1-SUNcUbJwFf_YGV2NFLf-l-4N_TQDrdK  ("COMITE DE PROYECTOS")
CARPETA_COMITE_ID = '1-SUNcUbJwFf_YGV2NFLf-l-4N_TQDrdK'

# Subcarpetas mensuales: "044 INFORME NOV 26", "043 INFORME OCT 26", ...
PATRON_CARPETA_MES = re.compile(r'^\s*(\d+)\s+INFORME\b', re.IGNORECASE)


def carpeta_destino():
    """La subcarpeta 'NNN INFORME ...' con el numero mas alto (la del ultimo comite)."""
    servicio = gdu._cliente_drive()
    try:
        servicio.files().get(fileId=CARPETA_COMITE_ID, fields='id', supportsAllDrives=True).execute(num_retries=3)
    except gdu.HttpError as e:
        if e.resp.status == 404:
            correo = servicio._http.credentials.service_account_email
            raise PermissionError(
                f"La cuenta de servicio {correo} no tiene acceso a la carpeta COMITE DE PROYECTOS. "
                "Compartela con ese correo con permiso de Colaborador (o superior).") from None
        raise

    candidatas = []
    for carpeta in gdu.listar_subcarpetas(CARPETA_COMITE_ID):
        m = PATRON_CARPETA_MES.match(carpeta['name'])
        if m:
            candidatas.append((int(m.group(1)), carpeta['createdTime'], carpeta))
    if not candidatas:
        raise RuntimeError("No se encontro ninguna subcarpeta 'NNN INFORME ...' en COMITE DE PROYECTOS.")
    return max(candidatas, key=lambda c: (c[0], c[1]))[2]


def informe_mas_reciente():
    archivos = sorted(glob(os.path.join(RUTA_REPORTES, 'informe_escrituracion_[0-9]*.html')))
    archivos = [a for a in archivos if re.search(r'informe_escrituracion_\d{8}\.html$', a)]
    if not archivos:
        raise FileNotFoundError(f"No hay informes 'informe_escrituracion_YYYYMMDD.html' en {RUTA_REPORTES}.")
    return archivos[-1]


def _es_corte_comite(fecha_yyyymmdd):
    ruta = os.path.join(RUTA_REFERENCIA, 'cortes_comite.csv')
    if not os.path.exists(ruta):
        return False
    cortes = pd.read_csv(ruta, dtype=str)
    fechas = cortes['fecha_corte_comite'].dropna().str.strip().str.replace('-', '')
    return fecha_yyyymmdd in set(fechas)


def nombre_en_drive(ruta_informe):
    base = os.path.basename(ruta_informe)
    m = re.search(r'_(\d{8})\.html$', base)
    if m and _es_corte_comite(m.group(1)):
        return base[:-len('.html')] + ' Comité.html'
    return base


def run(ruta_informe=None, prueba=False):
    ruta_informe = ruta_informe or informe_mas_reciente()
    nombre = nombre_en_drive(ruta_informe)
    destino = carpeta_destino()
    print(f"Informe: {ruta_informe} ({os.path.getsize(ruta_informe) / 1e6:.1f} MB)")
    print(f"Destino: COMITE DE PROYECTOS / {destino['name']} / {nombre}")
    if prueba:
        print("(prueba: no se subio nada)")
        return None

    archivo = gdu.subir_archivo(ruta_informe, destino['id'], nombre=nombre, mime_type='text/html')
    print(f"Informe {archivo['accion']} en Drive: {archivo['webViewLink']}")
    return archivo


if __name__ == '__main__':
    argumentos = [a for a in sys.argv[1:] if a != '--prueba']
    run(argumentos[0] if argumentos else None, prueba='--prueba' in sys.argv)
