"""Informe PDF del análisis de un departamento (producto "informe suelto", S/ 19).

Usa las fuentes base de PDF (latin-1): sirven para el español, pero no para emojis,
así que el texto se limpia antes de escribirlo.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fpdf import FPDF

AZUL = (42, 120, 214)
VERDE = (12, 163, 12)
ROJO = (208, 59, 59)
GRIS = (82, 81, 78)


def _t(texto) -> str:
    """Texto seguro para las fuentes base (latin-1): quita emojis y símbolos fuera del rango."""
    return str(texto).replace("−", "-").replace("≈", "~").encode("latin-1", "ignore").decode("latin-1").strip()


def _usd(x: float) -> str:
    return f"US$ {x:,.0f}"


def _pct(x: float | None) -> str:
    return "-" if x is None or pd.isna(x) else f"{x * 100:.1f} %"


def generar(aviso: pd.Series, res: dict, desglose: list[tuple[str, float]], tabla_flujo: pd.DataFrame,
            p_max: float | None, fuente_datos: str) -> bytes:
    s = res["supuestos"]
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Encabezado
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*AZUL)
    pdf.cell(0, 10, "DepaRadar", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 5, _t(f"Informe de inversión · generado el {date.today().strftime('%d/%m/%Y')} · {fuente_datos}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Aviso
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 6, _t(aviso["titulo"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _t(f"{aviso['distrito']} · {aviso['area_m2']:.0f} m² · {aviso['dormitorios']:.0f} dorm. · "
                            f"{aviso['banos']:.0f} baños · {aviso['cocheras']:.0f} cochera(s) · {aviso['estado']}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*AZUL)
    pdf.cell(0, 5, _t(aviso["url"]), link=aviso["url"], new_x="LMARGIN", new_y="NEXT")
    senales = [_t(e) for e in str(aviso.get("etiquetas") or "").split("·") if _t(e)]
    if senales:
        pdf.set_text_color(*GRIS)
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 5, _t("Señales del aviso (leídas con Gemini): " + "; ".join(senales)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Veredicto
    cuadra = res["van"] > 0
    pdf.set_fill_color(*(VERDE if cuadra else ROJO))
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    veredicto = f"CUADRA: rinde {_pct(res['tir'])} al año" if cuadra else f"NO CUADRA: rinde {_pct(res['tir'])} al año"
    pdf.cell(0, 11, _t(f"  {veredicto} (costo de oportunidad {s['tasa_descuento'] * 100:.1f} %)"), fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    if p_max:
        pdf.ln(1)
        pdf.multi_cell(0, 5, _t(f"Precio máximo para que cuadre: {_usd(p_max)} "
                                f"({(p_max / aviso['precio_usd'] - 1) * 100:+.0f} % frente al precio pedido de "
                                f"{_usd(aviso['precio_usd'])})."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    def tabla(titulo: str, filas: list[tuple[str, str]], ancho_izq: float = 110):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _t(titulo), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for i, (k, v) in enumerate(filas):
            pdf.set_fill_color(*((240, 239, 236) if i % 2 == 0 else (255, 255, 255)))
            pdf.cell(ancho_izq, 6, _t(k), fill=True)
            pdf.cell(0, 6, _t(v), fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    tabla("Indicadores", [
        ("Precio evaluado", _usd(s["precio"])),
        ("Precio justo estimado (modelo)", f"{_usd(aviso['precio_justo_usd'])} ({aviso['descuento_pct']:.0f} % bajo mercado)"),
        ("Pones al inicio (inicial + notaría + alcabala)", _usd(res["inversion_inicial"])),
        ("Cuota mensual del crédito", _usd(res["cuota_mensual"])),
        ("Flujo mensual (año 1)", _usd(res["flujo_mensual_anio1"])),
        ("TIR", _pct(res["tir"])),
        (f"VAN al {s['tasa_descuento'] * 100:.1f} %", _usd(res["van"])),
        ("Cash-on-cash (año 1)", _pct(res["cash_on_cash"])),
        (f"Venta neta al año {s['horizonte_anios']}", _usd(res["neto_venta"])),
    ])
    tabla("A dónde se va tu alquiler (por mes, año 1)",
          [(c, _usd(v)) for c, v in desglose] + [("Flujo mensual", _usd(sum(v for _, v in desglose)))])
    tabla("Supuestos", [
        ("Crédito", f"{s['tasa_anual'] * 100:.2f} % TEA · {s['plazo_anios']} años · inicial {s['cuota_inicial_pct'] * 100:.0f} %"),
        ("Alquiler esperado", f"{_usd(s['alquiler_mensual'])} al mes (ajuste real vs. publicado {s['ajuste_alquiler'] * 100:.0f} %)"),
        ("Vacancia", f"{s['vacancia_meses_anio']:.1f} meses al año"),
        ("Apreciación / crecimiento del alquiler", f"{s['apreciacion_anual'] * 100:.1f} % / {s['crecimiento_alquiler'] * 100:.1f} % anual"),
        ("Horizonte", f"{s['horizonte_anios']} años"),
    ])

    # Flujo anual
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Flujo de caja anual (US$)", new_x="LMARGIN", new_y="NEXT")
    cols = [("Año", "anio", 15), ("Alquiler neto", "noi", 40), ("Cuotas", "servicio_deuda", 35),
            ("Flujo neto", "flujo_neto", 35), ("Venta", "venta", 30), ("Total", "flujo_total", 25)]
    pdf.set_font("Helvetica", "B", 9)
    for nombre, _, w in cols:
        pdf.cell(w, 6, nombre, border="B", align="R")
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for _, f in tabla_flujo.iterrows():
        for _, col, w in cols:
            v = f[col]
            pdf.cell(w, 5, f"{int(v)}" if col == "anio" else f"{v:,.0f}", align="R")
        pdf.ln()
    pdf.ln(4)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*GRIS)
    pdf.multi_cell(0, 4, _t("DepaRadar es una herramienta de análisis, no una recomendación de inversión. El precio justo "
                            "y el alquiler son estimaciones de modelos entrenados con avisos (error mediano ~10 %). "
                            "Verifica siempre el inmueble, la partida registral y los números con un profesional."))
    return bytes(pdf.output())
