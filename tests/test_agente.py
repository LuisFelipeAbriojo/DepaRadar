"""Tests de las herramientas del agente (sin llamar a Gemini)."""

import pandas as pd
import pytest

from deparadar.agente import Herramientas, Uso
from deparadar.finanzas import Supuestos


def _df():
    filas = []
    for i, (dist, precio, cuadra, oport) in enumerate([
        ("Miraflores", 200_000, True, True),
        ("Miraflores", 300_000, False, True),
        ("Barranco", 120_000, True, True),
        ("Barranco", 110_000, True, False),
    ]):
        filas.append(dict(
            id=i, distrito=dist, precio_usd=precio, area_m2=80, dormitorios=2, descuento_pct=20.0,
            rentabilidad_bruta_pct=6.0, tir=0.12 - i / 100, flujo_mensual=-50.0, cuadra=cuadra, oportunidad=oport,
            revisar_aviso=False, etiquetas="", url=f"https://x/{i}", estado="Buen estado",
            precio_justo_usd=precio * 1.25, alquiler_estimado_usd=precio * 0.005, usd_m2=precio / 80,
        ))
    return pd.DataFrame(filas)


@pytest.fixture
def h():
    return Herramientas(_df(), Supuestos(precio=1, alquiler_mensual=1), {"tasa_hipotecaria_usd": 6.3, "series": {}})


def test_buscar_filtra_y_ordena(h):
    r = h.buscar_oportunidades(distritos=["miraflores"])
    assert r["total_encontrados"] == 1 and r["avisos"][0]["id"] == 0
    r = h.buscar_oportunidades(solo_bajo_mercado=False, presupuesto_max_usd=150_000)
    assert [a["id"] for a in r["avisos"]] == [2, 3]  # ordenado por TIR


def test_plan_gratis_limita_distritos():
    h = Herramientas(_df(), Supuestos(precio=1, alquiler_mensual=1), {}, distritos_permitidos=["Barranco"])
    r = h.buscar_oportunidades(solo_que_cuadran=False)
    assert {a["distrito"] for a in r["avisos"]} == {"Barranco"}


def test_evaluar_aviso_y_error(h):
    r = h.evaluar_aviso(2)
    assert r["id"] == 2 and r["precio_evaluado_usd"] == 120_000 and "precio_maximo_para_que_cuadre_usd" in r
    assert "error" in h.evaluar_aviso(999)


def test_resumen_y_tasas(h):
    assert len(h.resumen_mercado()["por_distrito"]) == 2
    assert "error" in h.resumen_mercado("Ate")
    assert h.tasas_bcrp() == {"tasa_hipotecaria_usd": 6.3}


def test_costo_por_tokens():
    assert Uso(tokens_entrada=1_000_000, tokens_salida=1_000_000).costo_usd == pytest.approx(2.80)
