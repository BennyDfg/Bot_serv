"""Protección de la API para las apps de los agentes (X-API-Key)."""
import os

from fastapi import Header, HTTPException

API_TOKEN = os.environ.get("API_TOKEN", "").strip()


def verificar_token(x_api_key: str | None = Header(default=None)) -> None:
    if API_TOKEN and x_api_key != API_TOKEN:
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")
