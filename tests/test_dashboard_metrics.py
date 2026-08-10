import importlib.util
from pathlib import Path

import pandas as pd


module_path = Path(__file__).resolve().parents[1] / "src" / "6_dashboard.py"
spec = importlib.util.spec_from_file_location("dashboard", module_path)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def test_credito_sin_radicar_conta_todos_los_creditos_no_radicados():
    df = pd.DataFrame(
        [
            {"escriturado": 0, "credito": 1, "credito_aprobado": 0, "credito_radicado": 0},
            {"escriturado": 0, "credito": 1, "credito_aprobado": 1, "credito_radicado": 0},
            {"escriturado": 0, "credito": 1, "credito_aprobado": 1, "credito_radicado": 1},
            {"escriturado": 0, "credito": 0, "credito_aprobado": 0, "credito_radicado": 0},
        ]
    )

    metricas = dashboard._calcular_metricas(df, "Todos")

    assert metricas["credito"][4] == 2
