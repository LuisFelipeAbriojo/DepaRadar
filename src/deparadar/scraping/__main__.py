"""Corre el scraper para Lima Moderna y guarda un CSV en data/raw/.

Uso:
    uv run python -m deparadar.scraping --max-paginas 5
    uv run python -m deparadar.scraping --distritos miraflores barranco --operaciones venta
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import pandas as pd
import requests

from deparadar.config import DATA_RAW, DISTRITOS, OPERACIONES
from deparadar.scraping.infocasas import scrapear

log = logging.getLogger("deparadar.scraping")


def main() -> None:
    p = argparse.ArgumentParser(description="Scraper de avisos de InfoCasas (Lima Moderna)")
    p.add_argument("--distritos", nargs="+", default=list(DISTRITOS), choices=list(DISTRITOS))
    p.add_argument("--operaciones", nargs="+", default=list(OPERACIONES), choices=OPERACIONES)
    p.add_argument("--max-paginas", type=int, default=5, help="páginas por distrito y operación (21 avisos c/u)")
    p.add_argument("--pausa", type=float, default=2.0, help="segundos entre pedidos")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    session = requests.Session()
    filas: list[dict] = []
    for op in args.operaciones:
        for slug in args.distritos:
            try:
                avisos = scrapear(op, slug, DISTRITOS[slug], args.max_paginas, args.pausa, session)
            except Exception as e:  # un distrito que falla no detiene el resto
                log.warning("%s / %s falló: %s", op, slug, e)
                continue
            log.info("%-8s %-18s %4d avisos", op, slug, len(avisos))
            filas.extend(avisos)

    df = pd.DataFrame(filas).drop_duplicates(subset=["id"])
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    salida = DATA_RAW / f"infocasas_{date.today().isoformat()}.csv"
    df.to_csv(salida, index=False, encoding="utf-8")
    log.info("Guardado %s (%d avisos únicos)", salida, len(df))


if __name__ == "__main__":
    main()
