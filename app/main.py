"""Bot_serv — red de agentes + bot de Telegram.

Arranque local:
    uvicorn app.main:app --reload --port 8000

Sin TELEGRAM_BOT_TOKEN la parte de Telegram se desactiva y la API para las
apps sigue funcionando (útil para pruebas locales).
"""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

load_dotenv()  # .env local (gitignored); en Railway se usan variables reales

from .bot import db as bot_db
from .bot import scheduler, telegram
from .routes import bot_api

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Un fallo al inicializar la DB o el webhook de Telegram no debe impedir
    # que la API levante: se registra y se sigue (antes, una excepción aquí
    # mataba el arranque y Railway reiniciaba el servicio en bucle).
    try:
        bot_db.inicializar()
    except Exception as e:
        print(f"[startup] Error inicializando la base de datos: {e}", flush=True)

    telegram.iniciar()
    try:
        await telegram.arrancar()
    except Exception as e:
        print(f"[startup] Error arrancando Telegram (la API sigue activa): {e}", flush=True)

    sched = scheduler.crear()
    sched.start()
    app.state.scheduler = sched
    try:
        yield
    finally:
        sched.shutdown(wait=False)
        await telegram.apagar()


app = FastAPI(title="Bot_serv — Red de agentes", lifespan=lifespan)

app.include_router(bot_api.router)


@app.post("/webhook/telegram")
async def webhook_telegram(request: Request):
    # Si WEBHOOK_SECRET está definido, solo se aceptan updates que lo traigan
    # en la cabecera X-Telegram-Bot-Api-Secret-Token (evita updates falsos).
    if not telegram.verificar_secret(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    ):
        return Response(status_code=403)
    await telegram.procesar_update(await request.json())
    return Response(status_code=200)


@app.get("/health")
def health():
    """Healthcheck para Railway: 200 si la base de datos responde."""
    try:
        agentes = bot_db.contar_agentes()
        return {"ok": True, "bot": bool(TELEGRAM_BOT_TOKEN), "agentes": agentes}
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False})


@app.get("/")
def raiz():
    return {"ok": True, "bot": bool(TELEGRAM_BOT_TOKEN), "agentes": bot_db.contar_agentes()}
