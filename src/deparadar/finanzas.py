"""Flujo de caja de comprar un departamento para alquilarlo, con crédito hipotecario.

Todo se calcula en la moneda del crédito (USD o PEN). Las cuentas las hace
Python, no el LLM: cada cifra se puede repetir y auditar.

Supuestos peruanos (editables en la app):
- Alcabala: 3 % sobre el exceso de 10 UIT. No aplica a la primera venta de un
  inmueble nuevo (estreno), que ya lleva IGV en el precio.
- Impuesto a la renta del alquiler (1.ª categoría): 5 % del alquiler bruto.
- Ganancia de capital al vender (persona natural): 5 % de la ganancia.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

UIT_2026_PEN = 5_500  # supuesto: valor de la UIT 2026; actualizar si cambia


@dataclass
class Supuestos:
    precio: float                      # precio de compra (moneda del crédito)
    alquiler_mensual: float            # alquiler esperado al inicio
    tipo_cambio: float = 3.45          # S/ por US$ (para la alcabala, que se mide en UIT)
    moneda: str = "USD"
    cuota_inicial_pct: float = 0.20
    tasa_anual: float = 0.0629         # TEA del crédito hipotecario (BCRP)
    plazo_anios: int = 20
    horizonte_anios: int = 10
    primera_venta: bool = False        # True si es estreno comprado a la inmobiliaria
    notaria_registros_pct: float = 0.01
    vacancia_meses_anio: float = 1.0
    predial_arbitrios_pct: float = 0.004   # anual, sobre el precio
    seguros_pct: float = 0.0035            # desgravamen + inmueble, anual sobre el precio
    mantenimiento_propietario: float = 0.0  # mensual, si el dueño lo asume
    ir_alquiler_pct: float = 0.05
    crecimiento_alquiler: float = 0.02
    apreciacion_anual: float = 0.03
    costo_venta_pct: float = 0.035
    impuesto_ganancia_pct: float = 0.05
    tasa_descuento: float = 0.10       # costo de oportunidad del inversionista (VAN)


def cuota_mensual(principal: float, tasa_anual: float, plazo_anios: int) -> float:
    """Cuota fija (método francés) con TEA convertida a tasa efectiva mensual."""
    i = (1 + tasa_anual) ** (1 / 12) - 1
    n = plazo_anios * 12
    if i == 0:
        return principal / n
    return principal * i / (1 - (1 + i) ** -n)


def saldo_deuda(principal: float, tasa_anual: float, plazo_anios: int, meses_pagados: int) -> float:
    i = (1 + tasa_anual) ** (1 / 12) - 1
    c = cuota_mensual(principal, tasa_anual, plazo_anios)
    k = meses_pagados
    if i == 0:
        return max(principal - c * k, 0.0)
    return max(principal * (1 + i) ** k - c * ((1 + i) ** k - 1) / i, 0.0)


def van(tasa: float, flujos: list[float]) -> float:
    return float(sum(f / (1 + tasa) ** t for t, f in enumerate(flujos)))


def tir(flujos: list[float], lo: float = -0.99, hi: float = 1.0, tol: float = 1e-7) -> float | None:
    """TIR por bisección. None si los flujos no cambian de signo en el rango."""
    f_lo, f_hi = van(lo, flujos), van(hi, flujos)
    if np.sign(f_lo) == np.sign(f_hi):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = van(mid, flujos)
        if abs(f_mid) < tol:
            break
        if np.sign(f_mid) == np.sign(f_lo):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def alcabala(s: Supuestos) -> float:
    if s.primera_venta:
        return 0.0
    precio_pen = s.precio * (s.tipo_cambio if s.moneda == "USD" else 1)
    base_pen = max(precio_pen - 10 * UIT_2026_PEN, 0)
    return 0.03 * base_pen / (s.tipo_cambio if s.moneda == "USD" else 1)


def proyectar(s: Supuestos) -> tuple[pd.DataFrame, dict]:
    """Devuelve (tabla anual de flujos, indicadores)."""
    prestamo = s.precio * (1 - s.cuota_inicial_pct)
    cuota = cuota_mensual(prestamo, s.tasa_anual, s.plazo_anios)
    gastos_compra = s.precio * s.notaria_registros_pct + alcabala(s)
    inversion_inicial = s.precio * s.cuota_inicial_pct + gastos_compra

    filas = [{"anio": 0, "alquiler_bruto": 0.0, "noi": 0.0, "servicio_deuda": 0.0,
              "flujo_neto": -inversion_inicial, "saldo_deuda": prestamo}]
    for t in range(1, s.horizonte_anios + 1):
        alquiler_anual = s.alquiler_mensual * (1 + s.crecimiento_alquiler) ** (t - 1) * 12
        ingreso = alquiler_anual * (1 - s.vacancia_meses_anio / 12)
        gastos = (ingreso * s.ir_alquiler_pct
                  + s.precio * (s.predial_arbitrios_pct + s.seguros_pct)
                  + s.mantenimiento_propietario * 12)
        noi = ingreso - gastos
        meses_con_cuota = max(0, min(12, s.plazo_anios * 12 - (t - 1) * 12))
        servicio = cuota * meses_con_cuota
        flujo = noi - servicio
        saldo = saldo_deuda(prestamo, s.tasa_anual, s.plazo_anios, min(t * 12, s.plazo_anios * 12))
        filas.append({"anio": t, "alquiler_bruto": alquiler_anual, "noi": noi,
                      "servicio_deuda": servicio, "flujo_neto": flujo, "saldo_deuda": saldo})

    tabla = pd.DataFrame(filas)
    valor_venta = s.precio * (1 + s.apreciacion_anual) ** s.horizonte_anios
    ganancia = max(valor_venta - s.precio, 0)
    neto_venta = (valor_venta * (1 - s.costo_venta_pct) - ganancia * s.impuesto_ganancia_pct
                  - tabla.iloc[-1]["saldo_deuda"])
    tabla["venta"] = 0.0
    tabla.loc[tabla.index[-1], "venta"] = neto_venta
    tabla["flujo_total"] = tabla["flujo_neto"] + tabla["venta"]

    flujos = tabla["flujo_total"].tolist()
    acumulado = tabla["flujo_neto"].cumsum()
    anio1 = tabla.iloc[1]
    indicadores = {
        "inversion_inicial": inversion_inicial,
        "gastos_compra": gastos_compra,
        "prestamo": prestamo,
        "cuota_mensual": cuota,
        "alquiler_neto_mensual_anio1": anio1["noi"] / 12,
        "flujo_mensual_anio1": anio1["flujo_neto"] / 12,
        "rentabilidad_bruta": s.alquiler_mensual * 12 / s.precio,
        "cap_rate": anio1["noi"] / s.precio,
        "cash_on_cash": anio1["flujo_neto"] / inversion_inicial,
        "tir": tir(flujos),
        "van": van(s.tasa_descuento, flujos),
        "valor_venta": valor_venta,
        "neto_venta": neto_venta,
        "payback_anios": next((int(a) for a, c in zip(tabla["anio"], acumulado) if a > 0 and c >= 0), None),
    }
    indicadores = {k: (float(v) if isinstance(v, (int, float, np.floating)) and k != "payback_anios" else v)
                   for k, v in indicadores.items()}
    indicadores["supuestos"] = asdict(s)
    return tabla, indicadores
