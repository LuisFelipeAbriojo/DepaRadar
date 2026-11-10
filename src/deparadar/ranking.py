"""Ranking de oportunidades: valoración + flujo de caja + etiquetas de Gemini."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from deparadar.finanzas import Supuestos, proyectar


def _bool(v) -> bool:
    return str(v).strip().lower() in {"true", "1", "1.0"}


def etiquetas(fila: pd.Series) -> list[str]:
    """Etiquetas cortas que explican un aviso (vienen de la ficha y de Gemini)."""
    out = []
    if _bool(fila.get("urgencia_venta")):
        out.append("🔥 Urge vender")
    if fila.get("tipo_unidad") in ("duplex", "triplex", "penthouse"):
        out.append(f"⚠️ {str(fila['tipo_unidad']).capitalize()}: revisar área")
    if _bool(fila.get("requiere_remodelacion")):
        out.append("🔨 Por remodelar")
    if fila.get("vista") == "mar":
        out.append("🌊 Vista al mar")
    elif fila.get("vista") == "parque":
        out.append("🌳 Vista a parque")
    if fila.get("preventa") == 1:
        out.append("🏗️ Preventa")
    if _bool(fila.get("revisar_aviso")):
        out.append("❓ Descuento sospechoso")
    return out


def supuestos_para(fila: pd.Series, base: Supuestos) -> Supuestos:
    """Supuestos del flujo para un aviso concreto (en USD)."""
    return replace(
        base,
        precio=float(fila["precio_usd"]),
        alquiler_mensual=float(fila["alquiler_estimado_usd"]),
        primera_venta=fila.get("estado") in ("A estrenar", "En construcción", "En Pozo"),
    )


def rankear(venta: pd.DataFrame, base: Supuestos) -> pd.DataFrame:
    """Agrega TIR, VAN, flujo mensual y si 'cuadra' a cada aviso en venta."""
    filas = []
    for _, f in venta.iterrows():
        _, ind = proyectar(supuestos_para(f, base))
        filas.append({
            "tir": ind["tir"],
            "van": ind["van"],
            "flujo_mensual": ind["flujo_mensual_anio1"],
            "cuota_mensual": ind["cuota_mensual"],
            "inversion_inicial": ind["inversion_inicial"],
        })
    out = pd.concat([venta.reset_index(drop=True), pd.DataFrame(filas)], axis=1)
    out["cuadra"] = out["van"] > 0
    out["etiquetas"] = out.apply(lambda f: " · ".join(etiquetas(f)), axis=1)
    return out
