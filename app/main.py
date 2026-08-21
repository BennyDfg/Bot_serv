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

load_dotenv()  # .env local (gitignored); en Railway se usan variables reales

from .bot import db as bot_db
from .bot import scheduler, telegram
from .routes import bot_api

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bot_db.inicializar()
    telegram.iniciar()
    await telegram.arrancar()
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
    await telegram.procesar_update(await request.json())
    return Response(status_code=200)


@app.get("/")
def raiz():
    return {"ok": True, "bot": bool(TELEGRAM_BOT_TOKEN), "agentes": bot_db.contar_agentes()}
