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
from deparadar.finanzas import Supuestos, desglose_mensual, precio_maximo, proyectar  # noqa: E402
from deparadar.informe import generar as generar_informe  # noqa: E402
from deparadar.ranking import etiquetas, rankear, supuestos_para  # noqa: E402

AZUL, ROJO, GRIS = "#2a78d6", "#e34948", "#9a9993"
NARANJA = "#eb6834"  # resalta el depa seleccionado en el mapa
OK, MAL = "#0ca30c", "#d03b3b"  # colores de estado (siempre con ícono y texto)
LIMITE_GRATIS = 3          # oportunidades visibles en el plan gratis
PREGUNTAS_PRO_MES = 100    # tope de preguntas al agente en Pro (controla el costo por usuario)

st.set_page_config(page_title="DepaRadar", page_icon="🏢", layout="wide")


# ---------- datos ----------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cargar_bcrp() -> dict:
    return bcrp.indicadores()


# Versión de los datos: cambia cuando la actualización diaria sube CSV nuevos.
# Se pasa a las funciones con caché para que no sigan mostrando datos viejos.
VERSION_DATOS = (DATA_PROCESSED / "metricas.json").stat().st_mtime


@st.cache_data(show_spinner=False)
def cargar_venta(version: float = VERSION_DATOS) -> pd.DataFrame:
    return pd.read_csv(DATA_PROCESSED / "venta.csv")


@st.cache_data(show_spinner=False)
def cargar_metricas(version: float = VERSION_DATOS) -> dict:
    return json.loads((DATA_PROCESSED / "metricas.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Calculando el flujo de caja de cada aviso…")
def ranking(base: Supuestos, version: float = VERSION_DATOS) -> pd.DataFrame:
    return rankear(cargar_venta(version), base)


def usd(x: float) -> str:
    return f"US$ {x:,.0f}"


def usd_k(x: float) -> str:
    return f"US$ {x / 1000:,.0f}k" if abs(x) >= 10_000 else usd(x)


def md(texto: str) -> str:
    """Escapa "$" para que Streamlit no lea "US$ 95,000 ... US$ 120,000" como una fórmula LaTeX."""
    return texto.replace("$", r"\$")


def pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:.1f} %"


ind = cargar_bcrp()
metricas = cargar_metricas(VERSION_DATOS)

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
    with st.expander("🏦 Tu crédito", expanded=True):
        moneda = st.radio("Crédito hipotecario en", ["Dólares", "Soles"], horizontal=True)
        tasa_bcrp = ind["tasa_hipotecaria_usd" if moneda == "Dólares" else "tasa_hipotecaria_pen"]
        periodo = ind["periodo_tasa_hipotecaria_usd" if moneda == "Dólares" else "periodo_tasa_hipotecaria_pen"]
        tasa = st.slider("Tasa del crédito (TEA %)", 3.0, 15.0, float(round(tasa_bcrp, 2)), 0.05,
                         help=f"Por defecto: promedio de la banca según el BCRP ({periodo}).")
        st.caption(f"BCRP {periodo}: {tasa_bcrp:.2f} % · Tipo de cambio {ind['tipo_cambio']:.3f}")
        inicial = st.slider("Cuota inicial (%)", 10, 50, 20, 5)
        plazo = st.slider("Plazo del crédito (años)", 5, 30, 20, 5)
    with st.expander("🎯 Tu objetivo"):
        descuento_inv = st.slider("Tu costo de oportunidad (%)", 4.0, 15.0, 10.0, 0.5,
                                  help="Lo que ganarías en tu mejor alternativa. Si el VAN a esta tasa es positivo, la inversión cuadra.")
        horizonte = st.slider("Horizonte de inversión (años)", 5, 20, 10)
    with st.expander("⚙️ Más supuestos"):
        vacancia = st.slider("Meses sin inquilino al año", 0.0, 3.0, 1.0, 0.5)
        apreciacion = st.slider("Apreciación anual del inmueble (%)", 0.0, 6.0, 3.0, 0.5)
        crec_alq = st.slider("Crecimiento anual del alquiler (%)", 0.0, 6.0, 2.0, 0.5)
        ajuste_alq = st.slider("Alquiler real vs. publicado (%)", -20, 0, 0, 1,
                               help="El alquiler estimado sale de avisos (lo que se PIDE). Un corredor nos dijo: "
                                    "'una cosa es lo que piden y otra lo que realmente paga el inquilino'. "
                                    "Pon -5 % o -10 % para ser conservador.")
    if moneda == "Soles":
        st.caption("Con crédito en soles se asume tipo de cambio constante (todo se muestra en US$).")

