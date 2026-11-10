"""DepaRadar · encuentra departamentos bajo precio en Lima Moderna y mira si su flujo de caja cuadra.

Correr en local:
    uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # para Streamlit Cloud, que no instala el paquete

import altair as alt  # noqa: E402
import folium  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit_folium import st_folium  # noqa: E402

from deparadar import bcrp  # noqa: E402
from deparadar.agente import Herramientas, responder  # noqa: E402
from deparadar.config import DATA_PROCESSED  # noqa: E402
from deparadar.finanzas import Supuestos, precio_maximo, proyectar  # noqa: E402
from deparadar.ranking import etiquetas, rankear, supuestos_para  # noqa: E402

AZUL, ROJO, GRIS = "#2a78d6", "#e34948", "#9a9993"
LIMITE_GRATIS = 3          # oportunidades visibles en el plan gratis
PREGUNTAS_PRO_MES = 100    # tope de preguntas al agente en Pro (controla el costo por usuario)

st.set_page_config(page_title="DepaRadar", page_icon="🏢", layout="wide")


# ---------- datos ----------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cargar_bcrp() -> dict:
    return bcrp.indicadores()


@st.cache_data(show_spinner=False)
def cargar_venta() -> pd.DataFrame:
    return pd.read_csv(DATA_PROCESSED / "venta.csv")


@st.cache_data(show_spinner=False)
def cargar_metricas() -> dict:
    return json.loads((DATA_PROCESSED / "metricas.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Calculando el flujo de caja de cada aviso…")
def ranking(base: Supuestos) -> pd.DataFrame:
    return rankear(cargar_venta(), base)


def usd(x: float) -> str:
    return f"US$ {x:,.0f}"


def usd_k(x: float) -> str:
    return f"US$ {x / 1000:,.0f}k" if abs(x) >= 10_000 else usd(x)


def pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:.1f} %"


ind = cargar_bcrp()
metricas = cargar_metricas()

# ---------- encabezado ----------
st.title("🏢 DepaRadar")
st.markdown(
    "**Encuentra departamentos que se venden bajo su precio de mercado en Lima Moderna "
    "y descubre en un minuto si comprarlos para alquilar *cuadra*.**"
)
st.caption(
    f"{metricas['avisos_venta']:,} avisos de venta y {metricas['avisos_alquiler']:,} de alquiler de InfoCasas "
    f"({metricas['fecha_datos']}) · Tasas y tipo de cambio del BCRP "
    f"{'en vivo' if ind.get('en_vivo') else '(último dato guardado)'} · "
    "Atributos del texto leídos con Gemini"
)

# ---------- barra lateral: el crédito ----------
with st.sidebar:
    plan = st.segmented_control("Tu plan", ["Gratis", "Pro ⭐"], default="Pro ⭐",
                                help="Demo: el cambio de plan es simulado, no se cobra nada.")
    es_pro = plan == "Pro ⭐"
    if es_pro:
        st.caption("⭐ **Pro · S/ 39/mes:** 10 distritos, oportunidades ilimitadas, precio máximo a ofrecer y analista IA.")
    else:
        st.caption(f"Plan gratis: 1 distrito y las {LIMITE_GRATIS} mejores oportunidades. **Pro: S/ 39/mes.**")
    st.divider()
    st.header("Tu inversión")
    moneda = st.radio("Crédito hipotecario en", ["Dólares", "Soles"], horizontal=True)
    tasa_bcrp = ind["tasa_hipotecaria_usd" if moneda == "Dólares" else "tasa_hipotecaria_pen"]
    periodo = ind["periodo_tasa_hipotecaria_usd" if moneda == "Dólares" else "periodo_tasa_hipotecaria_pen"]
    tasa = st.slider("Tasa del crédito (TEA %)", 3.0, 15.0, float(round(tasa_bcrp, 2)), 0.05,
                     help=f"Por defecto: promedio de la banca según el BCRP ({periodo}).")
    st.caption(f"BCRP {periodo}: {tasa_bcrp:.2f} % · Tipo de cambio {ind['tipo_cambio']:.3f}")
    inicial = st.slider("Cuota inicial (%)", 10, 50, 20, 5)
    plazo = st.slider("Plazo del crédito (años)", 5, 30, 20, 5)
    descuento_inv = st.slider("Tu costo de oportunidad (%)", 4.0, 15.0, 10.0, 0.5,
                              help="Lo que ganarías en tu mejor alternativa. Si el VAN a esta tasa es positivo, la inversión cuadra.")
    horizonte = st.slider("Horizonte de inversión (años)", 5, 20, 10)
    with st.expander("Más supuestos"):
        vacancia = st.slider("Meses sin inquilino al año", 0.0, 3.0, 1.0, 0.5)
        apreciacion = st.slider("Apreciación anual del inmueble (%)", 0.0, 6.0, 3.0, 0.5)
        crec_alq = st.slider("Crecimiento anual del alquiler (%)", 0.0, 6.0, 2.0, 0.5)
    if moneda == "Soles":
        st.caption("Con crédito en soles se asume tipo de cambio constante (todo se muestra en US$).")

base = Supuestos(
    precio=1, alquiler_mensual=1, tipo_cambio=ind["tipo_cambio"], cuota_inicial_pct=inicial / 100,
    tasa_anual=tasa / 100, plazo_anios=plazo, horizonte_anios=horizonte, tasa_descuento=descuento_inv / 100,
    vacancia_meses_anio=vacancia, apreciacion_anual=apreciacion / 100, crecimiento_alquiler=crec_alq / 100,
)
df = ranking(base)

tab_radar, tab_agente, tab_como = st.tabs(["🔎 Radar de oportunidades", "💬 Analista IA ⭐", "ℹ️ Cómo funciona"])

# Las pestañas se llenan en este orden (agente y "cómo funciona" primero) para que
# un st.stop() dentro del radar no las deje vacías.


# ---------- analista IA (Pro) ----------
def clave_gemini() -> bool:
    try:  # en Streamlit Cloud la clave vive en Secrets; en local, en .env
        if "GEMINI_API_KEY" in st.secrets:
            os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    except Exception:  # noqa: BLE001 - no hay secrets.toml en local
        pass
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    return bool(os.environ.get("GEMINI_API_KEY"))


with tab_agente:
    st.subheader("💬 Tu analista inmobiliario")
    st.caption("Pregúntale en lenguaje natural. Gemini busca en los avisos reales y calcula con tu crédito de la barra lateral; "
               "las cifras salen de nuestras funciones, no del modelo.")
    if not es_pro:
        st.info("🔒 **El analista IA es parte de DepaRadar Pro (S/ 39/mes).** "
                "Cambia a *Pro* en la barra lateral para probarlo (demo, sin cobro).")
    elif not clave_gemini():
        st.warning("Falta la clave de Gemini (`GEMINI_API_KEY`) en `.env` o en los Secrets de Streamlit Cloud.")
    else:
        from deparadar.llm import _modelos, cliente

        st.session_state.setdefault("chat", [])
        st.session_state.setdefault("costo_chat", 0.0)
        sugerencias = [
            "Búscame depas en Surco bajo US$150 mil que cuadren",
            "¿Qué distrito tiene la mejor rentabilidad por alquiler?",
            "¿Cuánto ofrecer por la mejor oportunidad de Miraflores?",
        ]
        cols = st.columns(len(sugerencias))
        pregunta_boton = next((s for c, s in zip(cols, sugerencias) if c.button(s, use_container_width=True)), None)

        for m in st.session_state["chat"]:
            with st.chat_message("user" if m["rol"] == "user" else "assistant"):
                st.markdown(m["texto"])
                if m.get("meta"):
                    st.caption(m["meta"])

        usadas = sum(1 for m in st.session_state["chat"] if m["rol"] == "user")
        pregunta = pregunta_boton or st.session_state.pop("pendiente", None)
        if pregunta and usadas >= PREGUNTAS_PRO_MES:
            st.warning(f"Llegaste al tope de {PREGUNTAS_PRO_MES} preguntas del mes.")
        elif pregunta:
            with st.chat_message("user"):
                st.markdown(pregunta)
            with st.chat_message("assistant"):
                with st.spinner("Buscando en los avisos y calculando…"):
                    try:
                        herramientas = Herramientas(df, base, ind)
                        historial = [{"rol": m["rol"], "texto": m["texto"]} for m in st.session_state["chat"]]
                        texto, uso = responder(cliente(), herramientas, historial, pregunta, _modelos())
                    except Exception as e:  # noqa: BLE001
                        texto, uso = f"No pude responder ahora ({str(e)[:120]}). Intenta de nuevo en unos segundos.", None
                st.markdown(texto)
                meta = ""
                if uso:
                    herr = ", ".join(dict.fromkeys(uso.llamadas_herramientas)) or "ninguna"
                    meta = (f"🔧 Herramientas: {herr} · {uso.tokens_entrada:,} + {uso.tokens_salida:,} tokens · "
                            f"costo ≈ US$ {uso.costo_usd:.4f}")
                    st.session_state["costo_chat"] += uso.costo_usd
                    st.caption(meta)
            st.session_state["chat"] += [{"rol": "user", "texto": pregunta}, {"rol": "model", "texto": texto, "meta": meta}]
            st.rerun()  # vuelve a dibujar: la conversación queda arriba y la caja de texto abajo
        if st.session_state["chat"]:
            st.caption(f"Preguntas este mes: {usadas}/{PREGUNTAS_PRO_MES} · "
                       f"costo acumulado de esta sesión ≈ US$ {st.session_state['costo_chat']:.4f}")
            if st.button("🗑️ Nueva conversación"):
                st.session_state["chat"], st.session_state["costo_chat"] = [], 0.0
                st.rerun()
        escrita = st.chat_input("Ej.: depas de 2 dormitorios en Barranco que cuadren con 30 % de inicial")
        if escrita:
            st.session_state["pendiente"] = escrita
            st.rerun()

with tab_como:
    st.subheader("Cómo funciona DepaRadar")
    st.markdown(f"""
