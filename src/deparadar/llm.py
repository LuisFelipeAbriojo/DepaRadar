"""Extracción de atributos del texto libre de los avisos con Gemini.

Herramienta del curso: LLMs con salidas estructuradas (sesión 08).
La ficha técnica de InfoCasas no dice si un depa es dúplex, si tiene vista o si
hay que remodelarlo, pero el texto del aviso sí. Le pedimos a Gemini que lo lea
y devuelva un JSON validado con Pydantic.

Para ahorrar tokens y no pasar los límites del tier gratuito:
- mandamos varios avisos por pedido (lotes),
- recortamos descripciones largas,
- guardamos un caché por id: un aviso ya leído no se vuelve a mandar.

Uso:
    uv run python -m deparadar.llm --limite 30     # prueba con 30 avisos
    uv run python -m deparadar.llm                 # todos los pendientes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from enum import Enum

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from deparadar.config import DATA_PROCESSED, ROOT

log = logging.getLogger("deparadar.llm")

CACHE = DATA_PROCESSED / "atributos_llm.csv"
USO = DATA_PROCESSED / "uso_tokens.json"
MODELOS_RESPALDO = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
MAX_CHARS_DESCRIPCION = 1200


class TipoUnidad(str, Enum):
    flat = "flat"
    duplex = "duplex"
    triplex = "triplex"
    penthouse = "penthouse"


class Vista(str, Enum):
    ninguna = "ninguna"
    parque = "parque"
    mar = "mar"
    ciudad = "ciudad"


class AtributosAviso(BaseModel):
    id: int = Field(description="El mismo id que se recibió")
    tipo_unidad: TipoUnidad = Field(description="flat si no se menciona dúplex, tríplex o penthouse")
    vista: Vista = Field(description="Vista principal mencionada; ninguna si no se menciona o es interior")
    area_techada_m2: float | None = Field(description="Área techada/ocupada en m² si el texto la distingue del total; null si no")
    area_libre_m2: float | None = Field(description="m² de terraza, azotea o jardín si se mencionan; null si no")
    requiere_remodelacion: bool = Field(description="true si dice para remodelar, para refaccionar o similar")
    urgencia_venta: bool = Field(description="true si dice ocasión, remate, urge, precio negociable o de oportunidad")
    antiguedad_anios: int | None = Field(description="Años de antigüedad si se menciona; 0 si es de estreno; null si no")
    piso: int | None = Field(description="Número de piso del depa si se menciona; null si no")


class Lote(BaseModel):
    avisos: list[AtributosAviso]


PROMPT = """Eres un analista inmobiliario en Lima. Lee cada aviso y extrae SOLO lo que el texto dice
explícitamente; si algo no se menciona, usa el valor por defecto indicado en el esquema. No inventes.
Devuelve exactamente un objeto por cada aviso, con el mismo id.

Avisos (JSON, uno por línea):
{avisos}"""


def cliente():
    """Cliente de Gemini. Lee la clave de .env (local) o de las variables de entorno (despliegue)."""
    from google import genai

    load_dotenv(ROOT / ".env")
    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta GEMINI_API_KEY: copia .env.example a .env y completa tu clave")
    return genai.Client(api_key=clave)


def _modelos() -> list[str]:
    preferido = os.environ.get("GEMINI_MODEL", MODELOS_RESPALDO[0])
    return [preferido] + [m for m in MODELOS_RESPALDO if m != preferido]


def generar_estructurado(client, prompt: str, esquema: type[BaseModel], reintentos: int = 3):
    """Llama a Gemini con salida JSON validada. Devuelve (objeto, tokens_entrada, tokens_salida, modelo).

    Si un modelo está saturado (503) o con límite (429), espera y prueba el siguiente.
    """
    ultimo_error: Exception | None = None
    for intento in range(reintentos):
        for modelo in _modelos():
            try:
                r = client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config={"response_mime_type": "application/json", "response_schema": esquema, "temperature": 0},
                )
                obj = r.parsed if r.parsed is not None else esquema.model_validate_json(r.text)
                u = r.usage_metadata
                return obj, u.prompt_token_count or 0, u.candidates_token_count or 0, modelo
            except Exception as e:  # noqa: BLE001 - probamos el siguiente modelo
                ultimo_error = e
                log.warning("%s falló (%s), probando otro modelo", modelo, str(e)[:80])
        time.sleep(10 * (intento + 1))
    raise RuntimeError(f"Gemini no respondió: {ultimo_error}")


def _entrada(fila: pd.Series) -> str:
    texto = f"{fila['titulo'] or ''}. {fila['descripcion'] or ''}"[:MAX_CHARS_DESCRIPCION]
    return json.dumps({"id": int(fila["id"]), "texto": texto}, ensure_ascii=False)


def extraer_lote(client, filas: pd.DataFrame) -> tuple[list[AtributosAviso], dict]:
    prompt = PROMPT.format(avisos="\n".join(_entrada(f) for _, f in filas.iterrows()))
    lote, t_in, t_out, modelo = generar_estructurado(client, prompt, Lote)
    pedidos = set(filas["id"].astype(int))
    validos = [a for a in lote.avisos if a.id in pedidos]  # descartamos ids inventados
    return validos, {"tokens_entrada": t_in, "tokens_salida": t_out, "modelo": modelo}


def extraer_pendientes(df: pd.DataFrame, tam_lote: int = 15, pausa: float = 4.0, limite: int | None = None) -> pd.DataFrame:
    """Procesa los avisos que aún no están en el caché y lo actualiza."""
    cache = pd.read_csv(CACHE) if CACHE.exists() else pd.DataFrame(columns=["id"])
    pendientes = df[~df["id"].isin(cache["id"])]
    if limite:
        pendientes = pendientes.head(limite)
    log.info("%d avisos en caché, %d pendientes", len(cache), len(pendientes))

    uso = json.loads(USO.read_text(encoding="utf-8")) if USO.exists() else {"pedidos": 0, "avisos": 0, "tokens_entrada": 0, "tokens_salida": 0}
    client = cliente()
    for i in range(0, len(pendientes), tam_lote):
        filas = pendientes.iloc[i : i + tam_lote]
        try:
            resultados, meta = extraer_lote(client, filas)
        except RuntimeError as e:
            log.error("Lote %d omitido: %s", i // tam_lote, e)
            continue
        nuevos = pd.DataFrame([r.model_dump(mode="json") for r in resultados])
        cache = pd.concat([cache, nuevos], ignore_index=True)
        cache.to_csv(CACHE, index=False, encoding="utf-8")  # guardamos tras cada lote
        uso["pedidos"] += 1
        uso["avisos"] += len(resultados)
        uso["tokens_entrada"] += meta["tokens_entrada"]
        uso["tokens_salida"] += meta["tokens_salida"]
        USO.write_text(json.dumps(uso, indent=2), encoding="utf-8")
        log.info("lote %d: %d/%d avisos (%s, %d+%d tokens)", i // tam_lote + 1, len(resultados), len(filas),
                 meta["modelo"], meta["tokens_entrada"], meta["tokens_salida"])
        time.sleep(pausa)
    return cache


def main() -> None:
    p = argparse.ArgumentParser(description="Extrae atributos del texto de los avisos con Gemini")
    p.add_argument("--limite", type=int, default=None, help="máximo de avisos a procesar (para probar)")
    p.add_argument("--lote", type=int, default=15)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    avisos = pd.concat([pd.read_csv(DATA_PROCESSED / f) for f in ("venta.csv", "alquiler.csv")])
    extraer_pendientes(avisos, tam_lote=args.lote, limite=args.limite)


if __name__ == "__main__":
    main()
