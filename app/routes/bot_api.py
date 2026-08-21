"""API para las apps de los agentes (protegida con X-API-Key)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..bot import db as bot_db
from ..security import verificar_token

router = APIRouter(prefix="/api", dependencies=[Depends(verificar_token)])


class RegistrarIn(BaseModel):
    device_id: str
    nombre: str
    telefono: str = ""


class RespuestaIn(BaseModel):
    tarea_id: int
    datos: dict


@router.post("/agentes/registrar")
def registrar(payload: RegistrarIn):
    if not payload.device_id.strip() or not payload.nombre.strip():
        raise HTTPException(status_code=400, detail="device_id y nombre son obligatorios.")
    bot_db.registrar_agente(
        payload.device_id.strip(),
        payload.nombre.strip(),
        payload.telefono.strip(),
    )
    return {"ok": True}


@router.get("/agentes")
def listar():
    return {"agentes": bot_db.listar_agentes()}


@router.get("/agentes/{device_id}/tareas")
def tareas(device_id: str):
    bot_db.tocar_conexion(device_id)
    return {"tareas": bot_db.tareas_pendientes(device_id)}


@router.post("/agentes/{device_id}/respuesta")
def responder(device_id: str, payload: RespuestaIn):
    if not bot_db.marcar_respondida(payload.tarea_id, payload.datos):
        raise HTTPException(status_code=404, detail="Tarea no encontrada o ya respondida.")
    return {"ok": True}