1. **Datos reales.** Un scraper lee avisos de venta y alquiler de departamentos en 10 distritos de Lima Moderna (InfoCasas), respetando su `robots.txt`.
2. **Gemini lee cada aviso** y extrae lo que la ficha no dice: si es dúplex, la vista, si hay que remodelar o si el vendedor tiene urgencia.
3. **Precio justo.** Un modelo de *machine learning* estima el precio por m² según distrito, área, dormitorios, cocheras, estado, amenidades y ubicación exacta. Error mediano fuera de muestra: **{metricas['error_mediano_venta_pct']} %** (usar solo la mediana del distrito da 13.4 %).
4. **Alquiler estimado.** Otro modelo, entrenado con avisos de alquiler, estima cuánto se alquilaría cada depa en venta.
5. **Flujo de caja** con las tasas hipotecarias del **BCRP** y reglas peruanas: alcabala, impuesto a la renta del alquiler (5 %) y ganancia de capital (5 %).
6. **Analista IA (Pro).** Gemini con *function calling*: elige qué función nuestra llamar (buscar, evaluar, resumir el mercado, consultar el BCRP) y redacta la respuesta. ~US$ 0.002 por pregunta.

| Embudo | Avisos |
|---|---|
| Avisos de venta analizados | {len(df):,} |
| Bajo precio de mercado (15 %–40 %) | {int(df['oportunidad'].sum()):,} |
| Bajo precio **y** cuadran con tu crédito | {int((df['oportunidad'] & df['cuadra']).sum()):,} |

