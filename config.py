"""
config.py — Configuración centralizada
=======================================
Todas las variables de entorno se definen aquí.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Seguridad ──────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ── Uploads ────────────────────────────────────────────
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "data/uploads")
    ALLOWED_EXTENSIONS: set = {"csv", "geojson", "json"}
    # 10 MB por defecto (GeoJSONs pueden ser más pesados que CSVs)
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))

    # ── Flask ──────────────────────────────────────────────
    DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"
