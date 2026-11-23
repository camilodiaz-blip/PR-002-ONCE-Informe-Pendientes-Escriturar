"""
Orquesta el pipeline completo del informe de pendientes por escriturar:

1 (clientes raw) -> 2 (clientes staging) -> 3 (pagos raw, 1 sola llamada masiva)
-> 4 (tareas de no escriturados, por cliente) -> 5 (consolidado final)
-> estado de cuentas raw (Drive) -> unidades atadas (cruce vs. estado de cuentas)
-> unidades atadas por fiducia (cruce vs. tareas/tramites)
-> 6 (dashboard HTML) -> publicar el informe en Drive (COMITE DE PROYECTOS, ver
publicar_informe_drive.py; si falla solo avisa)

El circuito de conversaciones (cargue_conversaciones_raw.py -> cargue_conversaciones_staging.py
-> analisis_conversaciones.py) NO esta incluido aca por el momento -- se saco de main.py a
pedido explicito (2026-09-28), se corre aparte, manualmente, cuando se pide.

Los pasos 3 y 4 ya no se combinan: el paso 3 (3_cargue_pagos_raw.py) trae TODOS los pagos
en una sola llamada a la API (GetPaymentsRecords), no una llamada por cliente, asi que ya
no hay beneficio de rendimiento en compartir el ThreadPoolExecutor con el paso 4 (que si
sigue siendo una llamada por cliente).

El paso de estado de cuentas (cargue_estado_cuentas_raw.py) depende de la API de Google
Drive (cuenta de servicio) en vez de la API de Smarthome, y hoy el dashboard todavia no
consume ese archivo -- por eso, si falla (ej. credenciales no configuradas en esta maquina,
sin red hacia Drive), se avisa pero NO se detiene el resto del pipeline.

Las 2 fuentes de "unidades atadas" (estado de cuentas y fiducia, ver actualizar_unidades_atadas.py
y actualizar_unidades_atadas_fiducia.py) son procesos independientes que se pueden correr en
cualquier orden -- cada uno agrega sus propios hallazgos con OR, sin pisar al otro.

Cada paso sigue siendo ejecutable por separado (ej. `python 4_no_escriturados__tareas_raw.py`)
para reprocesar solo uno sin correr todo el pipeline.
"""
import importlib

paso_1 = importlib.import_module("1_cargue_clientes_raw")
paso_2 = importlib.import_module("2_cargue_clientes_staging")
paso_3 = importlib.import_module("3_cargue_pagos_raw")
paso_4 = importlib.import_module("4_no_escriturados__tareas_raw")
paso_5 = importlib.import_module("5_no_escriturados_staging")
paso_estado_cuentas = importlib.import_module("cargue_estado_cuentas_raw")
paso_unidades_atadas = importlib.import_module("actualizar_unidades_atadas")
paso_unidades_atadas_fiducia = importlib.import_module("actualizar_unidades_atadas_fiducia")
paso_6 = importlib.import_module("6_dashboard")
paso_publicar_drive = importlib.import_module("publicar_informe_drive")


def _guardar_atadas_en_historico():
    """
    El paso 5 guarda la foto del dia (data/historico/clientes_detallado_YYYYMMDD.parquet) ANTES
    de que se calculen las unidades atadas (estado de cuentas y fiducia), asi que la foto quedaba
    sin la columna 'unidades_atadas'. Eso hacia que el comparativo contra el comite
    (generar_detalle_ia.py) tomara 0 atadas en el comite y marcara como "Unidad atada" a todas
    las atadas de hoy. Aca se copia la columna ya calculada (clientes_detallado.csv) a la foto
    del mismo corte.
    """
    import os
    import pandas as pd
    from api_utils import RUTA_ANALYTICS, RUTA_HISTORICO

    actual = pd.read_csv(os.path.join(RUTA_ANALYTICS, "clientes_detallado.csv"), encoding='utf-8-sig',
                         usecols=['id_prospecto', 'unidades_atadas', 'fecha_corte'])
    fecha = str(actual['fecha_corte'].dropna().iloc[0]).replace('-', '')
    ruta = os.path.join(RUTA_HISTORICO, f"clientes_detallado_{fecha}.parquet")
    if not os.path.exists(ruta):
        print(f"ADVERTENCIA: no existe la foto {ruta}; no se pudieron guardar las unidades atadas en el historico.")
        return
    foto = pd.read_parquet(ruta).drop(columns=['unidades_atadas'], errors='ignore')
    atadas = actual.drop_duplicates('id_prospecto').set_index('id_prospecto')['unidades_atadas']
    foto['unidades_atadas'] = foto['id_prospecto'].map(atadas).fillna(0).astype(int)
    foto.to_parquet(ruta, index=False, compression='snappy')
    print(f"'unidades_atadas' guardado en la foto {ruta} ({int(foto['unidades_atadas'].sum())} unidades atadas).")


