import numpy as np
import pandas as pd

from deparadar.limpieza import limpiar
from deparadar.modelo import valorizar


def _aviso(i, op="venta", distrito="Miraflores", precio=200_000, m2=80, **kw):
    base = dict(
        id=i, operacion=op, distrito=distrito, precio_usd=precio, m2=m2, m2_construido=m2,
        dormitorios=2, banos=2, cocheras=1, piso=3, estado="Buen estado", mantenimiento_pen=400,
        amenidades="Ascensor|GYM", latitud=-12.12, longitud=-77.03,
    )
    return {**base, **kw}


def test_limpiar_descarta_atipicos_y_duplicados():
    df = pd.DataFrame([
        _aviso(1),
        _aviso(2, m2=0),                       # sin área
        _aviso(3, precio=900),                 # precio absurdo
        _aviso(1),                             # id repetido
        _aviso(4),                             # mismo depa con otro id
        _aviso(5, precio=250_000, latitud=0),  # coordenada fuera de Lima
        _aviso(6, op="alquiler", precio=900, estado="En construcción"),
    ])
    out = limpiar(df)
    assert set(out["id"]) == {1, 5, 6}
    assert out.loc[out.id == 5, "latitud"].isna().all()
    assert out.loc[out.id == 1, ["ascensor", "gimnasio", "piscina"]].values.tolist() == [[1, 1, 0]]
    assert out.loc[out.id == 6, "preventa"].item() == 1


def test_valorizar_detecta_un_depa_bajo_precio():
    rng = np.random.default_rng(0)
    filas = []
    for i in range(200):
        m2 = int(rng.integers(50, 150))
        filas.append(_aviso(i, precio=2500 * m2 * rng.uniform(0.95, 1.05), m2=m2, latitud=-12.12 + rng.normal(0, .005)))
        filas.append(_aviso(1000 + i, op="alquiler", precio=11 * m2 * rng.uniform(0.95, 1.05), m2=m2))
    filas.append(_aviso(9999, precio=2500 * 100 * 0.75, m2=100))  # 25 % bajo mercado
    limpio = limpiar(pd.DataFrame(filas))
    venta, met = valorizar(limpio[limpio.operacion == "venta"], limpio[limpio.operacion == "alquiler"])

    ganga = venta.set_index("id").loc[9999]
    assert ganga["oportunidad"] and 15 < ganga["descuento_pct"] < 40
    # 11 USD/m2/mes * 12 / 1875 USD/m2 ≈ 7 % bruto
    assert 5 < ganga["rentabilidad_bruta_pct"] < 9
    assert met["error_mediano_venta_pct"] < 5
