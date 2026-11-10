"""Limpieza de los avisos crudos del scraper.

Reglas (decididas mirando la primera corrida del 10-nov-2026):
- Área: usamos m² construidos si existen; si no, m² totales. Rango 20–600 m².
- Precios por m² fuera de un rango razonable de Lima Moderna se descartan
  (suelen ser errores de tipeo: precio en miles, m² del edificio, etc.).
- Coordenadas fuera de Lima se vuelven NaN (el aviso se queda, pero no va al mapa).
- Casi-duplicados: el mismo depa publicado por dos inmobiliarias.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Datos de contacto que algunos anunciantes ponen en el texto: no los publicamos
_CONTACTO_RE = re.compile(
    r"(?:\+?51[\s.-]*)?\b9\d{2}[\s.*-]?\d{3}[\s.*-]?\d{3}\b"   # celulares peruanos (9 dígitos)
    r"|\(?\b01\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"                  # fijos de Lima
    r"|[\w.+-]+@[\w-]+\.[\w.]+"                              # correos
    r"|(?:https?://)?(?:wa\.me|api\.whatsapp\.com)/\S+",       # enlaces de WhatsApp
    re.I,
)


def anonimizar(texto) -> str:
    """Reemplaza teléfonos, correos y enlaces de WhatsApp por [contacto]."""
    if not isinstance(texto, str):
        return ""
    return _CONTACTO_RE.sub("[contacto]", texto)

# Rango de área útil (m²)
M2_MIN, M2_MAX = 20, 600
# Rangos de precio por m² en USD (venta) y USD/mes (alquiler)
RANGO_USD_M2 = {"venta": (700, 7000), "alquiler": (3, 40)}
# Caja aproximada de Lima Metropolitana
LAT_LIMA, LON_LIMA = (-12.25, -11.95), (-77.15, -76.90)

# Amenidades que convertimos en columnas 0/1 (nombre en InfoCasas -> columna)
AMENIDADES = {
    "ascensor": ["Ascensor"],
    "piscina": ["Piscina"],
    "gimnasio": ["GYM"],
    "terraza": ["Balcón / Terraza", "Balcón", "Jardin / Patio", "Patio"],
    "amoblado": ["Amueblada"],
    "dorm_servicio": ["Dormitorio de servicio"],
    "areas_comunes": ["Parrillero / Barbacoa", "Barbacoa", "Playroom", "Salón de uso común"],
    "acepta_mascotas": ["Se aceptan mascotas"],
}

ESTADOS_PREVENTA = {"En construcción", "En Pozo"}


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates(subset=["id"]).copy()
    for col in ("titulo", "descripcion"):
        if col in df:
            df[col] = df[col].map(anonimizar)

    df["area_m2"] = df["m2_construido"].where(df["m2_construido"] > 0, df["m2"])
    df = df[df["area_m2"].between(M2_MIN, M2_MAX)]
    df = df[df["precio_usd"] > 0]
    df["usd_m2"] = df["precio_usd"] / df["area_m2"]

    en_rango = pd.Series(False, index=df.index)
    for op, (lo, hi) in RANGO_USD_M2.items():
        en_rango |= (df["operacion"] == op) & df["usd_m2"].between(lo, hi)
    df = df[en_rango]

    # Mismo depa publicado varias veces: igual operación, distrito, precio, área y dormitorios
    df = df.drop_duplicates(subset=["operacion", "distrito", "precio_usd", "area_m2", "dormitorios"])

    fuera = ~df["latitud"].between(*LAT_LIMA) | ~df["longitud"].between(*LON_LIMA)
    df.loc[fuera, ["latitud", "longitud"]] = np.nan

    df["cocheras"] = df["cocheras"].fillna(0)
    df["preventa"] = df["estado"].isin(ESTADOS_PREVENTA).astype(int)
    df["estado"] = df["estado"].fillna("Sin dato")
    df["mantenimiento_pen"] = df["mantenimiento_pen"].where(df["mantenimiento_pen"].between(50, 5000))

    lista = df["amenidades"].fillna("").str.split("|")
    for col, nombres in AMENIDADES.items():
        df[col] = lista.apply(lambda xs, n=set(nombres): int(bool(n.intersection(xs))))

    return df.reset_index(drop=True)