def _validar_actualizacion_clientes(resultado):
    """
    Si algun proyecto no se pudo refrescar en el paso 1 (ej. corte de conexion con la API),
    el resto del pipeline seguiria usando el archivo raw VIEJO de ese proyecto sin que nadie
    se entere. Avisamos y preguntamos si de todas formas se quiere continuar.

    Si hay quien conteste, pregunta con input() como antes. Si NO (corrida desatendida --
    background, pipe, Task Scheduler), ya no se queda esperando una respuesta que nunca llega
    ni revienta con EOFError: avisa y continua automaticamente con el archivo raw viejo de los
    proyectos fallidos (comportamiento no destructivo, el mismo que "s" en el modo interactivo).

    NOTA: sys.stdin.isatty() NO es confiable aca para detectar "sin terminal" -- en git-bash/
    MSYS2, un proceso lanzado en background puede seguir reportando isatty()==True aunque no
    haya nadie que vaya a escribir nada, y el input() igual revienta con EOFError al intentar
    leer. Por eso se captura EOFError directamente en vez de confiar en isatty().
    """
    if not resultado:
        return
    fallidos = resultado.get('fallidos', [])
    if not fallidos:
        return

    total = len(fallidos) + len(resultado.get('actualizados', []))
    print(f"\nADVERTENCIA: {len(fallidos)} de {total} proyectos NO se pudieron actualizar "
          f"en el paso 1 (fallo de conexion con la API de Smarthome):")
    for proyecto in fallidos:
        print(f"  - {proyecto}")
    print("Si continuas, el resto del pipeline usara el archivo raw VIEJO de estos proyectos "
          "(si existia una corrida anterior).")

    try:
        respuesta = input("\n¿Deseas continuar de todas formas? (s/n): ").strip().lower()
    except EOFError:
        print("Corrida no interactiva (no hay quien conteste) -- se continua automaticamente "
              "con el archivo raw viejo de los proyectos fallidos.")
        return

    if respuesta not in ('s', 'si', 'sí', 'y', 'yes'):
        print("Pipeline detenido por el usuario.")
        raise SystemExit(1)


def main():
    print("\n=== Paso 1: cargue de clientes (raw) ===")
    resultado_paso1 = paso_1.run()
    _validar_actualizacion_clientes(resultado_paso1)

    print("\n=== Paso 2: cargue de clientes (staging) ===")
    paso_2.run()

    print("\n=== Paso 3: pagos raw (llamada masiva) ===")
    paso_3.run()

    print("\n=== Paso 4: tareas de no escriturados (por cliente) ===")
    paso_4.run()

    print("\n=== Paso 5: consolidado final ===")
    paso_5.run()

    print("\n=== Paso estado de cuentas (raw, desde Drive) ===")
    try:
        paso_estado_cuentas.run()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo actualizar el estado de cuentas desde Drive ({e}). "
              "Se continua con el resto del pipeline igual.")

    print("\n=== Paso unidades atadas (cruce clientes_detallado vs. estado de cuentas) ===")
    try:
        paso_unidades_atadas.run()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo actualizar 'unidades_atadas' ({e}). "
              "La columna puede quedar desactualizada o ausente en clientes_detallado.csv.")

    print("\n=== Paso unidades atadas por fiducia (cruce clientes_detallado vs. tareas/tramites) ===")
    try:
        paso_unidades_atadas_fiducia.run()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo actualizar 'unidades_atadas' por fiducia ({e}). "
              "Se continua con el resto del pipeline igual.")

    print("\n=== Unidades atadas en la foto historica del dia ===")
    try:
        _guardar_atadas_en_historico()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo guardar 'unidades_atadas' en la foto historica ({e}). "
              "El comparativo contra el comite puede mostrar cambios de atadas que no son reales.")

    print("\n=== Paso 6: dashboard HTML ===")
    paso_6.run()

    # Sube el informe a la carpeta del comite del mes en Drive (COMITE DE PROYECTOS / "NNN
    # INFORME ..."). Si falla (sin red, sin permiso), el informe ya quedo generado en local.
    print("\n=== Publicar informe en Drive (COMITE DE PROYECTOS) ===")
    try:
        paso_publicar_drive.run()
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo subir el informe a Drive ({e}). "
              "Se puede subir despues con: python publicar_informe_drive.py")

    print("\nPipeline completo.")


if __name__ == "__main__":
    main()
