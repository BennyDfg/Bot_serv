"""Persistencia de la red de agentes.

- En local / desarrollo: SQLite (un solo archivo `data/bot.db`, sin proceso
  que mantener).
- En Railway / producción: Postgres, configurado con la variable
  `DATABASE_URL` (p. ej. `postgresql+psycopg://usuario:clave@host:5432/db`).

El interfaz de funciones (`registrar_agente`, `tareas_pendientes`,
`marcar_respondida`, `get_config`, ...) no cambia, así que `telegram.py` y
`routes/` funcionan igual en ambos motores.

Cada agente tiene una columna `habilitada` (1/0) que decide si su app puede
usarse. El dueño la cambia desde el bot con `/deshabilitar`, `/habilitar`,
`/deshabilitar_todos` y `/habilitar_todos`; la app la consulta en su polling.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

RUTA_DB = Path(__file__).resolve().parent.parent.parent / "data" / "bot.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_engine = None
_engine_url = None


def _url_de_engine() -> str:
    """URL de conexión actual: Postgres si hay DATABASE_URL, si no SQLite."""
    return DATABASE_URL or f"sqlite:///{RUTA_DB}"


def _crear_engine(url: str):
    if url.startswith("sqlite"):
        # NullPool = conexión nueva por operación (como el sqlite3 original),
        # evita problemas de hilos/conexiones compartidas en FastAPI.
        return create_engine(
            url,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
    return create_engine(url, pool_pre_ping=True)


def _engine_actual():
    """Engine cacheado; se reconstruye si cambia la URL (p. ej. en tests)."""
    global _engine, _engine_url
    url = _url_de_engine()
    if _engine is None or _engine_url != url:
        if _engine is not None:
            _engine.dispose()
        _engine = _crear_engine(url)
        _engine_url = url
    return _engine


@contextmanager
def _conexion():
    with _engine_actual().begin() as con:
        yield con


def _es_sqlite(con) -> bool:
    return con.dialect.name == "sqlite"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _con_bool(fila) -> dict:
    """Convierte una fila SQL a dict, con `habilitada` como bool."""
    d = dict(fila._mapping)
    if "habilitada" in d:
        d["habilitada"] = bool(d["habilitada"])
    return d


def ping() -> bool:
    """Comprobación ligera de conexión para el healthcheck."""
    try:
        with _conexion() as con:
            con.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def inicializar() -> None:
    if not DATABASE_URL:
        RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
    with _conexion() as con:
        if _es_sqlite(con):
            con.execute(text("PRAGMA journal_mode=WAL"))

        con.execute(text(
            """
            CREATE TABLE IF NOT EXISTS agentes (
                device_id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                ultima_conexion TEXT,
                creado_en TEXT,
                habilitada INTEGER NOT NULL DEFAULT 1
            )
            """
        ))

        # El id autoincremental cambia de sintaxis entre SQLite y Postgres.
        if _es_sqlite(con):
            con.execute(text(
                """
                CREATE TABLE IF NOT EXISTS tareas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    consulta_id TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    creada_en TEXT,
                    respondida_en TEXT,
                    entregada INTEGER NOT NULL DEFAULT 0,
                    respuesta TEXT
                )
                """
            ))
        else:
            con.execute(text(
                """
                CREATE TABLE IF NOT EXISTS tareas (
                    id BIGSERIAL PRIMARY KEY,
                    consulta_id TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    creada_en TEXT,
                    respondida_en TEXT,
                    entregada INTEGER NOT NULL DEFAULT 0,
                    respuesta TEXT
                )
                """
            ))

        con.execute(text(
            """
            CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT)
            """
        ))
        _migrar(con)


def _migrar(con) -> None:
    """Añade columnas nuevas a bases creadas antes de que existieran."""
    if _es_sqlite(con):
        columnas = {
            fila[1]
            for fila in con.execute(text("PRAGMA table_info(agentes)")).fetchall()
        }
        if "habilitada" not in columnas:
            con.execute(text(
                "ALTER TABLE agentes ADD COLUMN habilitada INTEGER NOT NULL DEFAULT 1"
            ))
    else:
        con.execute(text(
            "ALTER TABLE agentes ADD COLUMN IF NOT EXISTS habilitada INTEGER NOT NULL DEFAULT 1"
        ))


# ---------------- agentes ----------------

def registrar_agente(device_id: str, nombre: str, telefono: str) -> None:
    """Alta/actualización del agente. Cada registro marca su última conexión.

    El `habilitada` NO se toca en el re-registro: una app deshabilitada no
    puede "desbloquearse" simplemente volviendo a registrarse.
    """
    ahora = _ahora()
    with _conexion() as con:
        con.execute(text(
            """
            INSERT INTO agentes
                (device_id, nombre, telefono, ultima_conexion, creado_en, habilitada)
            VALUES (:device_id, :nombre, :telefono, :ahora, :ahora, 1)
            ON CONFLICT(device_id) DO UPDATE SET
                nombre = excluded.nombre,
                telefono = excluded.telefono,
                ultima_conexion = excluded.ultima_conexion
            """
        ), {"device_id": device_id, "nombre": nombre, "telefono": telefono, "ahora": ahora})


def tocar_conexion(device_id: str) -> None:
    with _conexion() as con:
        con.execute(
            text("UPDATE agentes SET ultima_conexion = :ahora WHERE device_id = :d"),
            {"ahora": _ahora(), "d": device_id},
        )


def listar_agentes() -> list[dict]:
    with _conexion() as con:
        filas = con.execute(text(
            "SELECT device_id, nombre, telefono, ultima_conexion, creado_en, habilitada "
            "FROM agentes ORDER BY LOWER(nombre)"
        )).fetchall()
    return [_con_bool(f) for f in filas]


def obtener_agente(device_id: str) -> dict | None:
    with _conexion() as con:
        fila = con.execute(text(
            "SELECT device_id, nombre, telefono, ultima_conexion, habilitada "
            "FROM agentes WHERE device_id = :d"
        ), {"d": device_id}).first()
    return _con_bool(fila) if fila else None


def buscar_agente(termino: str) -> list[dict]:
    """Búsqueda para /consulta, /deshabilitar y /habilitar: nombre o teléfono."""
    t = termino.strip().lower()
    t_sin_espacios = t.replace(" ", "")
    with _conexion() as con:
        filas = con.execute(text(
            "SELECT device_id, nombre, telefono, ultima_conexion, habilitada "
            "FROM agentes "
            "WHERE LOWER(nombre) = :t OR REPLACE(telefono, ' ', '') = :ts"
        ), {"t": t, "ts": t_sin_espacios}).fetchall()
    return [_con_bool(f) for f in filas]


def es_habilitada(device_id: str) -> bool:
    with _conexion() as con:
        fila = con.execute(text(
            "SELECT habilitada FROM agentes WHERE device_id = :d"
        ), {"d": device_id}).mappings().first()
    return bool(fila["habilitada"]) if fila else False


def set_habilitada(device_id: str, habilitada: bool) -> bool:
    """Habilita/deshabilita un agente. Devuelve False si no existe."""
    with _conexion() as con:
        result = con.execute(
            text("UPDATE agentes SET habilitada = :h WHERE device_id = :d"),
            {"h": 1 if habilitada else 0, "d": device_id},
        )
    return result.rowcount > 0


def set_habilitada_todos(habilitada: bool) -> int:
    """Habilita/deshabilita a TODOS los agentes. Devuelve cuántos afectó."""
    with _conexion() as con:
        result = con.execute(
            text("UPDATE agentes SET habilitada = :h"),
            {"h": 1 if habilitada else 0},
        )
    return result.rowcount


def contar_agentes() -> int:
    with _conexion() as con:
        return con.execute(text("SELECT COUNT(*) AS n FROM agentes")).mappings().first()["n"]


# ---------------- tareas (cola de consultas) ----------------

def crear_tareas(consulta_id: str, tipo: str, devices: list[str]) -> None:
    """Crea una tarea por dispositivo (queda en cola hasta que responda)."""
    ahora = _ahora()
    with _conexion() as con:
        con.execute(
            text(
                "INSERT INTO tareas (consulta_id, tipo, device_id, creada_en) "
                "VALUES (:consulta_id, :tipo, :device_id, :creada_en)"
            ),
            [
                {"consulta_id": consulta_id, "tipo": tipo, "device_id": d, "creada_en": ahora}
                for d in devices
            ],
        )


def tareas_pendientes(device_id: str) -> list[dict]:
    with _conexion() as con:
        filas = con.execute(text(
            "SELECT id, consulta_id, tipo FROM tareas "
            "WHERE device_id = :d AND respondida_en IS NULL ORDER BY id"
        ), {"d": device_id}).fetchall()
    return [dict(f._mapping) for f in filas]


def marcar_respondida(tarea_id: int, datos: dict) -> bool:
    """Guarda la respuesta. Devuelve False si la tarea no existe o ya respondió."""
    with _conexion() as con:
        result = con.execute(
            text(
                "UPDATE tareas SET respondida_en = :ahora, respuesta = :respuesta "
                "WHERE id = :id AND respondida_en IS NULL"
            ),
            {"ahora": _ahora(), "respuesta": json.dumps(datos, ensure_ascii=False), "id": tarea_id},
        )
    return result.rowcount > 0


def tareas_entregables() -> list[dict]:
    """Tareas respondidas pero aún no enviadas al chat de Telegram."""
    with _conexion() as con:
        filas = con.execute(text(
            "SELECT id, consulta_id, tipo, device_id, respuesta FROM tareas "
            "WHERE respondida_en IS NOT NULL AND entregada = 0 ORDER BY id"
        )).fetchall()
    return [dict(f._mapping) for f in filas]


def marcar_entregada(tarea_id: int) -> None:
    with _conexion() as con:
        con.execute(text("UPDATE tareas SET entregada = 1 WHERE id = :id"), {"id": tarea_id})


# ---------------- config ----------------

def get_config(k: str) -> str | None:
    with _conexion() as con:
        fila = con.execute(text("SELECT v FROM config WHERE k = :k"), {"k": k}).mappings().first()
    return fila["v"] if fila else None


def set_config(k: str, v: str) -> None:
    with _conexion() as con:
        con.execute(
            text(
                "INSERT INTO config (k, v) VALUES (:k, :v) "
                "ON CONFLICT(k) DO UPDATE SET v = excluded.v"
            ),
            {"k": k, "v": v},
        )
