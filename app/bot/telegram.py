"""Bot de Telegram: comandos del dueño y entrega de respuestas de las apps.

El bot responde en el chat (grupo) donde se añadió: el primer `/start` en un
chat registra ese chat como destino (se guarda en `config`; `OWNER_CHAT_ID`
por variable lo fija directamente). Todos los informes — resumen, auditoría,
resumen diario y respuestas tardías — se envían a ese chat.

Mecánica de consulta: un comando crea una tarea por dispositivo (cola en
SQLite). Las apps la contestan cuando hacen su polling (cada 30 min). Un
proceso (ver scheduler.py) entrega las respuestas y, mientras la consulta
sigue abierta, va editando el mismo mensaje con la lista actualizada
(⏳ para las que aún no han respondido, que quedan en cola).
"""
import json
import os
import uuid
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from . import db

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BASE_URL = (
    os.environ.get("BASE_URL", "")
    or (f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}" if os.environ.get("RAILWAY_PUBLIC_DOMAIN") else "")
).strip()

# Consultas activas en memoria: consulta_id -> estado, para ir editando el
# mensaje mientras llegan respuestas. Se pierden al reiniciar el proceso; las
# respuestas posteriores se envían como mensaje independiente (cola intacta).
CONSULTAS: dict[str, "ConsultaActiva"] = {}

application: Application | None = None


class ConsultaActiva:
    def __init__(self, consulta_id: str, chat_id: int, message_id: int,
                 devices: list[str], tipo: str):
        self.consulta_id = consulta_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.devices = set(devices)
        self.tipo = tipo
        self.respuestas: dict[str, dict] = {}
        self.creada_en = datetime.now(timezone.utc)

    def agregar(self, device_id: str, datos: dict) -> None:
        self.respuestas[device_id] = datos

    def completa(self) -> bool:
        return self.devices <= set(self.respuestas)

    def texto(self) -> str:
        cabecera = {
            "consulta": "📊 Resumen de agentes",
            "auditoria": "🔍 Auditoría de agente",
            "resumen": "🌙 Resumen diario",
        }.get(self.tipo, "📊 Consulta")
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        lineas = [f"{cabecera} — {fecha}"]
        for d in sorted(self.devices):
            ag = db.obtener_agente(d)
            nombre = ag["nombre"] if ag else d
            tel = (ag or {}).get("telefono", "")
            prefijo = "⛔ " if ag and not ag.get("habilitada", True) else ""
            if d in self.respuestas:
                r = self.respuestas[d]
                if self.tipo == "auditoria":
                    ultima = (ag or {}).get("ultima_conexion") or "—"
                    lineas.append(
                        f"• {prefijo}{nombre} ({tel}): {r.get('hoy', 0)} hoy · {r.get('total', 0)} total"
                        f" · conexión {ultima[:16]}"
                    )
                else:
                    lineas.append(
                        f"• {prefijo}{nombre} ({tel}): {r.get('hoy', 0)} hoy · {r.get('total', 0)} total"
                    )
            else:
                lineas.append(f"• {prefijo}{nombre}: ⏳ sin conexión (en cola)")
        return "\n".join(lineas)


