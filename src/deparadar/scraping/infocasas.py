"""Scraper de avisos de departamentos en InfoCasas Perú.

InfoCasas es una app Next.js: cada página de resultados trae los avisos ya
estructurados dentro del <script id="__NEXT_DATA__">. Leemos ese JSON en vez de
parsear el HTML visual, así el scraper es más simple y robusto.

Buenas prácticas:
- Solo páginas de búsqueda que el robots.txt permite (/venta/... y /alquiler/...).
- Pausa entre pedidos y un tope de páginas por distrito.
- No guardamos datos personales: ni nombres ni teléfonos de los anunciantes,
  solo si el aviso es de una inmobiliaria o de un particular.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import date

import requests

BASE_URL = "https://www.infocasas.com.pe"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"[\d.,]+")


def url_busqueda(operacion: str, distrito_slug: str, pagina: int = 1) -> str:
    url = f"{BASE_URL}/{operacion}/departamentos/lima/{distrito_slug}"
    return url if pagina == 1 else f"{url}/pagina{pagina}"


def extraer_next_data(page_html: str) -> dict:
    m = _NEXT_DATA_RE.search(page_html)
    if not m:
        raise ValueError("La página no trae __NEXT_DATA__ (¿bloqueo o cambio de diseño?)")
    return json.loads(m.group(1))


def _a_numero(valor) -> float | None:
    """'95 m2' -> 95.0, 'S/ 300' -> 300.0, '' -> None."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    m = _NUM_RE.search(str(valor))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _texto_plano(desc: str | None) -> str:
    if not desc:
        return ""
    texto = _TAG_RE.sub(" ", desc)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def parsear_aviso(item: dict, distrito: str) -> dict:
    """Convierte un aviso crudo de InfoCasas en una fila plana."""
    ficha = {t.get("field"): t.get("value") for t in item.get("technicalSheet") or []}
    precio = item.get("price") or {}
    moneda = (precio.get("currency") or {}).get("name")
    owner = item.get("owner") or {}
    return {
        "id": item.get("id"),
        "fuente": "infocasas",
        "operacion": ((item.get("operation_type") or {}).get("name") or "").lower(),
        "distrito": distrito,
        "titulo": item.get("title"),
        "direccion": item.get("address") if item.get("showAddress", True) else None,
        "precio": precio.get("amount"),
        "moneda": "USD" if moneda == "U$S" else "PEN" if moneda == "S/" else moneda,
        "precio_usd": item.get("price_amount_usd"),
        "mantenimiento_pen": _a_numero(ficha.get("commonExpenses")),
        "m2": item.get("m2"),
        "m2_construido": item.get("m2Built"),
        "m2_terraza": item.get("m2Terrace"),
        "dormitorios": _a_numero(ficha.get("bedrooms")),
        "banos": _a_numero(ficha.get("bathrooms")),
        "cocheras": _a_numero(ficha.get("garage")),
        "piso": _a_numero(ficha.get("floor")),
        "estado": ficha.get("construction_state_name") or None,
        "anio_construccion": _a_numero(ficha.get("constructionYear")),
        "distancia_mar": ficha.get("sea_distance_name") or None,
        "disposicion": ficha.get("disposition_name") or None,
        "amenidades": "|".join(f.get("name", "") for f in item.get("facilities") or []),
        "tipo_anunciante": owner.get("type"),
        "latitud": item.get("latitude"),
        "longitud": item.get("longitude"),
        "descripcion": _texto_plano(item.get("description")),
        "url": BASE_URL + item["link"] if item.get("link") else None,
        "publicado": item.get("created_at"),
        "actualizado": item.get("updated_at"),
        "fecha_scraping": date.today().isoformat(),
    }


def parsear_pagina(page_html: str, distrito: str) -> tuple[list[dict], dict]:
    """Devuelve (avisos, info_de_paginación) de una página de resultados."""
    data = extraer_next_data(page_html)
    busqueda = data["props"]["pageProps"]["fetchResult"]["searchFast"]
    avisos = [
        parsear_aviso(it, distrito)
        for it in busqueda.get("data") or []
        if (it.get("property_type") or {}).get("name") == "Departamento"
    ]
    return avisos, busqueda.get("paginatorInfo") or {}


def scrapear(
    operacion: str,
    distrito_slug: str,
    distrito: str,
    max_paginas: int = 5,
    pausa: float = 2.0,
    session: requests.Session | None = None,
) -> list[dict]:
    """Descarga hasta `max_paginas` páginas de resultados de un distrito."""
    s = session or requests.Session()
    avisos: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        resp = s.get(url_busqueda(operacion, distrito_slug, pagina), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        nuevos, info = parsear_pagina(resp.text, distrito)
        avisos.extend(nuevos)
        if not info.get("hasMorePages"):
            break
        time.sleep(pausa)
    return avisos
