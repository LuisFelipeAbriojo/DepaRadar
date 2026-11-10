"""Agente de DepaRadar: Gemini con herramientas (function calling) sobre nuestros datos.

El modelo NO hace cuentas ni inventa avisos: decide qué herramienta llamar y
redacta la respuesta. Las cifras salen de Python (ranking, finanzas, BCRP), igual
que en el MCP del BCRP de la sesión 04.

Herramientas:
- buscar_oportunidades: filtra el ranking (distrito, presupuesto, dormitorios...).
- evaluar_aviso: flujo de caja completo de un aviso y precio máximo a ofrecer.
- resumen_mercado: precios y alquileres típicos por distrito.
- tasas_bcrp: tasas hipotecarias y tipo de cambio del BCRP.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from deparadar.finanzas import Supuestos, precio_maximo, proyectar
from deparadar.ranking import supuestos_para

PRECIO_ENTRADA_USD_M = 0.30   # gemini-3.5-flash-lite, US$ por millón de tokens (nov-2026)
PRECIO_SALIDA_USD_M = 2.50
MAX_PASOS = 5

INSTRUCCIONES = """Eres el analista de DepaRadar, una herramienta para inversionistas inmobiliarios
minoristas en Lima Moderna. Respondes en español peruano, claro y breve (máximo ~150 palabras).

Reglas:
- Usa SIEMPRE las herramientas para cualquier cifra o aviso. Nunca inventes avisos, precios ni tasas,
  y no hagas cálculos financieros a mano: pide la evaluación a la herramienta.
- Montos en US$. "Cuadra" significa VAN positivo con el crédito y el costo de oportunidad del usuario.
- Cuando recomiendes avisos, da para cada uno: id, distrito, precio, m², % bajo mercado, TIR,
  flujo mensual y sus etiquetas (p. ej. urge vender, dúplex), y menciona el precio máximo si lo evaluaste.
- Si pct_bajo_mercado es negativo, dilo como "X % sobre mercado".
- Si un aviso cuadra pero su flujo mensual es negativo, aclara que pondrías ese monto cada mes y que
  la rentabilidad depende de la apreciación y de la venta futura.
