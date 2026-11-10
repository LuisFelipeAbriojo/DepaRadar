"""Modelos de precio justo (venta) y alquiler estimado.

Idea central de DepaRadar:
1. Un modelo hedónico aprende el precio por m² de VENTA según distrito, área,
   dormitorios, cocheras, estado, amenidades y ubicación exacta.
   Usamos predicciones "fuera de muestra" (validación cruzada): el precio justo
   de un aviso se estima con modelos que NUNCA vieron ese aviso.
   -> descuento = 1 - precio_pedido / precio_justo
2. Otro modelo aprende el ALQUILER por m² con los avisos de alquiler, y lo
   aplicamos a cada depa en venta para estimar cuánto se alquilaría.
   -> rentabilidad bruta = 12 * alquiler_estimado / precio
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold, cross_val_predict

from deparadar.limpieza import AMENIDADES

NUMERICAS = ["log_area", "dormitorios", "banos", "cocheras", "piso", "latitud", "longitud", "preventa", *AMENIDADES]
CATEGORICAS = ["distrito", "estado"]
FEATURES = NUMERICAS + CATEGORICAS

# Un descuento mayor a esto casi siempre es un error del aviso, no una ganga
DESCUENTO_MAX_CREIBLE = 0.40
# El error mediano del modelo es ~10 %: exigimos 15 % para que la señal supere al ruido
UMBRAL_OPORTUNIDAD = 0.15


def _matriz(df: pd.DataFrame) -> pd.DataFrame:
    X = df.assign(log_area=np.log(df["area_m2"]))[FEATURES].copy()
    for c in CATEGORICAS:
        X[c] = X[c].astype("category")
    return X


def _modelo(seed: int = 42) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=10,
        l2_regularization=1.0, categorical_features="from_dtype", random_state=seed,
    )


def _alinear_categorias(X: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    for c in CATEGORICAS:
        X[c] = pd.Categorical(X[c].astype(str), categories=ref[c].cat.categories)
    return X


def error_mediano_pct(real: pd.Series, pred: pd.Series) -> float:
    return float(np.median(np.abs(pred / real - 1)) * 100)


def valorizar(venta: pd.DataFrame, alquiler: pd.DataFrame, folds: int = 5) -> tuple[pd.DataFrame, dict]:
    """Agrega precio justo, descuento, alquiler estimado y rentabilidad a los avisos de venta."""
    venta = venta.copy()

    # 1) Precio justo de venta (fuera de muestra)
    Xv = _matriz(venta)
    yv = np.log(venta["usd_m2"])
    kf = KFold(folds, shuffle=True, random_state=42)
    venta["usd_m2_justo"] = np.exp(cross_val_predict(_modelo(), Xv, yv, cv=kf))
    venta["precio_justo_usd"] = venta["usd_m2_justo"] * venta["area_m2"]
    venta["descuento_pct"] = (1 - venta["precio_usd"] / venta["precio_justo_usd"]) * 100

    # 2) Alquiler estimado para cada depa en venta
    Xa = _matriz(alquiler)
    ya = np.log(alquiler["usd_m2"])
    alq_oof = np.exp(cross_val_predict(_modelo(), Xa, ya, cv=kf))
    modelo_alq = _modelo().fit(Xa, ya)
    venta["alquiler_estimado_usd"] = np.exp(modelo_alq.predict(_alinear_categorias(Xv.copy(), Xa))) * venta["area_m2"]
    venta["rentabilidad_bruta_pct"] = 12 * venta["alquiler_estimado_usd"] / venta["precio_usd"] * 100

    d = venta["descuento_pct"] / 100
    venta["oportunidad"] = d.between(UMBRAL_OPORTUNIDAD, DESCUENTO_MAX_CREIBLE)
    venta["revisar_aviso"] = d > DESCUENTO_MAX_CREIBLE

    metricas = {
        "avisos_venta": int(len(venta)),
        "avisos_alquiler": int(len(alquiler)),
        "error_mediano_venta_pct": round(error_mediano_pct(venta["usd_m2"], venta["usd_m2_justo"]), 1),
        "error_mediano_alquiler_pct": round(error_mediano_pct(alquiler["usd_m2"], pd.Series(alq_oof, index=alquiler.index)), 1),
        "oportunidades": int(venta["oportunidad"].sum()),
    }
    return venta, metricas
