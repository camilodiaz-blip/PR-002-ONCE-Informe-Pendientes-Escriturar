"""
Utilidades para leer archivos de una carpeta de Google Drive usando una cuenta de servicio
(Service Account) -- pensado para correr en un servidor, donde no se puede depender de tener
Google Drive para escritorio instalado y montado como unidad local (como pasa hoy en el PC,
con la unidad G:\\).

Requiere las librerias (ya instaladas en .venv):
    pip install google-api-python-client google-auth google-auth-httplib2

=== Configuracion previa, UNA SOLA VEZ, en https://console.cloud.google.com/ ===

1. Crear (o reutilizar) un proyecto de Google Cloud.
2. Habilitar la API de Google Drive:
   APIs & Services > Library > buscar "Google Drive API" > Enable.
3. Crear una cuenta de servicio:
   IAM & Admin > Service Accounts > Create Service Account.
   Anota el correo que le asigna, algo como:
   nombre-cuenta@tu-proyecto.iam.gserviceaccount.com
4. Generar una clave para esa cuenta de servicio:
   Entra a la cuenta de servicio > pestaña "Keys" > Add Key > Create new key > JSON.
   Se descarga un archivo .json -- esa es la credencial.
5. Compartir la carpeta/unidad de Drive con el correo de la cuenta de servicio, igual que
   la compartirias con una persona (o, si es una Unidad Compartida completa, agregala como
   miembro de la Unidad Compartida en vez de compartir solo una carpeta).
6. En el SERVIDOR (no en el repositorio / control de versiones), guardar el archivo .json de
   la clave en una ruta segura, y apuntar la variable de entorno GOOGLE_APPLICATION_CREDENTIALS
   a esa ruta -- o pasar la ruta directo a las funciones de este modulo con `ruta_credenciales`.

=== Como encontrar el ID de una carpeta ===

Es el ultimo segmento de la URL cuando abres la carpeta en drive.google.com:
    https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz
                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^ eso es el carpeta_id
"""
import io
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Solo lectura -- este modulo no necesita (ni deberia tener) permiso de escritura en Drive.
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def _cliente_drive(ruta_credenciales=None):
    """
    Crea el cliente autenticado de la API de Drive.

    ruta_credenciales: ruta al JSON de la cuenta de servicio. Si no se pasa, se usa la
    variable de entorno GOOGLE_APPLICATION_CREDENTIALS.
    """
    ruta_credenciales = ruta_credenciales or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not ruta_credenciales:
        raise RuntimeError(
            "No se encontraron credenciales de Google. Pasa ruta_credenciales, o define la "
            "variable de entorno GOOGLE_APPLICATION_CREDENTIALS con la ruta al JSON de la "
            "cuenta de servicio (ver instrucciones al inicio de este archivo)."
        )
    if not os.path.exists(ruta_credenciales):
        raise FileNotFoundError(f"No existe el archivo de credenciales: {ruta_credenciales}")

    credenciales = service_account.Credentials.from_service_account_file(ruta_credenciales, scopes=SCOPES)
    return build('drive', 'v3', credentials=credenciales)


def listar_archivos(carpeta_id, ruta_credenciales=None, incluir_subcarpetas=False):
    """
    Lista los archivos dentro de una carpeta de Drive.

    carpeta_id: ID de la carpeta (ver instrucciones arriba de como obtenerlo).
    incluir_subcarpetas: si True, tambien entra recursivamente a las subcarpetas.

    Retorna una lista de dicts: {id, name, mimeType, modifiedTime}.
    """
    servicio = _cliente_drive(ruta_credenciales)
    archivos = []
    carpetas_pendientes = [carpeta_id]

    while carpetas_pendientes:
        carpeta_actual = carpetas_pendientes.pop()
        page_token = None
        while True:
            respuesta = servicio.files().list(
                q=f"'{carpeta_actual}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token,
                # Necesario para que aparezcan archivos de Unidades Compartidas (no solo "Mi unidad").
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for archivo in respuesta.get('files', []):
                if archivo['mimeType'] == 'application/vnd.google-apps.folder':
                    if incluir_subcarpetas:
                        carpetas_pendientes.append(archivo['id'])
                else:
                    archivos.append(archivo)

            page_token = respuesta.get('nextPageToken')
            if not page_token:
                break

    return archivos


def descargar_archivo(archivo_id, ruta_destino, ruta_credenciales=None):
    """Descarga un archivo de Drive (tal cual, binario) a ruta_destino en disco."""
    servicio = _cliente_drive(ruta_credenciales)
    request = servicio.files().get_media(fileId=archivo_id, supportsAllDrives=True)

    os.makedirs(os.path.dirname(ruta_destino) or '.', exist_ok=True)
    with io.FileIO(ruta_destino, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    return ruta_destino


def leer_bytes(archivo_id, ruta_credenciales=None):
    """Descarga un archivo de Drive directo a memoria (BytesIO), sin tocar el disco."""
    servicio = _cliente_drive(ruta_credenciales)
    request = servicio.files().get_media(fileId=archivo_id, supportsAllDrives=True)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    return buffer


def leer_excel(archivo_id, ruta_credenciales=None, **kwargs_read_excel):
    """Lee un .xlsx de Drive directo a un DataFrame de pandas, sin guardarlo en disco."""
    import pandas as pd
    return pd.read_excel(leer_bytes(archivo_id, ruta_credenciales), **kwargs_read_excel)


def leer_csv(archivo_id, ruta_credenciales=None, **kwargs_read_csv):
    """Lee un .csv de Drive directo a un DataFrame de pandas, sin guardarlo en disco."""
    import pandas as pd
    return pd.read_csv(leer_bytes(archivo_id, ruta_credenciales), **kwargs_read_csv)


if __name__ == "__main__":
    # Prueba rapida manual: python google_drive_utils.py <carpeta_id> [ruta_credenciales]
    import sys

    if len(sys.argv) < 2:
        print("Uso: python google_drive_utils.py <carpeta_id> [ruta_credenciales]")
        raise SystemExit(1)

    carpeta_id_arg = sys.argv[1]
    ruta_credenciales_arg = sys.argv[2] if len(sys.argv) > 2 else None

    for archivo in listar_archivos(carpeta_id_arg, ruta_credenciales_arg):
        print(f"{archivo['id']}  {archivo['name']}  ({archivo['mimeType']})")
