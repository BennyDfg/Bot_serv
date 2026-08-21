"""Arranque del bot en modo POLLING (sin URL pública).

Útil para probar en local o como fallback: el bot se conecta él solo a
Telegram (getUpdates) en vez de recibir webhooks. Incluye el planificador
(entrega de respuestas cada 20 s + resumen diario).

Uso:
    python -m app.bot.polling

No debe ejecutarse a la vez que el modo webhook (FastAPI) con el mismo
token: Telegram solo permite un consumidor (getUpdates) por bot.
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()  # .env local (gitignored); debe cargarse ANTES de importar telegram

from . import db, scheduler, telegram


async def main() -> None:
    db.inicializar()
    telegram.iniciar()
    if telegram.application is None:
        print("[bot] TELEGRAM_BOT_TOKEN vacío — no se puede arrancar en modo polling.", flush=True)
        return

    app = telegram.application
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    sched = scheduler.crear()
    sched.start()

    print("[bot] Modo polling activo. Ctrl+C para detener.", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        sched.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
