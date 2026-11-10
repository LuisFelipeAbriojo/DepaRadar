import pytest

from deparadar.finanzas import Supuestos, alcabala, cuota_mensual, proyectar, saldo_deuda, tir, van


def test_cuota_metodo_frances():
    # 100 000 al 12 % TEA a 1 año: cuota ≈ 8 856.5 (TEM 0.9489 %)
    assert cuota_mensual(100_000, 0.12, 1) == pytest.approx(8856.5, abs=1)
    assert saldo_deuda(100_000, 0.12, 1, 12) == pytest.approx(0, abs=1e-6)
    assert saldo_deuda(100_000, 0.12, 1, 0) == pytest.approx(100_000)


def test_tir_y_van():
    flujos = [-1000, 100, 100, 1100]
    assert tir(flujos) == pytest.approx(0.10, abs=1e-6)
    assert van(0.10, flujos) == pytest.approx(0, abs=1e-6)
    assert tir([100, 100]) is None


def test_alcabala_respeta_10_uit_y_primera_venta():
    s = Supuestos(precio=100_000, alquiler_mensual=500, tipo_cambio=3.5)
    # 350 000 soles - 55 000 = 295 000 * 3 % = 8 850 soles = 2 528.6 USD
    assert alcabala(s) == pytest.approx(2528.57, abs=0.1)
    s.primera_venta = True
    assert alcabala(s) == 0


def test_proyeccion_coherente():
    s = Supuestos(precio=150_000, alquiler_mensual=800)
    tabla, ind = proyectar(s)
    assert len(tabla) == s.horizonte_anios + 1
    assert ind["prestamo"] == pytest.approx(120_000)
    assert ind["rentabilidad_bruta"] == pytest.approx(0.064)
    assert tabla.iloc[0]["flujo_total"] == pytest.approx(-ind["inversion_inicial"])
    assert ind["tir"] is not None and -0.5 < ind["tir"] < 0.5
    # más alquiler -> mejor TIR
    _, mejor = proyectar(Supuestos(precio=150_000, alquiler_mensual=1000))
    assert mejor["tir"] > ind["tir"]


def test_precio_maximo_deja_van_cero():
    from deparadar.finanzas import precio_maximo

    s = Supuestos(precio=183_500, alquiler_mensual=830)
    p = precio_maximo(s)
    assert p is not None and p < s.precio  # el depa mediano no cuadra: hay que negociar
    s.precio = p
    assert abs(proyectar(s)[1]["van"]) < 500