base = Supuestos(
    precio=1, alquiler_mensual=1, tipo_cambio=ind["tipo_cambio"], cuota_inicial_pct=inicial / 100,
    tasa_anual=tasa / 100, plazo_anios=plazo, horizonte_anios=horizonte, tasa_descuento=descuento_inv / 100,
    vacancia_meses_anio=vacancia, apreciacion_anual=apreciacion / 100, crecimiento_alquiler=crec_alq / 100,
    ajuste_alquiler=ajuste_alq / 100,
)
df = ranking(base, VERSION_DATOS)

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
                st.markdown(md(m["texto"]))
                if m.get("meta"):
                    st.caption(md(m["meta"]))

        usadas = sum(1 for m in st.session_state["chat"] if m["rol"] == "user")
        pregunta = pregunta_boton or st.session_state.pop("pendiente", None)
        if pregunta and usadas >= PREGUNTAS_PRO_MES:
            st.warning(f"Llegaste al tope de {PREGUNTAS_PRO_MES} preguntas del mes.")
        elif pregunta:
            with st.chat_message("user"):
                st.markdown(md(pregunta))
            with st.chat_message("assistant"):
                with st.spinner("Buscando en los avisos y calculando…"):
                    try:
                        herramientas = Herramientas(df, base, ind)
                        historial = [{"rol": m["rol"], "texto": m["texto"]} for m in st.session_state["chat"]]
                        texto, uso = responder(cliente(), herramientas, historial, pregunta, _modelos())
                    except Exception as e:  # noqa: BLE001
                        texto, uso = f"No pude responder ahora ({str(e)[:120]}). Intenta de nuevo en unos segundos.", None
                st.markdown(md(texto))
                meta = ""
                if uso:
                    herr = ", ".join(dict.fromkeys(uso.llamadas_herramientas)) or "ninguna"
                    meta = (f"🔧 Herramientas: {herr} · {uso.tokens_entrada:,} + {uso.tokens_salida:,} tokens · "
                            f"costo ≈ US$ {uso.costo_usd:.4f}")
                    st.session_state["costo_chat"] += uso.costo_usd
                    st.caption(md(meta))
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
3. **Precio justo.** Un modelo de *machine learning* estima el precio por m² según distrito, área, dormitorios, cocheras, estado, amenidades y ubicación exacta. Error mediano fuera de muestra: **{metricas['error_mediano_venta_pct']} %** (usar solo la mediana del distrito da {metricas.get('error_mediana_distrito_pct', 13.4)} %).
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

    # ---------- top 3 de hoy (tarjetas) ----------
    top = f[f["cuadra"] & ~f["revisar_aviso"]].head(3)
    if len(top):
        st.markdown("#### 🏆 Las mejores oportunidades con tu crédito")
        cols_top = st.columns(3)
        for col, (_, r) in zip(cols_top, top.iterrows()):
            with col.container(border=True):
                st.markdown(md(f"**{r['distrito']}** · {r['area_m2']:.0f} m² · {r['dormitorios']:.0f} dorm."))
                st.markdown(md(f"### {usd(r['precio_usd'])}"))
                st.markdown(md(f":green[**{r['descuento_pct']:.0f} % bajo mercado**] · TIR **{pct(r['tir'])}** · "
                               f"flujo {usd(r['flujo_mensual'])}/mes"))
                st.caption(r["etiquetas"] or "Sin alertas en el texto del aviso")
                if st.button("Ver análisis →", key=f"top_{r['id']}", use_container_width=True):
                    st.session_state["aviso_id"] = int(r["id"])

    # ---------- tabla + mapa ----------
    col_mapa, col_tabla = st.columns([1, 1.25])
    with col_tabla:
        tabla = f.assign(
            veredicto=f["cuadra"].map({True: "✅ Cuadra", False: "❌ No"}),
            tir_pct=f["tir"] * 100,
            precio_k=f["precio_usd"] / 1000,  # en miles: formato fijo, igual en cualquier idioma del navegador
        )[["veredicto", "distrito", "precio_k", "area_m2", "dormitorios", "descuento_pct",
           "rentabilidad_bruta_pct", "tir_pct", "flujo_mensual", "etiquetas", "id"]]
        sel = st.dataframe(
            tabla, hide_index=True, height=440, on_select="rerun", selection_mode="single-row",
            column_order=[c for c in tabla.columns if c != "id"], key="tabla_avisos",
            column_config={
                "veredicto": st.column_config.TextColumn("¿Cuadra?", width="small"),
                "distrito": st.column_config.TextColumn("Distrito", width="medium"),
                "precio_k": st.column_config.NumberColumn("Precio", format="$%.0fk"),
                "area_m2": st.column_config.NumberColumn("m²", format="%d", width="small"),
                "dormitorios": st.column_config.NumberColumn("Dorm.", format="%d", width="small"),
                "descuento_pct": st.column_config.ProgressColumn("Bajo mercado", format="%.0f %%", min_value=0, max_value=40),
                "rentabilidad_bruta_pct": st.column_config.NumberColumn("Rent. bruta", format="%.1f %%"),
                "tir_pct": st.column_config.NumberColumn("TIR", format="%.1f %%"),
                "flujo_mensual": st.column_config.NumberColumn("Flujo/mes", format="$%d"),
                "etiquetas": st.column_config.TextColumn("Lo que dice el aviso", width="large"),
            },
        )
        if bloqueadas:
            st.info(f"🔒 **{bloqueadas} oportunidades más** en {distritos[0]} y los otros 9 distritos con **Pro (S/ 39/mes)**.")
        st.caption("Selecciona una fila (o una tarjeta) para ver su análisis ↓")

    # Qué aviso se evalúa: un clic nuevo en la tabla manda; si no, la última tarjeta elegida; si no, el primero
    filas_sel = list(sel.selection.rows) if sel and sel.selection else []
    if filas_sel and filas_sel != st.session_state.get("sel_prev"):
        st.session_state["aviso_id"] = int(f.iloc[filas_sel[0]]["id"])
    st.session_state["sel_prev"] = filas_sel
    ids = f["id"].astype(int).tolist()
    aviso_id = st.session_state.get("aviso_id")
    aviso = f.iloc[ids.index(aviso_id)] if aviso_id in ids else f.iloc[0]

    with col_mapa:
        geo = f.dropna(subset=["latitud", "longitud"])
        tiene_coord = pd.notna(aviso["latitud"]) and pd.notna(aviso["longitud"])
        centro = [aviso["latitud"], aviso["longitud"]] if tiene_coord else [-12.11, -77.03]
        m = folium.Map(location=centro, zoom_start=15 if tiene_coord else 13, tiles="OpenStreetMap")
        for _, r in geo.iterrows():
            if int(r["id"]) == int(aviso["id"]):
                continue
            color = AZUL if r["cuadra"] else GRIS
            folium.CircleMarker(
                [r["latitud"], r["longitud"]], radius=7 if r["cuadra"] else 5, color="#fcfcfb", weight=2,
                fill=True, fill_color=color, fill_opacity=0.9,
                tooltip=(f"<b>{r['distrito']}</b> · {usd(r['precio_usd'])}<br>"
                         f"{r['area_m2']:.0f} m² · {r['descuento_pct']:.0f} % bajo mercado<br>"
                         f"TIR {pct(r['tir'])} · {'✅ cuadra' if r['cuadra'] else '❌ no cuadra'}"),
            ).add_to(m)
        if tiene_coord:
            folium.CircleMarker(
                centro, radius=12, color="#0b0b0b", weight=3, fill=True, fill_color=NARANJA, fill_opacity=1,
                tooltip=f"<b>Seleccionado:</b> {aviso['distrito']} · {usd(aviso['precio_usd'])}",
            ).add_to(m)
        st_folium(m, center=centro, zoom=15 if tiene_coord else 13, height=440, use_container_width=True,
                  returned_objects=[], key=f"mapa_{int(aviso['id'])}_{es_pro}_{len(f)}")
        st.caption("🟠 seleccionado · 🔵 cuadra (VAN > 0) · ⚪ no cuadra con tu crédito"
                   + ("" if tiene_coord else " · este aviso no tiene ubicación exacta"))

    # ---------- evaluación de un aviso ----------
    st.divider()
    st.subheader(f"📊 {aviso['titulo']}")
    st.markdown(md(
        f"**{aviso['distrito']}** · {aviso['area_m2']:.0f} m² · {aviso['dormitorios']:.0f} dorm. · "
        f"{aviso['banos']:.0f} baños · {aviso['cocheras']:.0f} cochera(s) · {aviso['estado']} · "
        f"[Ver aviso original ↗]({aviso['url']})"
    ))
    tags = etiquetas(aviso)
    if tags:
        st.markdown(" ".join(f":blue-badge[{t}]" for t in tags))

    e1, e2 = st.columns(2)
    precio_oferta = e1.number_input("Precio que ofrecerías (US$)", 10_000, 5_000_000, int(aviso["precio_usd"]), 1_000,
                                    key=f"oferta_{int(aviso['id'])}")
    alquiler = e2.number_input("Alquiler mensual esperado (US$)", 100, 20_000, int(round(aviso["alquiler_estimado_usd"], -1)), 10,
                               key=f"alquiler_{int(aviso['id'])}",
                               help="Por defecto: alquiler estimado por nuestro modelo con avisos de alquiler de la zona.")
    s = replace(supuestos_para(aviso, base), precio=float(precio_oferta), alquiler_mensual=float(alquiler))
    tabla_flujo, res = proyectar(s)
    p_max = precio_maximo(s)
    desglose = desglose_mensual(s)

    # Veredicto grande: se lee desde lejos al compartir pantalla (color de estado + ícono + texto)
    cuadra = res["van"] > 0
    if not es_pro:
        sub = "🔒 Con Pro te decimos cuánto ofrecer como máximo para que cuadre."
    elif p_max is None:
        sub = "Con este alquiler no hay un precio razonable al que cuadre con tu crédito."
    elif p_max < precio_oferta:
        sub = (f"Para que cuadre, ofrece como máximo <b>{usd(p_max)}</b> "
               f"({(p_max / aviso['precio_usd'] - 1) * 100:+.0f} % frente al precio pedido).")
    else:
        sub = f"Podrías pagar hasta <b>{usd(p_max)}</b> y seguiría cuadrando: tienes margen de seguridad."
    color_v = OK if cuadra else MAL
    titulo_v = "✅ CUADRA" if cuadra else "❌ NO CUADRA"
    html_v = (
        f'<div style="border-left:8px solid {color_v};background:rgba(127,127,127,.08);padding:14px 20px;'
        f'border-radius:8px;margin:8px 0 16px 0">'
        f'<div style="font-size:2rem;font-weight:800;color:{color_v};line-height:1.2">{titulo_v} '
        f'<span style="font-size:1.15rem;font-weight:600;color:#52514e">· rinde {pct(res["tir"])} al año '
        f'vs. tu costo de oportunidad de {descuento_inv:.1f} %</span></div>'
        f'<div style="font-size:1.05rem;margin-top:6px">{sub}</div></div>'
    )
    st.markdown(html_v.replace("$", "&#36;"), unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio justo estimado", usd_k(aviso["precio_justo_usd"]),
              f"{aviso['descuento_pct']:.0f} % bajo mercado" if aviso["descuento_pct"] > 0 else f"{-aviso['descuento_pct']:.0f} % sobre mercado",
              delta_color="normal" if aviso["descuento_pct"] > 0 else "inverse")
    m2.metric("Pones al inicio", usd_k(res["inversion_inicial"]), help="Cuota inicial + notaría y registros + alcabala")
    m3.metric("Flujo mensual (año 1)", usd(res["flujo_mensual_anio1"]),
              help="Alquiler real menos vacancia, impuestos, predial, seguros y cuota.")
    m4.metric(f"VAN al {descuento_inv:.1f} %", usd_k(res["van"]),
              help=f"Venta neta al año {horizonte}: {usd(res['neto_venta'])} · cash-on-cash año 1: {pct(res['cash_on_cash'])}")

    # ---------- gráficos: a dónde se va el alquiler + flujo por año ----------
    g1, g2 = st.columns(2)
    with g1:
        # Cascada: del alquiler publicado al flujo mensual, paso a paso (un solo eje)
        filas_c, acum = [], 0.0
        for concepto, v in desglose:
            filas_c.append({"concepto": concepto, "inicio": acum, "fin": acum + v, "monto": v,
                            "tipo": "Ingreso" if v > 0 else "Gasto o cuota"})
            acum += v
        filas_c.append({"concepto": "Te queda al mes", "inicio": 0.0, "fin": acum, "monto": acum,
                        "tipo": "Te queda" if acum >= 0 else "Pones de tu bolsillo"})
        dc = pd.DataFrame(filas_c)
        dc["max_x"] = dc[["inicio", "fin"]].max(axis=1)
        # Leyenda solo con los tipos que aparecen (si no, se corta)
        colores_c = {k: v for k, v in {"Ingreso": AZUL, "Gasto o cuota": GRIS, "Te queda": AZUL,
                                       "Pones de tu bolsillo": ROJO}.items() if k in set(dc["tipo"])}
        orden = dc["concepto"].tolist()
        barras = alt.Chart(dc).mark_bar(cornerRadius=3, size=20).encode(
            y=alt.Y("concepto:N", sort=orden, title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False, labelFontSize=12)),
            x=alt.X("inicio:Q", title="US$ por mes (año 1)", axis=alt.Axis(format=",.0f", gridOpacity=0.3)),
            x2="fin:Q",
            color=alt.Color("tipo:N", legend=alt.Legend(title=None, orient="top"),
                            scale=alt.Scale(domain=list(colores_c), range=list(colores_c.values()))),
            tooltip=[alt.Tooltip("concepto:N", title="Concepto"), alt.Tooltip("monto:Q", title="US$ al mes", format=",.0f")],
        )
        textos = alt.Chart(dc).mark_text(align="left", dx=4, fontSize=11, color="#52514e").encode(
            y=alt.Y("concepto:N", sort=orden), x="max_x:Q", text=alt.Text("monto:Q", format=",.0f"),
        )
        st.altair_chart((barras + textos).properties(height=48 * len(dc) + 40, title="¿A dónde se va tu alquiler cada mes?"),
                        use_container_width=True)
    with g2:
        # Solo los años de operación: la inversión inicial y la venta van en las tarjetas,
        # porque en el mismo eje aplastarían los flujos anuales.
        g = tabla_flujo[tabla_flujo["anio"] > 0].assign(
            mensual=lambda d: d["flujo_neto"] / 12,
            tipo=lambda d: d["flujo_neto"].map(lambda v: "Te sobra dinero" if v >= 0 else "Pones de tu bolsillo"),
        )
        colores_f = {k: v for k, v in {"Pones de tu bolsillo": ROJO, "Te sobra dinero": AZUL}.items() if k in set(g["tipo"])}
        chart = alt.Chart(g).mark_bar(cornerRadiusEnd=4, size=22).encode(
            x=alt.X("anio:O", title="Año", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mensual:Q", title="Flujo por mes (US$)", axis=alt.Axis(format=",.0f", grid=True, gridOpacity=0.3)),
            color=alt.Color("tipo:N", scale=alt.Scale(domain=list(colores_f), range=list(colores_f.values())),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("anio:O", title="Año"),
                     alt.Tooltip("mensual:Q", title="Flujo por mes", format=",.0f"),
                     alt.Tooltip("noi:Q", title="Alquiler neto del año", format=",.0f"),
                     alt.Tooltip("servicio_deuda:Q", title="Cuotas del año", format=",.0f")],
        ).properties(height=48 * len(dc) + 40, title="Flujo mensual promedio de cada año")
        cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#52514e", strokeWidth=1).encode(y="y:Q")
        st.altair_chart(chart + cero, use_container_width=True)

    # ---------- informe PDF ----------
    c_pdf, c_tabla = st.columns([1, 2])
    with c_pdf:
        if es_pro:
            st.download_button(
                "📄 Descargar informe PDF", type="primary", use_container_width=True,
                data=generar_informe(aviso, res, desglose, tabla_flujo, p_max,
                                     f"Avisos de InfoCasas del {metricas['fecha_datos']} · tasas del BCRP ({periodo})"),
                file_name=f"DepaRadar_{aviso['distrito'].replace(' ', '_')}_{int(aviso['id'])}.pdf",
                mime="application/pdf",
            )
            st.caption("Para llevar al banco o a la negociación. Incluido en Pro · S/ 19 por informe suelto.")
        else:
            st.button("🔒 Informe PDF (Pro o S/ 19)", disabled=True, use_container_width=True)
    with c_tabla:
        with st.expander("Ver la tabla del flujo de caja"):
            st.dataframe(tabla_flujo.round(0), hide_index=True, use_container_width=True)