def es_chat_destino(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    destino = db.get_config("chat_destino") or OWNER_CHAT_ID
    return bool(destino) and str(chat_id) == destino


def verificar_secret(header: str | None) -> bool:
    """Valida la cabecera del webhook. Sin WEBHOOK_SECRET no se exige."""
    if not WEBHOOK_SECRET:
        return True
    return header == WEBHOOK_SECRET


# ---------------- comandos ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat is None:
        return
    if not db.get_config("chat_destino") and not OWNER_CHAT_ID:
        db.set_config("chat_destino", str(chat.id))
        await update.effective_message.reply_text(
            "✅ Bot activo en este chat. Los informes se enviarán aquí.\n"
            "Comandos: /agentes · /resumen · /consulta <nombre o teléfono>"
        )
    else:
        await update.effective_message.reply_text(
            "Bot activo.\nComandos: /agentes · /resumen · /consulta <nombre o teléfono>"
        )


async def cmd_agentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    agentes = db.listar_agentes()
    if not agentes:
        await update.effective_message.reply_text("Todavía no hay agentes registrados.")
        return
    lineas = ["📋 Agentes registrados:"]
    for a in agentes:
        ultima = (a.get("ultima_conexion") or "—")[:16]
        estado = "✅" if a.get("habilitada", True) else "⛔"
        lineas.append(f"{estado} {a['nombre']} ({a['telefono']}) · conexión {ultima}")
    await update.effective_message.reply_text("\n".join(lineas))


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    if not db.listar_agentes():
        await update.effective_message.reply_text("Todavía no hay agentes registrados.")
        return
    await _iniciar_consulta(update.effective_chat.id, "consulta")


async def cmd_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    termino = (context.args[0] if context.args else "").strip()
    if not termino:
        await update.effective_message.reply_text("Uso: /consulta <nombre o teléfono>")
        return
    candidatos = db.buscar_agente(termino)
    if not candidatos:
        lista = "\n".join(f"• {a['nombre']} ({a['telefono']})" for a in db.listar_agentes())
        await update.effective_message.reply_text(
            f"No encontré a «{termino}». Agentes registrados:\n{lista or '— ninguno —'}"
        )
        return
    if len(candidatos) > 1:
        lista = "\n".join(f"• {a['nombre']} ({a['telefono']})" for a in candidatos)
        await update.effective_message.reply_text(
            f"Hay varios agentes que coinciden con «{termino}». "
            f"Usa el teléfono exacto:\n{lista}"
        )
        return
    await _iniciar_consulta(update.effective_chat.id, "auditoria", [candidatos[0]["device_id"]])


def _resolver_agente(termino: str) -> tuple[dict | None, str | None]:
    """Devuelve (agente, error) buscando por nombre o teléfono exacto."""
    candidatos = db.buscar_agente(termino)
    if not candidatos:
        return None, f"No encontré a «{termino}»."
    if len(candidatos) > 1:
        lista = "\n".join(f"• {a['nombre']} ({a['telefono']})" for a in candidatos)
        return None, f"Hay varios agentes que coinciden. Usa el teléfono exacto:\n{lista}"
    return candidatos[0], None


async def cmd_deshabilitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    termino = (context.args[0] if context.args else "").strip()
    if not termino:
        await update.effective_message.reply_text("Uso: /deshabilitar <nombre o teléfono>")
        return
    agente, error = _resolver_agente(termino)
    if error:
        await update.effective_message.reply_text(error)
        return
    db.set_habilitada(agente["device_id"], False)
    await update.effective_message.reply_text(
        f"⛔ App deshabilitada para {agente['nombre']} ({agente['telefono']})."
    )


async def cmd_habilitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    termino = (context.args[0] if context.args else "").strip()
    if not termino:
        await update.effective_message.reply_text("Uso: /habilitar <nombre o teléfono>")
        return
    agente, error = _resolver_agente(termino)
    if error:
        await update.effective_message.reply_text(error)
        return
    db.set_habilitada(agente["device_id"], True)
    await update.effective_message.reply_text(
        f"✅ App habilitada para {agente['nombre']} ({agente['telefono']})."
    )


async def cmd_deshabilitar_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    n = db.set_habilitada_todos(False)
    await update.effective_message.reply_text(f"⛔ Se deshabilitaron {n} app(s).")


async def cmd_habilitar_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_chat_destino(update.effective_chat.id):
        await update.effective_message.reply_text("⛔ No autorizado.")
        return
    n = db.set_habilitada_todos(True)
    await update.effective_message.reply_text(f"✅ Se habilitaron {n} app(s).")


# ---------------- consultas ----------------

async def _iniciar_consulta(chat_id: int, tipo: str, devices: list[str] | None = None) -> None:
    global application
    if application is None:
        return
    targets = devices if devices is not None else [a["device_id"] for a in db.listar_agentes()]
    if not targets:
        return
    consulta_id = uuid.uuid4().hex
    db.crear_tareas(consulta_id, tipo, targets)
    inicial = {
        "consulta": f"📊 Consultando a {len(targets)} agente(s)… te informo a medida que respondan.",
        "auditoria": f"🔍 Consultando a {len(targets)} agente(s)…",
        "resumen": f"🌙 Pidiendo resumen diario a {len(targets)} agente(s)…",
    }[tipo]
    msg = await application.bot.send_message(chat_id, inicial)
    CONSULTAS[consulta_id] = ConsultaActiva(consulta_id, chat_id, msg.message_id, targets, tipo)


async def iniciar_consulta_diaria() -> None:
    """Resumen diario automático (lo dispara el scheduler a la hora configurada)."""
    if application is None:
        return
    destino = db.get_config("chat_destino") or OWNER_CHAT_ID
    if not destino:
        return
    if not db.listar_agentes():
        return
    await _iniciar_consulta(int(destino), "resumen")


# ---------------- entrega de respuestas ----------------

async def entregar_pendientes() -> None:
    """Lee tareas respondidas y las entrega (edita el mensaje de su consulta)."""
    if application is None:
        return
    for tarea in db.tareas_entregables():
        try:
            datos = json.loads(tarea["respuesta"])
        except (TypeError, ValueError):
            datos = {}
        consulta = CONSULTAS.get(tarea["consulta_id"])
        if consulta is not None:
            consulta.agregar(tarea["device_id"], datos)
            try:
                await application.bot.edit_message_text(
                    consulta.texto(),
                    chat_id=consulta.chat_id,
                    message_id=consulta.message_id,
                )
            except Exception:
                # Mensaje editado/borrado (límite de 48 h de Telegram): se
                # cierra la consulta en memoria y se envía como mensaje suelto.
                CONSULTAS.pop(tarea["consulta_id"], None)
                await _enviar_respuesta_suelta(tarea, datos)
            else:
                if consulta.completa():
                    CONSULTAS.pop(tarea["consulta_id"], None)
        else:
            await _enviar_respuesta_suelta(tarea, datos)
        db.marcar_entregada(tarea["id"])


async def _enviar_respuesta_suelta(tarea: dict, datos: dict) -> None:
    if application is None:
        return
    destino = db.get_config("chat_destino") or OWNER_CHAT_ID
    if not destino:
        return
    ag = db.obtener_agente(tarea["device_id"])
    nombre = ag["nombre"] if ag else tarea["device_id"]
    tel = (ag or {}).get("telefono", "")
    await application.bot.send_message(
        int(destino),
        f"📊 {nombre} ({tel}): {datos.get('hoy', 0)} hoy · {datos.get('total', 0)} total",
    )


# ---------------- ciclo de vida ----------------

def iniciar() -> None:
    """Crea la aplicación de PTB. Sin TELEGRAM_BOT_TOKEN no hace nada."""
    global application
    if not TOKEN:
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("agentes", cmd_agentes))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("consulta", cmd_consulta))
    app.add_handler(CommandHandler("deshabilitar", cmd_deshabilitar))
    app.add_handler(CommandHandler("habilitar", cmd_habilitar))
    app.add_handler(CommandHandler("deshabilitar_todos", cmd_deshabilitar_todos))
    app.add_handler(CommandHandler("habilitar_todos", cmd_habilitar_todos))
    application = app


async def arrancar() -> None:
    if application is None:
        return
    await application.initialize()
    await application.start()
    if BASE_URL:
        url = BASE_URL.rstrip("/") + "/webhook/telegram"
        await application.bot.set_webhook(url, secret_token=WEBHOOK_SECRET or None)
        print(f"[bot] Webhook configurado en {url}", flush=True)
    else:
        print("[bot] Sin BASE_URL: solo API (sin webhook de Telegram)", flush=True)


async def apagar() -> None:
    if application is None:
        return
    await application.stop()
    await application.shutdown()


async def procesar_update(datos: dict) -> None:
    if application is None:
        return
    from telegram import Update
    update = Update.de_json(datos, application.bot)
    if update is not None:
        await application.process_update(update)
