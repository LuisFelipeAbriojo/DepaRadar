"""Actualización diaria de los datos: scraping -> Gemini -> modelos -> BCRP.

La corre GitHub Actions todos los días (.github/workflows/actualizar-datos.yml)
y también se puede correr a mano:

    uv run python -m deparadar.actualizar
    uv run python -m deparadar.actualizar --max-paginas 1   # prueba rápida

Control de seguridad: si el scraping trae muchos menos avisos que la última vez
(por ejemplo, porque el portal bloqueó al servidor), NO se tocan los datos de la
app y el proceso termina con error para que se note en GitHub.
"""

from __future__ import annotations

import argparse
import json
import logging
import os

import pandas as pd
from dotenv import load_dotenv

from deparadar import bcrp, pipeline
from deparadar.config import DATA_PROCESSED, ROOT
from deparadar.limpieza import limpiar
from deparadar.scraping.__main__ import main as scrapear_todo

log = logging.getLogger("deparadar.actualizar")

METRICAS = DATA_PROCESSED / "metricas.json"
FRACCION_MINIMA = 0.6   # el scraping nuevo debe traer al menos 60 % de los avisos de la última vez
MINIMO_ABSOLUTO = 100   # y nunca menos de 100 por operación


def validar(nuevo: dict[str, int], previo: dict[str, int], fraccion: float = FRACCION_MINIMA) -> list[str]:
    """Problemas que impiden usar el scraping nuevo (lista vacía = todo bien)."""
    problemas = []
    for op, n in nuevo.items():
        antes = previo.get(op, 0)
        if n < MINIMO_ABSOLUTO:
            problemas.append(f"{op}: solo {n} avisos limpios (mínimo {MINIMO_ABSOLUTO})")
        elif antes and n < fraccion * antes:
            problemas.append(f"{op}: {n} avisos limpios vs. {antes} la última vez (menos del {fraccion:.0%})")
    return problemas


def _resumen(texto: str) -> None:
    """Escribe en el resumen del job de GitHub Actions (si estamos ahí)."""
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Actualiza avisos, atributos de Gemini, modelos y tasas del BCRP")
    p.add_argument("--max-paginas", type=int, default=5)
    p.add_argument("--pausa", type=float, default=2.0)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    load_dotenv(ROOT / ".env")

    previo_m = json.loads(METRICAS.read_text(encoding="utf-8")) if METRICAS.exists() else {}
    previo = {"venta": previo_m.get("avisos_venta", 0), "alquiler": previo_m.get("avisos_alquiler", 0)}

    # 1) Scraping
    crudo = scrapear_todo(["--max-paginas", str(args.max_paginas), "--pausa", str(args.pausa)])
    limpio = limpiar(pd.read_csv(crudo))
    nuevo = {op: int((limpio["operacion"] == op).sum()) for op in ("venta", "alquiler")}
    log.info("Avisos limpios: %s (antes: %s)", nuevo, previo)

    # 2) Control de seguridad: no pisar datos buenos con un scraping fallido
    problemas = validar(nuevo, previo)
    if problemas:
        crudo.rename(crudo.with_suffix(".rechazado"))  # que el pipeline no lo use después
        msg = "❌ Scraping descartado, la app sigue con los datos anteriores:\n- " + "\n- ".join(problemas)
        log.error(msg)
        _resumen(msg)
        raise SystemExit(1)

    # 3) Gemini lee solo los avisos nuevos (los demás están en caché)
    if os.environ.get("GEMINI_API_KEY"):
        from deparadar.llm import CACHE, extraer_pendientes

        antes = len(pd.read_csv(CACHE)) if CACHE.exists() else 0
        extraer_pendientes(limpio)
        leidos = (len(pd.read_csv(CACHE)) if CACHE.exists() else 0) - antes
        log.info("Gemini leyó %d avisos nuevos", leidos)
    else:
        leidos = 0
        log.warning("Sin GEMINI_API_KEY: los avisos nuevos van sin atributos de Gemini")

    # 4) Limpieza + modelos -> data/processed
    pipeline.main()

    # 5) Tasas del BCRP (refresca la caché que usa la app si la API falla)
    try:
        bcrp.indicadores()
    except Exception as e:  # noqa: BLE001 - la app ya tiene caché
        log.warning("BCRP no respondió: %s", e)

    m = json.loads(METRICAS.read_text(encoding="utf-8"))
    _resumen(f"✅ Datos del {m['fecha_datos']}: {m['avisos_venta']} avisos de venta, {m['avisos_alquiler']} de "
             f"alquiler, {m['oportunidades']} oportunidades · Gemini leyó {leidos} avisos nuevos · "
             f"error del modelo {m['error_mediano_venta_pct']} %")


if __name__ == "__main__":
    main()