*DepaRadar es una herramienta de análisis, no una recomendación de inversión. Verifica siempre el inmueble, la partida registral y los números con un profesional.*
""")

with tab_radar:
    # ---------- filtros (una fila) ----------
    c1, c2, c3, c4 = st.columns([2.4, 1.3, 1, 2.3])
    if es_pro:
        distritos = c1.multiselect("Distritos", sorted(df["distrito"].unique()), placeholder="Todos")
    else:
        lista_d = sorted(df["distrito"].unique())
        distritos = [c1.selectbox("Distrito (gratis: 1)", lista_d, index=lista_d.index("Miraflores"))]
    presupuesto = c2.number_input("Presupuesto máx. (US$)", 30_000, 3_000_000, 300_000, 10_000)
    dorms = c3.selectbox("Dormitorios", ["Todos", "1+", "2+", "3+"])
    vista = c4.segmented_control("Mostrar", ["Bajo precio", "Que cuadran", "Todos"], default="Bajo precio")

    f = df[df["precio_usd"] <= presupuesto]
    if distritos:
        f = f[f["distrito"].isin(distritos)]
    if dorms != "Todos":
        f = f[f["dormitorios"] >= int(dorms[0])]
    if vista == "Bajo precio":
        f = f[f["oportunidad"]]
    elif vista == "Que cuadran":
        f = f[f["oportunidad"] & f["cuadra"]]
    # Los descuentos sospechosos (>40 %, casi siempre errores del aviso) van al final
    f = f.sort_values(["revisar_aviso", "cuadra", "tir"], ascending=[True, False, False])
    bloqueadas = 0
    if not es_pro and len(f) > LIMITE_GRATIS:
        bloqueadas = len(f) - LIMITE_GRATIS
        f = f.head(LIMITE_GRATIS)

    # ---------- KPIs ----------
    base_filtros = df[df["precio_usd"] <= presupuesto]
    if distritos:
        base_filtros = base_filtros[base_filtros["distrito"].isin(distritos)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Avisos analizados", f"{len(base_filtros):,}")
    k2.metric("Bajo precio de mercado", f"{int(base_filtros['oportunidad'].sum()):,}", help="15 % a 40 % por debajo del precio justo estimado")
    k3.metric("Bajo precio y cuadran", f"{int((base_filtros['oportunidad'] & base_filtros['cuadra']).sum()):,}",
              help=f"Además, VAN positivo a tu costo de oportunidad de {descuento_inv:.1f} %")
    k4.metric("Flujo mensual típico", usd(base_filtros["flujo_mensual"].median()) if len(base_filtros) else "—",
              help="Mediana del flujo mensual del año 1 (alquiler neto menos cuota) con tu crédito")

    if f.empty:
        st.info("No hay avisos con esos filtros. Prueba ampliando el presupuesto o los distritos.")
        st.stop()

    # ---------- mapa + tabla ----------
    col_mapa, col_tabla = st.columns([1, 1.25])
    with col_mapa:
        geo = f.dropna(subset=["latitud", "longitud"])
        m = folium.Map(location=[-12.11, -77.03], zoom_start=13, tiles="OpenStreetMap")
        for _, r in geo.iterrows():
            color = AZUL if r["cuadra"] else GRIS
            folium.CircleMarker(
                [r["latitud"], r["longitud"]], radius=7 if r["cuadra"] else 5, color="#fcfcfb", weight=2,
                fill=True, fill_color=color, fill_opacity=0.9,
                tooltip=(f"<b>{r['distrito']}</b> · {usd(r['precio_usd'])}<br>"
                         f"{r['area_m2']:.0f} m² · {r['descuento_pct']:.0f} % bajo mercado<br>"
                         f"TIR {pct(r['tir'])} · {'✅ cuadra' if r['cuadra'] else '❌ no cuadra'}"),
            ).add_to(m)
        st_folium(m, height=460, use_container_width=True, returned_objects=[])
        st.caption("🔵 cuadra (VAN > 0) · ⚪ bajo precio pero no cuadra con tu crédito")

    with col_tabla:
        tabla = f.assign(
            veredicto=f["cuadra"].map({True: "✅ Cuadra", False: "❌ No"}),
            tir_pct=f["tir"] * 100,
        )[["veredicto", "distrito", "precio_usd", "area_m2", "dormitorios", "descuento_pct",
           "rentabilidad_bruta_pct", "tir_pct", "flujo_mensual", "etiquetas", "id"]]
        sel = st.dataframe(
            tabla, hide_index=True, height=460, on_select="rerun", selection_mode="single-row",
            column_order=[c for c in tabla.columns if c != "id"],
            column_config={
                "veredicto": "¿Cuadra?",
                "distrito": "Distrito",
                "precio_usd": st.column_config.NumberColumn("Precio", format="$%d"),
                "area_m2": st.column_config.NumberColumn("m²", format="%d"),
                "dormitorios": st.column_config.NumberColumn("Dorm.", format="%d"),
                "descuento_pct": st.column_config.NumberColumn("Bajo mercado", format="%.0f %%"),
                "rentabilidad_bruta_pct": st.column_config.NumberColumn("Rent. bruta", format="%.1f %%"),
                "tir_pct": st.column_config.NumberColumn("TIR", format="%.1f %%"),
                "flujo_mensual": st.column_config.NumberColumn("Flujo/mes", format="$%d"),
                "etiquetas": "Lo que dice el aviso",
            },
        )
        if bloqueadas:
            st.info(f"🔒 **{bloqueadas} oportunidades más** en {distritos[0]} y los otros 9 distritos con **Pro (S/ 39/mes)**.")
        st.caption("Selecciona una fila para ver su flujo de caja ↓")

    filas_sel = sel.selection.rows if sel and sel.selection else []
    aviso = f.iloc[filas_sel[0]] if filas_sel else f.iloc[0]

    # ---------- evaluación de un aviso ----------
    st.divider()
    st.subheader(f"📊 {aviso['titulo']}")
    st.markdown(
        f"**{aviso['distrito']}** · {aviso['area_m2']:.0f} m² · {aviso['dormitorios']:.0f} dorm. · "
        f"{aviso['banos']:.0f} baños · {aviso['cocheras']:.0f} cochera(s) · {aviso['estado']} · "
        f"[Ver aviso original ↗]({aviso['url']})"
    )
    tags = etiquetas(aviso)
    if tags:
        st.markdown(" ".join(f":blue-badge[{t}]" for t in tags))

    e1, e2 = st.columns(2)
    precio_oferta = e1.number_input("Precio que ofrecerías (US$)", 10_000, 5_000_000, int(aviso["precio_usd"]), 1_000)
    alquiler = e2.number_input("Alquiler mensual esperado (US$)", 100, 20_000, int(round(aviso["alquiler_estimado_usd"], -1)), 10,
                               help="Por defecto: alquiler estimado por nuestro modelo con avisos de alquiler de la zona.")
    s = replace(supuestos_para(aviso, base), precio=float(precio_oferta), alquiler_mensual=float(alquiler))
    tabla_flujo, res = proyectar(s)
    p_max = precio_maximo(s)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio justo estimado", usd_k(aviso["precio_justo_usd"]),
              f"{aviso['descuento_pct']:.0f} % bajo mercado" if aviso["descuento_pct"] > 0 else f"{-aviso['descuento_pct']:.0f} % sobre mercado",
              delta_color="normal" if aviso["descuento_pct"] > 0 else "inverse")
    m2.metric("Pones al inicio", usd_k(res["inversion_inicial"]), help="Cuota inicial + notaría y registros + alcabala")
    m3.metric("Cuota mensual del crédito", usd(res["cuota_mensual"]))
    m4.metric("Flujo mensual (año 1)", usd(res["flujo_mensual_anio1"]),
              help="Alquiler neto de vacancia, impuestos, predial y seguros, menos la cuota.")
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("TIR de tu inversión", pct(res["tir"]))
    m6.metric(f"VAN al {descuento_inv:.1f} %", usd_k(res["van"]))
    m7.metric("Cash-on-cash (año 1)", pct(res["cash_on_cash"]), help="Flujo del año 1 / lo que pusiste al inicio")
    m8.metric(f"Venta neta al año {horizonte}", usd_k(res["neto_venta"]),
              help="Valor con apreciación, menos comisión, impuesto a la ganancia y deuda pendiente")

    if res["van"] > 0:
        st.success(f"✅ **Cuadra.** Con tu crédito, esta compra rinde {pct(res['tir'])} al año, más que tu costo de oportunidad "
                   f"({descuento_inv:.1f} %). Pondrías {usd(res['inversion_inicial'])} al inicio (inicial + notaría + alcabala).")
    else:
        st.error(f"❌ **No cuadra** a {usd(precio_oferta)}. Rinde {pct(res['tir'])} al año, menos que tu costo de oportunidad.")
    if not es_pro:
        st.info("🔒 **¿Cuánto ofrecer para que cuadre?** Con Pro te decimos el precio máximo a ofrecer por este depa.")
    elif p_max is None:
        st.warning("💡 Con este alquiler, no hay un precio razonable al que cuadre con tu crédito.")
    elif p_max < precio_oferta:
        st.info(f"💡 **Para que cuadre, ofrece como máximo {usd(p_max)}** "
                f"({(p_max / aviso['precio_usd'] - 1) * 100:+.0f} % frente al precio pedido de {usd(aviso['precio_usd'])}).")
    else:
        st.info(f"💡 Podrías pagar hasta **{usd(p_max)}** y seguiría cuadrando: tienes margen de seguridad.")

    # Solo los años de operación: la inversión inicial y la venta van en las tarjetas de arriba,
    # porque en el mismo eje aplastarían los flujos anuales.
    g = tabla_flujo[tabla_flujo["anio"] > 0].assign(
        mensual=lambda d: d["flujo_neto"] / 12,
        tipo=lambda d: d["flujo_neto"].map(lambda v: "Te sobra dinero" if v >= 0 else "Pones de tu bolsillo"),
    )
    chart = alt.Chart(g).mark_bar(cornerRadiusEnd=4, size=28).encode(
        x=alt.X("anio:O", title="Año", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("mensual:Q", title="Flujo por mes (US$)", axis=alt.Axis(format=",.0f", grid=True, gridOpacity=0.3)),
        color=alt.Color("tipo:N", scale=alt.Scale(domain=["Pones de tu bolsillo", "Te sobra dinero"], range=[ROJO, AZUL]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("anio:O", title="Año"),
                 alt.Tooltip("mensual:Q", title="Flujo por mes", format=",.0f"),
                 alt.Tooltip("noi:Q", title="Alquiler neto del año", format=",.0f"),
                 alt.Tooltip("servicio_deuda:Q", title="Cuotas del año", format=",.0f")],
    ).properties(height=280, title="Flujo mensual promedio de cada año (alquiler neto − cuota)")
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#52514e", strokeWidth=1).encode(y="y:Q")
    chart = chart + cero
    st.altair_chart(chart, use_container_width=True)
    with st.expander("Ver la tabla del flujo de caja"):
        st.dataframe(tabla_flujo.round(0), hide_index=True, use_container_width=True)
