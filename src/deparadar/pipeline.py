"""Del CSV crudo más reciente a los datos que usa la app.

Uso:
    uv run python -m deparadar.pipeline
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from deparadar.config import DATA_PROCESSED, DATA_RAW
from deparadar.limpieza import limpiar
from deparadar.modelo import valorizar

log = logging.getLogger("deparadar.pipeline")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    crudos = sorted(DATA_RAW.glob("infocasas_*.csv"))
    if not crudos:
        raise SystemExit("No hay datos crudos: corre primero `python -m deparadar.scraping`")
    origen = crudos[-1]
    df = pd.read_csv(origen)
    limpio = limpiar(df)
    log.info("%s: %d avisos crudos -> %d limpios", origen.name, len(df), len(limpio))

    venta = limpio[limpio["operacion"] == "venta"]
    alquiler = limpio[limpio["operacion"] == "alquiler"]
    venta_val, metricas = valorizar(venta, alquiler)
    metricas["fuente"] = origen.name
    metricas["fecha_datos"] = str(df["fecha_scraping"].max())

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    venta_val.to_csv(DATA_PROCESSED / "venta.csv", index=False, encoding="utf-8")
    alquiler.to_csv(DATA_PROCESSED / "alquiler.csv", index=False, encoding="utf-8")
    (DATA_PROCESSED / "metricas.json").write_text(json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Métricas: %s", metricas)


if __name__ == "__main__":
    main()
