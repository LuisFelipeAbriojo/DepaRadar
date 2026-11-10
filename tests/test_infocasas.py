import json

import pytest

from deparadar.scraping.infocasas import (
    _a_numero,
    parsear_pagina,
    url_busqueda,
)

AVISO = {
    "id": 1,
    "title": "Se vende departamento",
    "address": "Av. Ejemplo 123, Miraflores",
    "showAddress": True,
    "price": {"amount": 950000, "currency": {"name": "S/", "rate": 3.45}},
    "price_amount_usd": 275362,
    "m2": 90,
    "m2Built": 85,
    "m2Terrace": 5,
    "technicalSheet": [
        {"field": "bedrooms", "value": "3"},
        {"field": "bathrooms", "value": "2"},
        {"field": "garage", "value": "1"},
        {"field": "commonExpenses", "value": "S/ 1,250"},
        {"field": "construction_state_name", "value": "Buen estado"},
        {"field": "constructionYear", "value": ""},
    ],
    "facilities": [{"name": "Cochera"}, {"name": "Ascensor"}],
    "owner": {"type": "particular", "name": "No debe guardarse", "whatsapp_phone": "999999999"},
    "property_type": {"name": "Departamento"},
    "operation_type": {"name": "Venta"},
    "description": "<p>Lindo depa &amp; vista</p>",
    "link": "/depa/1",
    "latitude": -12.12,
    "longitude": -77.03,
}
CASA = {**AVISO, "id": 2, "property_type": {"name": "Casa"}}


def _html(items, has_more=False):
    data = {
        "props": {
            "pageProps": {
                "fetchResult": {
                    "searchFast": {"data": items, "paginatorInfo": {"hasMorePages": has_more}}
                }
            }
        }
    }
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_parsea_campos_principales_y_filtra_no_departamentos():
    avisos, info = parsear_pagina(_html([AVISO, CASA]), "Miraflores")
    assert len(avisos) == 1 and info == {"hasMorePages": False}
    a = avisos[0]
    assert a["moneda"] == "PEN" and a["precio"] == 950000 and a["precio_usd"] == 275362
    assert a["dormitorios"] == 3 and a["cocheras"] == 1 and a["mantenimiento_pen"] == 1250
    assert a["anio_construccion"] is None
    assert a["descripcion"] == "Lindo depa & vista"
    assert a["url"] == "https://www.infocasas.com.pe/depa/1"
    assert a["operacion"] == "venta" and a["distrito"] == "Miraflores"


def test_no_guarda_datos_personales_del_anunciante():
    a = parsear_pagina(_html([AVISO]), "Miraflores")[0][0]
    valores = json.dumps(a, ensure_ascii=False)
    assert "999999999" not in valores and "No debe guardarse" not in valores
    assert a["tipo_anunciante"] == "particular"


def test_pagina_bloqueada_lanza_error():
    with pytest.raises(ValueError):
        parsear_pagina("<html>Just a moment...</html>", "Miraflores")


@pytest.mark.parametrize("entrada,esperado", [("95 m2", 95.0), ("S/ 1,250", 1250.0), ("", None), (None, None), (3, 3.0)])
def test_a_numero(entrada, esperado):
    assert _a_numero(entrada) == esperado


def test_url_busqueda():
    assert url_busqueda("venta", "barranco") == "https://www.infocasas.com.pe/venta/departamentos/lima/barranco"
    assert url_busqueda("alquiler", "lince", 3).endswith("/alquiler/departamentos/lima/lince/pagina3")
