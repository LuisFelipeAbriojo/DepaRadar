import pandas as pd

from deparadar.finanzas import Supuestos, desglose_mensual, precio_maximo, proyectar
from deparadar.informe import _t, generar


def test_genera_un_pdf_valido():
    aviso = pd.Series(dict(
        titulo="Lindo dúplex 🔥 en Miraflores", distrito="Miraflores", area_m2=90, dormitorios=2, banos=2,
        cocheras=1, estado="Buen estado", url="https://example.com/1", precio_usd=180_000,
        precio_justo_usd=220_000, descuento_pct=18.2,
    ))
    s = Supuestos(precio=180_000, alquiler_mensual=900)
    tabla, res = proyectar(s)
    pdf = generar(aviso, res, desglose_mensual(s), tabla, precio_maximo(s), "InfoCasas 10-nov-2026")
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_texto_sin_emojis():
    assert _t("Urge vender 🔥 · 90 m²") == "Urge vender  · 90 m²"
