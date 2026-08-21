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

## Despliegue en Render (plan gratuito)

1. Sube este repositorio a GitHub (el repo es `BennyDfg/Bot_serv`).
2. En [render.com](https://render.com) → **New → Blueprint** → conecta GitHub
   y elige el repo. Render lee `render.yaml` y crea el servicio **Web** con
   plan **Free**.
3. Durante la creación te pide las variables `sync: false`:
   - `TELEGRAM_BOT_TOKEN` — el token de [@BotFather](https://t.me/BotFather).
   - `API_TOKEN` — token largo que escribes en Ajustes de cada app (sección «Agente y servidor»).
   - `BASE_URL` — déjala vacía: Render la resuelve solo con `RENDER_EXTERNAL_URL`.
   - `OWNER_CHAT_ID` — opcional.
   - `DATABASE_URL` — vacía para SQLite (ver nota de persistencia).
   (`WEBHOOK_SECRET` se genera solo.)
4. Abre el grupo de Telegram, añade el bot y escribe `/start`: queda activo ahí.
5. En la app de cada agente: **Ajustes → Agente y servidor** → URL del
   servidor (`https://<nombre>.onrender.com`) y Token (`API_TOKEN`), y pulsa
   **Sincronizar ahora**.

### Límites del plan Free de Render

- **Se duerme a los 15 min sin tráfico** y tarda ~1 min en despertar con la
  siguiente petición. Para que el bot responda y el resumen diario (22:30) se
  dispare, mantenlo despierto con un ping externo cada ~10 min a
  `https://<nombre>.onrender.com/health` (p. ej. [UptimeRobot](https://uptimerobot.com)
  o [cron-job.org](https://cron-job.org), ambos con plan gratis).
- **Disco efímero**: con SQLite (sin `DATABASE_URL`) los datos se pierden en
  cada redeploy, reinicio o spin-down (15 min de inactividad). Las apps se
  re-registran solas cada 30 min, pero el grupo destino (`/start`) y las
  tareas en cola se pierden. Para que sobreviva a los spin-downs, añade un
  **Postgres** (Render ofrece uno Free, pero **expira a los 30 días**).
- **750 horas Free/mes** por workspace: un servicio despierto 24/7 consume
  ~720-744 h/mes. Si se acaban, Render suspende los servicios Free hasta el
  mes siguiente.

## Despliegue en Railway (alternativa)

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
