# Bot_serv — Red de agentes + bot de Telegram

Servicio central de la app **Alquileres**: identifica cada instalación
(agente: nombre + teléfono), mantiene una **cola de consultas** (si una app
está apagada, la tarea queda esperando hasta que vuelva a estar online) y
responde a los comandos del dueño por Telegram.

- Las **apps** se registran y consultan tareas pendientes cada 30 min.
- El **bot de Telegram** responde en el grupo donde se añada.
- **Resumen diario automático** a las 22:30 (configurable).

## Comandos del bot

| Comando | Qué hace |
|---|---|
| `/start` | Registra el chat (grupo) donde se envía como destino de los informes |
| `/agentes` | Lista los agentes registrados (nombre · teléfono · última conexión) |
| `/resumen` | Consulta a **todas** las apps: «X hoy · Y total» por agente |
| `/consulta <nombre o teléfono>` | **Auditoría** de una app concreta (hoy · total · última conexión) |

Solo el chat destino (el grupo) puede usar los comandos.

## Arranque local

```bash
python -m venv venv
venv\Scripts\activate          # Windows (en Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env           # rellena TELEGRAM_BOT_TOKEN y API_TOKEN
uvicorn app.main:app --reload --port 8000
```

Tests:

```bash
python -m unittest discover -s tests
```

## Despliegue en Railway

1. Sube este repositorio a GitHub (el backend va en este repo).
2. En [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → elige este repo.
3. Railway detecta el `Procfile` y arranca `uvicorn app.main:app --port $PORT`.
4. En **Variables** añade:
   - `TELEGRAM_BOT_TOKEN` — el token de [@BotFather](https://t.me/BotFather).
   - `API_TOKEN` — token largo que escribes en Ajustes de cada app (sección «Agente y servidor»).
   - `BASE_URL` — la URL pública `https://…up.railway.app` que te da Railway (para el webhook del bot).
   - `RESUMEN_HORA` — `22:30` (opcional).    - `TZ` — `America/Havana` (hora de Cuba; opcional).
5. Abre el grupo de Telegram, añade el bot al grupo y escribe `/start`: el bot queda activo en ese grupo.
6. En la app de cada agente: **Ajustes → Agente y servidor** → URL del servidor (`https://tu-app.up.railway.app`) y Token (`API_TOKEN`), y pulsa **Sincronizar ahora**.

### Notas

- **SQLite efímero en Railway**: el disco se pierde al redeployar. Las apps
  se re-registran solas cada 30 min (la lista de agentes se auto-recupera);
  las tareas pendientes de apps apagadas en ese momento se pierden — basta
  repetir el comando. Para persistencia real, migrar a Postgres (evolución).
- **Polling cada 30 min**: la respuesta a `/resumen` puede tardar hasta 30 min
  por agente; el bot va actualizando el mismo mensaje a medida que responden.
- **Sin Telegram**: si `TELEGRAM_BOT_TOKEN` está vacío, el bot se desactiva y
  la API de agentes sigue funcionando (útil para pruebas locales).
