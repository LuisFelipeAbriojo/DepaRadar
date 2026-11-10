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

from dataclasses import asdict, dataclass, replace

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


def van(tasa: float, flujos) -> float:
    f = np.asarray(flujos, dtype=float)
    return float(np.sum(f / (1 + tasa) ** np.arange(len(f))))


def tir(flujos, lo: float = -0.99, hi: float = 1.0, tol: float = 1e-7) -> float | None:
    """TIR por bisección. None si los flujos no cambian de signo en el rango."""
    f = np.asarray(flujos, dtype=float)
    f_lo, f_hi = van(lo, f), van(hi, f)
    if np.sign(f_lo) == np.sign(f_hi):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = van(mid, f)
        if abs(f_mid) < tol or hi - lo < 1e-9:
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


def proyectar(s: Supuestos, con_tabla: bool = True) -> tuple[pd.DataFrame | None, dict]:
    """Devuelve (tabla anual de flujos, indicadores).

    Se calcula con arrays de numpy (rápido: el radar evalúa ~900 avisos en cada cambio
    de supuestos); la tabla de pandas solo se arma si se pide.
    """
    n = s.horizonte_anios
    prestamo = s.precio * (1 - s.cuota_inicial_pct)
    cuota = cuota_mensual(prestamo, s.tasa_anual, s.plazo_anios)
    gastos_compra = s.precio * s.notaria_registros_pct + alcabala(s)
    inversion_inicial = s.precio * s.cuota_inicial_pct + gastos_compra

    t = np.arange(1, n + 1)
    alquiler_bruto = s.alquiler_mensual * (1 + s.crecimiento_alquiler) ** (t - 1) * 12
    ingreso = alquiler_bruto * (1 - s.vacancia_meses_anio / 12)
    gastos = (ingreso * s.ir_alquiler_pct + s.precio * (s.predial_arbitrios_pct + s.seguros_pct)
              + s.mantenimiento_propietario * 12)
    noi = ingreso - gastos
    meses_con_cuota = np.clip(s.plazo_anios * 12 - (t - 1) * 12, 0, 12)
    servicio = cuota * meses_con_cuota
    saldo = np.array([saldo_deuda(prestamo, s.tasa_anual, s.plazo_anios, min(k * 12, s.plazo_anios * 12)) for k in t])

    flujo_neto = np.concatenate([[-inversion_inicial], noi - servicio])
    valor_venta = s.precio * (1 + s.apreciacion_anual) ** n
    ganancia = max(valor_venta - s.precio, 0)
    neto_venta = valor_venta * (1 - s.costo_venta_pct) - ganancia * s.impuesto_ganancia_pct - saldo[-1]
    venta = np.zeros(n + 1)
    venta[-1] = neto_venta
    flujo_total = flujo_neto + venta

    acumulado = np.cumsum(flujo_neto)
    positivos = np.nonzero((np.arange(n + 1) > 0) & (acumulado >= 0))[0]
    tir_ = tir(flujo_total)
    indicadores = {
        "inversion_inicial": float(inversion_inicial),
        "gastos_compra": float(gastos_compra),
        "prestamo": float(prestamo),
        "cuota_mensual": float(cuota),
        "alquiler_neto_mensual_anio1": float(noi[0] / 12),
        "flujo_mensual_anio1": float(flujo_neto[1] / 12),
        "rentabilidad_bruta": float(s.alquiler_mensual * 12 / s.precio),
        "cap_rate": float(noi[0] / s.precio),
        "cash_on_cash": float(flujo_neto[1] / inversion_inicial),
        "tir": None if tir_ is None else float(tir_),
        "van": van(s.tasa_descuento, flujo_total),
        "valor_venta": float(valor_venta),
        "neto_venta": float(neto_venta),
        "payback_anios": int(positivos[0]) if len(positivos) else None,
        "supuestos": asdict(s),
    }
    tabla = None
    if con_tabla:
        tabla = pd.DataFrame({
            "anio": np.arange(n + 1),
            "alquiler_bruto": np.concatenate([[0.0], alquiler_bruto]),
            "noi": np.concatenate([[0.0], noi]),
            "servicio_deuda": np.concatenate([[0.0], servicio]),
            "flujo_neto": flujo_neto,
            "saldo_deuda": np.concatenate([[prestamo], saldo]),
            "venta": venta,
            "flujo_total": flujo_total,
        })
    return tabla, indicadores


def precio_maximo(s: Supuestos, tol: float = 50.0) -> float | None:
    """Precio más alto que se puede pagar para que el VAN sea >= 0 (manteniendo el alquiler).

    Sirve para negociar: "ofrece hasta X para que la inversión cuadre".
    """
    def van_a(precio: float) -> float:
        return proyectar(replace(s, precio=precio), con_tabla=False)[1]["van"]

    lo, hi = s.alquiler_mensual * 12 * 3, s.alquiler_mensual * 12 * 60  # rentabilidad bruta 33 % ... 1.7 %
    if van_a(lo) < 0:
        return None
    if van_a(hi) >= 0:
        return hi
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if van_a(mid) >= 0 else (lo, mid)
    return lo
