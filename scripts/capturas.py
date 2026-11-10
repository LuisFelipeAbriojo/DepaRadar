"""Genera las capturas del README a partir de la app corriendo en local.

    uv run streamlit run app/streamlit_app.py          # en otra terminal
    uv run --with playwright python scripts/capturas.py

Usa el navegador Edge ya instalado (channel="msedge"): no descarga navegadores.
La captura del analista hace una pregunta real a Gemini (~US$0.002).
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
SALIDA = Path(__file__).resolve().parents[1] / "docs" / "img"


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge")
        page = nav.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.goto(URL)
        page.get_by_text("Avisos analizados").wait_for(timeout=90_000)
        page.wait_for_timeout(4000)  # deja cargar el mapa
        page.screenshot(path=SALIDA / "01-radar.png")

        page.get_by_text("Precio justo estimado").scroll_into_view_if_needed()
        page.get_by_role("heading", name="📊").first.scroll_into_view_if_needed()
        page.mouse.wheel(0, -40)
        page.wait_for_timeout(1500)
        page.screenshot(path=SALIDA / "02-evaluador.png")

        page.mouse.wheel(0, -5000)
        page.get_by_role("tab", name="Analista IA").click()
        page.get_by_role("button", name="Búscame depas en Surco").click()
        page.get_by_text("Preguntas este mes").wait_for(timeout=90_000)  # aparece tras el redibujo final
        page.wait_for_timeout(2500)
        page.get_by_text("Herramientas:").scroll_into_view_if_needed()
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(800)
        page.screenshot(path=SALIDA / "03-analista.png")
        nav.close()
    print("Capturas en", SALIDA)


if __name__ == "__main__":
    main()
