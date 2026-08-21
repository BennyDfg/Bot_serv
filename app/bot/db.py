"""Persistencia de la red de agentes (SQLite).

Un solo archivo .db — sin proceso de servidor que mantener. Backup = copiar
el archivo. Nota: en Railway el disco es efímero (se pierde al redeployar);
las apps se re-registran solas cada 30 min, así que la tabla de agentes se
auto-recupera. Las tareas pendientes de una app apagada se pierden si se
redeploya el servicio — se resuelve repitiendo el comando.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

RUTA_DB = Path(__file__).resolve().parent.parent.parent / "data" / "bot.db"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conexion():
    con = sqlite3.connect(RUTA_DB)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def inicializar() -> None:
    RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
    with _conexion() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""
            CREATE TABLE IF NOT EXISTS agentes (
                device_id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                ultima_conexion TEXT,
                creado_en TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS tareas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                consulta_id TEXT NOT NULL,
                tipo TEXT NOT NULL,
                device_id TEXT NOT NULL,
                creada_en TEXT DEFAULT CURRENT_TIMESTAMP,
                respondida_en TEXT,
                entregada INTEGER DEFAULT 0,
                respuesta TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT)
        """)
        con.commit()


# ---------------- agentes ----------------

def registrar_agente(device_id: str, nombre: str, telefono: str) -> None:
    """Alta/actualización del agente. Cada registro marca su última conexión."""
    with _conexion() as con:
        con.execute("""
            INSERT INTO agentes (device_id, nombre, telefono, ultima_conexion)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                nombre = excluded.nombre,
                telefono = excluded.telefono,
                ultima_conexion = excluded.ultima_conexion
        """, (device_id, nombre, telefono, _ahora()))
        con.commit()


def tocar_conexion(device_id: str) -> None:
    with _conexion() as con:
        con.execute("UPDATE agentes SET ultima_conexion = ? WHERE device_id = ?",
                    (_ahora(), device_id))
        con.commit()


def listar_agentes() -> list[dict]:
    with _conexion() as con:
        filas = con.execute(
            "SELECT device_id, nombre, telefono, ultima_conexion, creado_en "
            "FROM agentes ORDER BY nombre COLLATE NOCASE"
        ).fetchall()
    return [dict(f) for f in filas]


def obtener_agente(device_id: str) -> dict | None:
    with _conexion() as con:
        fila = con.execute(
            "SELECT device_id, nombre, telefono, ultima_conexion "
            "FROM agentes WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    return dict(fila) if fila else None


def buscar_agente(termino: str) -> list[dict]:
    """Búsqueda para /consulta: por nombre o teléfono, sin distinguir mayúsculas."""
    t = termino.strip().lower()
    t_sin_espacios = t.replace(" ", "")
    with _conexion() as con:
        filas = con.execute(
            "SELECT device_id, nombre, telefono, ultima_conexion FROM agentes "
            "WHERE LOWER(nombre) = ? OR REPLACE(telefono, ' ', '') = ?",
            (t, t_sin_espacios),
        ).fetchall()
    return [dict(f) for f in filas]


def contar_agentes() -> int:
    with _conexion() as con:
        return con.execute("SELECT COUNT(*) AS n FROM agentes").fetchone()["n"]


# ---------------- tareas (cola de consultas) ----------------

def crear_tareas(consulta_id: str, tipo: str, devices: list[str]) -> None:
    """Crea una tarea por dispositivo (queda en cola hasta que responda)."""
    with _conexion() as con:
        con.executemany(
            "INSERT INTO tareas (consulta_id, tipo, device_id) VALUES (?, ?, ?)",
            [(consulta_id, tipo, d) for d in devices],
        )
        con.commit()


def tareas_pendientes(device_id: str) -> list[dict]:
    with _conexion() as con:
        filas = con.execute(
            "SELECT id, consulta_id, tipo FROM tareas "
            "WHERE device_id = ? AND respondida_en IS NULL ORDER BY id",
            (device_id,),
        ).fetchall()
    return [dict(f) for f in filas]


def marcar_respondida(tarea_id: int, datos: dict) -> bool:
    """Guarda la respuesta. Devuelve False si la tarea no existe o ya respondió."""
    with _conexion() as con:
        cur = con.execute(
            "UPDATE tareas SET respondida_en = ?, respuesta = ? "
            "WHERE id = ? AND respondida_en IS NULL",
            (_ahora(), json.dumps(datos, ensure_ascii=False), tarea_id),
        )
        con.commit()
        return cur.rowcount > 0


def tareas_entregables() -> list[dict]:
    """Tareas respondidas pero aún no enviadas al chat de Telegram."""
    with _conexion() as con:
        filas = con.execute(
            "SELECT id, consulta_id, tipo, device_id, respuesta FROM tareas "
            "WHERE respondida_en IS NOT NULL AND entregada = 0 ORDER BY id"
        ).fetchall()
    return [dict(f) for f in filas]


def marcar_entregada(tarea_id: int) -> None:
    with _conexion() as con:
        con.execute("UPDATE tareas SET entregada = 1 WHERE id = ?", (tarea_id,))
        con.commit()


# ---------------- config ----------------

def get_config(k: str) -> str | None:
    with _conexion() as con:
        fila = con.execute("SELECT v FROM config WHERE k = ?", (k,)).fetchone()
    return fila["v"] if fila else None


def set_config(k: str, v: str) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT INTO config (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (k, v),
        )
        con.commit()
