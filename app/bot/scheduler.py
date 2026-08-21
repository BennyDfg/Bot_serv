"""Planificador: resumen diario automático + entrega de respuestas.

- Resumen diario: a las `RESUMEN_HORA` (por defecto 22:30, zona `TZ`)
  crea una consulta tipo 'resumen' para todos los agentes; las apps la
  responden cuando hacen su polling y el bot va entregando los resultados.
- Entrega: cada 20 s lee las tareas respondidas y actualiza los mensajes.
"""
import os
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import telegram

ZONA_CONFIGURADA = os.environ.get("TZ", "America/Havana")


def _zona_valida() -> str:
    try:
        ZoneInfo(ZONA_CONFIGURADA)
        return ZONA_CONFIGURADA
    except Exception:
        return "UTC"


def crear() -> AsyncIOScheduler:
    zona = _zona_valida()
    s = AsyncIOScheduler(timezone=zona)

    hora = os.environ.get("RESUMEN_HORA", "22:30")
    try:
        hh, mm = hora.split(":")
        s.add_job(
            telegram.iniciar_consulta_diaria,
            CronTrigger(hour=int(hh), minute=int(mm), timezone=zona),
            id="resumen_diario",
            coalesce=True,
            max_instances=1,
        )
    except ValueError:
        print(f"[scheduler] RESUMEN_HORA inválido («{hora}»); resumen diario desactivado", flush=True)

    s.add_job(
        telegram.entregar_pendientes,
        "interval",
        seconds=20,
        id="entrega_respuestas",
        coalesce=True,
        max_instances=1,
    )
    return s
