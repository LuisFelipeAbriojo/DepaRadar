"""Indicadores del BCRP para el flujo de caja (herramienta del curso: APIs / MCP del BCRP, sesión 04).

Series oficiales (API pública, sin clave):
- PN07848NM  Tasa activa promedio de la banca - MN - Hipotecario (% efectiva anual)
- PN07857NM  Tasa activa promedio de la banca - ME - Hipotecario (% efectiva anual)
- PD04638PD  Tipo de cambio interbancario venta (S/ por US$), diaria

Si la API no responde (o pide esperar), usamos el último valor guardado en
data/processed/bcrp.json para que la app nunca se caiga en pleno demo.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import requests

from deparadar.config import DATA_PROCESSED

API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
SERIES = {
    "tasa_hipotecaria_pen": "PN07848NM",
    "tasa_hipotecaria_usd": "PN07857NM",
    "tipo_cambio": "PD04638PD",
}
CACHE = DATA_PROCESSED / "bcrp.json"


def _ultimo_valor(codigo: str, desde: str, hasta: str, reintentos: int = 3) -> tuple[str, float]:
    """Devuelve (periodo, valor) del último dato disponible de una serie."""
    for intento in range(reintentos):
        try:
            r = requests.get(f"{API}/{codigo}/json/{desde}/{hasta}", timeout=20)
            r.raise_for_status()
            datos = r.json()  # si la API devuelve HTML (exceso de pedidos), esto falla y reintentamos
            validos = [(p["name"], float(p["values"][0])) for p in datos["periods"] if p["values"][0] != "n.d."]
            if validos:
                return validos[-1]
            raise ValueError(f"{codigo} sin datos entre {desde} y {hasta}")
        except (requests.RequestException, ValueError, KeyError):
            if intento == reintentos - 1:
                raise
            time.sleep(2 * (intento + 1))
    raise RuntimeError("inalcanzable")


def descargar() -> dict:
    hoy = date.today()
    mensual = (f"{hoy.year - 1}-{hoy.month}", f"{hoy.year}-{hoy.month}")
    diaria = ((hoy - timedelta(days=30)).isoformat(), hoy.isoformat())
    out = {"fuente": "BCRP", "series": SERIES, "consultado": hoy.isoformat()}
    for clave, codigo in SERIES.items():
        periodo, valor = _ultimo_valor(codigo, *(diaria if clave == "tipo_cambio" else mensual))
        out[clave] = round(valor, 4)
        out[f"periodo_{clave}"] = periodo
    return out


def indicadores(usar_cache_si_falla: bool = True) -> dict:
    """Tasas hipotecarias y tipo de cambio más recientes; actualiza el caché local."""
    try:
        datos = descargar()
        DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
        return datos | {"en_vivo": True}
    except Exception:
        if usar_cache_si_falla and CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8")) | {"en_vivo": False}
        raise


if __name__ == "__main__":
    print(json.dumps(indicadores(), indent=2, ensure_ascii=False))
