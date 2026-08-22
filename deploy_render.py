#!/usr/bin/env python3
"""Crea (o actualiza) el servicio Bot_serv en Render desde la línea de comandos.

Qué automatiza:
  - Crea un Web Service "bot-serv" (plan free, runtime Python) apuntando a
    https://github.com/BennyDfg/Bot_serv (rama main).
  - Copia TELEGRAM_BOT_TOKEN y API_TOKEN desde tu `.env` local como variables
    de entorno del servicio (nunca se escriben en el repo).
  - Genera WEBHOOK_SECRET automáticamente y fija RESUMEN_HORA/TZ.
  - Si el servicio ya existe, solo actualiza sus variables de entorno.

Qué NO puede hacer (lo haces tú una vez, en el navegador):
  - Conectar tu cuenta de GitHub a Render (una OAuth en el dashboard).
  - Generar la API key de Render.

Uso:
  1. Render Dashboard → Account Settings → API Keys → Create API Key.
  2. export RENDER_API_KEY=rnd_...        (Windows: set RENDER_API_KEY=rnd_...)
  3. python deploy_render.py
     (o: python deploy_render.py --owner usr-xxx  si tienes varios workspaces)
"""

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

API_BASE = "https://api.render.com/v1"
NOMBRE = "bot-serv"
REPO = "https://github.com/BennyDfg/Bot_serv"
RAMA = "main"
REGION = "virginia"


def _pedir(ruta: str, key: str, method: str = "GET", body=None) -> dict:
    """Petición HTTP a la API de Render y parseo del JSON (o error claro)."""
    req = urllib.request.Request(
        API_BASE + ruta,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")
        print(f"[error] {method} {ruta} → HTTP {e.code}: {detalle}", file=sys.stderr)
        raise SystemExit(1)


def _owner_id(key: str, owner: str | None) -> str:
    if owner:
        return owner
    datos = _pedir("/owners", key)
    owners = datos if isinstance(datos, list) else datos.get("data", [])
    if not owners:
        print("[error] No hay workspaces en tu cuenta de Render.", file=sys.stderr)
        raise SystemExit(1)
    return owners[0]["owner"]["id"] if "owner" in owners[0] else owners[0]["id"]


def _servicio_existente(key: str, owner_id: str) -> dict | None:
    datos = _pedir(
        f"/services?name={NOMBRE}&type=web_service&limit=20", key
    )
    servicios = datos if isinstance(datos, list) else datos.get("data", [])
    for s in servicios:
        if s.get("name") == NOMBRE:
            return s
    return None


def _variables(env: dict) -> list[dict]:
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    api_token = (env.get("API_TOKEN") or "").strip()
    if not token or not api_token:
        print(
            "[error] Falta TELEGRAM_BOT_TOKEN o API_TOKEN en .env. Rellénalos y reintenta.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    variables = [
        {"key": "TELEGRAM_BOT_TOKEN", "value": token},
        {"key": "API_TOKEN", "value": api_token},
        # token_urlsafe usa el alfabeto base64url (A-Z a-z 0-9 - _), que es
        # exactamente lo que Telegram admite para el secret_token del webhook.
        {"key": "WEBHOOK_SECRET", "value": secrets.token_urlsafe(32)},
        {"key": "RESUMEN_HORA", "value": env.get("RESUMEN_HORA", "22:30")},
        {"key": "TZ", "value": env.get("TZ", "America/Havana")},
    ]
    for clave in ("OWNER_CHAT_ID", "DATABASE_URL", "BASE_URL"):
        valor = (env.get(clave) or "").strip()
        if valor:
            variables.append({"key": clave, "value": valor})
    return variables


def main() -> None:
    parser = argparse.ArgumentParser(description="Despliega Bot_serv en Render.")
    parser.add_argument("--owner", help="ID del workspace (usr-xxx) si hay varios")
    parser.add_argument("--name", default=NOMBRE, help="Nombre del servicio")
    parser.add_argument("--repo", default=REPO, help="URL del repo en GitHub")
    args = parser.parse_args()

    load_dotenv()  # carga .env local (token de Telegram y API_TOKEN)
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if not key:
        print(
            "[error] Define RENDER_API_KEY (Render → Account Settings → API Keys).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    owner_id = _owner_id(key, args.owner)
    variables = _variables(os.environ)
    existente = _servicio_existente(key, owner_id)

    if existente:
        sid = existente["service"]["id"] if "service" in existente else existente["id"]
        _pedir(f"/services/{sid}/env-vars", key, method="PUT", body=variables)
        url = f"https://{NOMBRE}.onrender.com"
        print(f"[ok] Servicio '{NOMBRE}' ya existía → variables actualizadas. URL: {url}")
        return

    body = {
        "type": "web_service",
        "name": args.name,
        "ownerId": owner_id,
        "repo": args.repo,
        "branch": RAMA,
        "autoDeploy": "yes",
        "envVars": variables,
        "serviceDetails": {
            "runtime": "python",
            "plan": "free",
            "region": REGION,
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            },
        },
    }
    _pedir("/services", key, method="POST", body=body)
    print(f"[ok] Servicio '{args.name}' creado en Render (plan free).")
    print(f"     URL: https://{args.name}.onrender.com")
    print("     Añade el bot al grupo de Telegram y escribe /start.")


if __name__ == "__main__":
    main()