- Si un aviso dice dúplex o tríplex, advierte que el área puede incluir terrazas.
- Si no hay resultados, sugiere ampliar presupuesto o distritos.
- Termina con una línea corta: es un análisis, no una recomendación de inversión."""


def _r(x, n=0):
    return None if x is None or pd.isna(x) else round(float(x), n)


@dataclass
class Uso:
    tokens_entrada: int = 0
    tokens_salida: int = 0
    llamadas_herramientas: list[str] = field(default_factory=list)

    @property
    def costo_usd(self) -> float:
        return self.tokens_entrada / 1e6 * PRECIO_ENTRADA_USD_M + self.tokens_salida / 1e6 * PRECIO_SALIDA_USD_M


class Herramientas:
    """Funciones que Gemini puede llamar. Sus docstrings y tipos son la 'ficha' que ve el modelo."""

    def __init__(self, ranking: pd.DataFrame, base: Supuestos, bcrp: dict, distritos_permitidos: list[str] | None = None):
        self.df = ranking
        self.base = base
        self.bcrp = bcrp
        self.distritos_permitidos = distritos_permitidos

    def _ficha(self, f: pd.Series) -> dict:
        return {
            "id": int(f["id"]), "distrito": f["distrito"], "precio_usd": _r(f["precio_usd"]),
            "area_m2": _r(f["area_m2"]), "dormitorios": _r(f["dormitorios"]),
            "pct_bajo_mercado": _r(f["descuento_pct"], 1), "rentabilidad_bruta_pct": _r(f["rentabilidad_bruta_pct"], 1),
            "tir_pct": _r(f["tir"] * 100 if f["tir"] is not None and not pd.isna(f["tir"]) else None, 1),
            "flujo_mensual_usd": _r(f["flujo_mensual"]), "cuadra": bool(f["cuadra"]),
            "etiquetas": f.get("etiquetas") or "", "url": f["url"],
        }

    def buscar_oportunidades(
        self,
        distritos: list[str] | None = None,
        presupuesto_max_usd: float | None = None,
        dormitorios_min: int | None = None,
        solo_que_cuadran: bool = True,
        solo_bajo_mercado: bool = True,
        limite: int = 5,
    ) -> dict:
        """Busca departamentos en venta en Lima Moderna, ordenados por TIR.

        Args:
            distritos: Nombres de distritos, p. ej. ["Miraflores", "Santiago de Surco"]. Vacío = todos.
            presupuesto_max_usd: Precio máximo en dólares.
            dormitorios_min: Mínimo de dormitorios.
            solo_que_cuadran: Si es True, solo avisos con VAN positivo con el crédito del usuario.
            solo_bajo_mercado: Si es True, solo avisos 15 %-40 % bajo su precio justo.
            limite: Cuántos avisos devolver (máximo 10).
        """
        f = self.df[~self.df["revisar_aviso"]]
        permitidos = self.distritos_permitidos
        if distritos:
            pedidos = {d.lower() for d in distritos}
            f = f[f["distrito"].str.lower().isin(pedidos)]
        if permitidos:
            f = f[f["distrito"].isin(permitidos)]
        if presupuesto_max_usd:
            f = f[f["precio_usd"] <= presupuesto_max_usd]
        if dormitorios_min:
            f = f[f["dormitorios"] >= dormitorios_min]
        if solo_bajo_mercado:
            f = f[f["oportunidad"]]
        if solo_que_cuadran:
            f = f[f["cuadra"]]
        f = f.sort_values("tir", ascending=False)
        return {
            "total_encontrados": int(len(f)),
            "avisos": [self._ficha(r) for _, r in f.head(max(1, min(int(limite), 10))).iterrows()],
            "distritos_disponibles": sorted(self.df["distrito"].unique()) if f.empty else None,
        }

    def evaluar_aviso(self, aviso_id: int, precio_oferta_usd: float | None = None, alquiler_mensual_usd: float | None = None) -> dict:
        """Calcula el flujo de caja de comprar un aviso para alquilarlo con el crédito del usuario.

        Args:
            aviso_id: El id del aviso (de buscar_oportunidades).
            precio_oferta_usd: Precio a evaluar; por defecto, el precio pedido.
            alquiler_mensual_usd: Alquiler esperado; por defecto, el estimado por el modelo.
        """
        filas = self.df[self.df["id"] == int(aviso_id)]
        if filas.empty:
            return {"error": f"No existe el aviso {aviso_id}"}
        f = filas.iloc[0]
        s = supuestos_para(f, self.base)
        s = replace(s, precio=float(precio_oferta_usd or s.precio), alquiler_mensual=float(alquiler_mensual_usd or s.alquiler_mensual))
        _, ind = proyectar(s, con_tabla=False)
        p_max = precio_maximo(s)
        return {
            **self._ficha(f),
            "precio_evaluado_usd": _r(s.precio), "precio_justo_usd": _r(f["precio_justo_usd"]),
            "alquiler_mensual_usd": _r(s.alquiler_mensual), "inversion_inicial_usd": _r(ind["inversion_inicial"]),
            "cuota_mensual_usd": _r(ind["cuota_mensual"]), "flujo_mensual_anio1_usd": _r(ind["flujo_mensual_anio1"]),
            "tir_pct": _r(ind["tir"] * 100 if ind["tir"] is not None else None, 1), "van_usd": _r(ind["van"]),
            "cuadra_al_precio_evaluado": ind["van"] > 0, "precio_maximo_para_que_cuadre_usd": _r(p_max),
            "supuestos": {"tasa_credito_pct": _r(s.tasa_anual * 100, 2), "cuota_inicial_pct": _r(s.cuota_inicial_pct * 100),
                          "plazo_anios": s.plazo_anios, "costo_oportunidad_pct": _r(s.tasa_descuento * 100, 1)},
        }

    def resumen_mercado(self, distrito: str | None = None) -> dict:
        """Precio de venta típico por m², alquiler típico y rentabilidad bruta por distrito.

        Args:
            distrito: Un distrito; vacío = todos los distritos.
        """
        f = self.df if not distrito else self.df[self.df["distrito"].str.lower() == distrito.lower()]
        if f.empty:
            return {"error": f"Sin datos para {distrito}", "distritos": sorted(self.df["distrito"].unique())}
        g = f.groupby("distrito").agg(
            avisos=("id", "size"), venta_usd_m2_mediana=("usd_m2", "median"),
            alquiler_estimado_usd_mediano=("alquiler_estimado_usd", "median"),
            rentabilidad_bruta_pct_mediana=("rentabilidad_bruta_pct", "median"),
            oportunidades=("oportunidad", "sum"), que_cuadran=("cuadra", "sum"),
        ).round(1)
        return {"por_distrito": g.reset_index().to_dict("records")}

    def tasas_bcrp(self) -> dict:
        """Tasas hipotecarias promedio de la banca (soles y dólares) y tipo de cambio, según el BCRP."""
        return {k: v for k, v in self.bcrp.items() if k != "series"}

    def lista(self):
        return [self.buscar_oportunidades, self.evaluar_aviso, self.resumen_mercado, self.tasas_bcrp]


def responder(client, herramientas: Herramientas, historial: list[dict], pregunta: str, modelos: list[str]) -> tuple[str, Uso]:
    """Una vuelta de conversación. `historial` es [{"rol": "user"|"model", "texto": ...}]."""
    from google.genai import types

    funciones = {f.__name__: f for f in herramientas.lista()}
    contenidos = [types.Content(role=m["rol"], parts=[types.Part.from_text(text=m["texto"])]) for m in historial[-8:]]
    contenidos.append(types.Content(role="user", parts=[types.Part.from_text(text=pregunta)]))
    config = types.GenerateContentConfig(
        system_instruction=INSTRUCCIONES, tools=herramientas.lista(), temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    uso = Uso()

    def llamar():
        ultimo = None
        for modelo in modelos:  # respaldo si un modelo está saturado
            try:
                return client.models.generate_content(model=modelo, contents=contenidos, config=config)
            except Exception as e:  # noqa: BLE001
                ultimo = e
        raise RuntimeError(f"Gemini no respondió: {ultimo}")

    for _ in range(MAX_PASOS):
        r = llamar()
        u = r.usage_metadata
        uso.tokens_entrada += (u.prompt_token_count or 0) if u else 0
        uso.tokens_salida += ((u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)) if u else 0
        if not r.function_calls:
            return (r.text or "").strip(), uso
        contenidos.append(r.candidates[0].content)
        partes = []
        for fc in r.function_calls:
            uso.llamadas_herramientas.append(fc.name)
            try:
                resultado = funciones[fc.name](**(fc.args or {}))
            except Exception as e:  # noqa: BLE001 - el modelo recibe el error y puede corregir
                resultado = {"error": str(e)}
            partes.append(types.Part.from_function_response(name=fc.name, response={"resultado": resultado}))
        contenidos.append(types.Content(role="user", parts=partes))
    return "No pude completar el análisis en pocos pasos. ¿Puedes reformular la pregunta?", uso
