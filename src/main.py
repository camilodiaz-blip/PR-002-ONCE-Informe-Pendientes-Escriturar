"""
Orquesta el pipeline completo del informe de pendientes por escriturar:

1 (clientes raw) -> 2 (clientes staging) -> 3 (pagos raw, 1 sola llamada masiva)
-> 4 (tareas de no escriturados, por cliente) -> 5 (consolidado final) -> 6 (dashboard HTML)

Los pasos 3 y 4 ya no se combinan: el paso 3 (3_cargue_pagos_raw.py) trae TODOS los pagos
en una sola llamada a la API (GetPaymentsRecords), no una llamada por cliente, asi que ya
no hay beneficio de rendimiento en compartir el ThreadPoolExecutor con el paso 4 (que si
sigue siendo una llamada por cliente).

Cada paso sigue siendo ejecutable por separado (ej. `python 4_no_escriturados__tareas_raw.py`)
para reprocesar solo uno sin correr todo el pipeline.
"""
import importlib

paso_1 = importlib.import_module("1_cargue_clientes_raw")
paso_2 = importlib.import_module("2_cargue_clientes_staging")
paso_3 = importlib.import_module("3_cargue_pagos_raw")
paso_4 = importlib.import_module("4_no_escriturados__tareas_raw")
paso_5 = importlib.import_module("5_no_escriturados_staging")
paso_6 = importlib.import_module("6_dashboard")


def _validar_actualizacion_clientes(resultado):
    """
    Si algun proyecto no se pudo refrescar en el paso 1 (ej. corte de conexion con la API),
    el resto del pipeline seguiria usando el archivo raw VIEJO de ese proyecto sin que nadie
    se entere. Avisamos y preguntamos si de todas formas se quiere continuar.

    NOTA: usa input(), pensado para corridas manuales/atendidas. Si en algun momento se
    programa main.py para correr desatendido (ej. Task Scheduler sin nadie mirando), este
    prompt se quedaria esperando para siempre -- avisame si llegamos a ese punto para
    cambiarlo por un umbral automatico en vez de una pregunta interactiva.
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

    respuesta = input("\n¿Deseas continuar de todas formas? (s/n): ").strip().lower()
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

    print("\n=== Paso 6: dashboard HTML ===")
    paso_6.run()

    print("\nPipeline completo.")


if __name__ == "__main__":
    main()
