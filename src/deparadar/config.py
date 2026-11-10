"""Configuración general de DepaRadar."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"

# Distritos de Lima Moderna: slug de InfoCasas -> nombre para mostrar
DISTRITOS = {
    "miraflores": "Miraflores",
    "san-isidro": "San Isidro",
    "santiago-de-surco": "Santiago de Surco",
    "san-borja": "San Borja",
    "barranco": "Barranco",
    "jesus-maria": "Jesús María",
    "lince": "Lince",
    "magdalena-del-mar": "Magdalena del Mar",
    "pueblo-libre": "Pueblo Libre",
    "surquillo": "Surquillo",
}

OPERACIONES = ("venta", "alquiler")
