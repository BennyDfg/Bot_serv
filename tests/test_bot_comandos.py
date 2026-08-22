"""Tests de los comandos de Telegram del bot (con mocks, sin red).

Se construyen Updates falsos y se captura lo que el bot respondería con
`reply_text`, verificando además los cambios en la base de datos
(habilitada, tareas, chat destino).
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import db as bot_db
from app.bot import telegram


def _update(chat_id: int, texto: str):
    u = MagicMock()
    u.effective_chat.id = chat_id
    u.effective_message.text = texto
    u.effective_message.reply_text = AsyncMock()
    return u


def _context(args=None):
    c = MagicMock()
    c.args = list(args or [])
    return c


class BotComandosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bot_db.RUTA_DB = Path(self.tmp.name) / "test_bot.db"
        bot_db.inicializar()
        bot_db.set_config("chat_destino", "12345")
        bot_db.registrar_agente("dev-1", "Juan", "600 111 222")
        bot_db.registrar_agente("dev-2", "Ana", "611 222 333")

    def tearDown(self):
        self.tmp.cleanup()

    def _correr(self, coro):
        return asyncio.run(coro)

    def test_agentes_lista_estado(self):
        u = _update(12345, "/agentes")
        self._correr(telegram.cmd_agentes(u, _context()))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("Juan", texto)
        self.assertIn("Ana", texto)
        self.assertIn("✅", texto)

    def test_deshabilitar_por_nombre(self):
        u = _update(12345, "/deshabilitar juan")
        self._correr(telegram.cmd_deshabilitar(u, _context(["juan"])))
        self.assertFalse(bot_db.es_habilitada("dev-1"))
        self.assertTrue(bot_db.es_habilitada("dev-2"))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("deshabilitada", texto)

    def test_habilitar_por_telefono(self):
        bot_db.set_habilitada("dev-2", False)
        u = _update(12345, "/habilitar 611222333")
        self._correr(telegram.cmd_habilitar(u, _context(["611222333"])))
        self.assertTrue(bot_db.es_habilitada("dev-2"))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("habilitada", texto)

    def test_deshabilitar_todos(self):
        u = _update(12345, "/deshabilitar_todos")
        self._correr(telegram.cmd_deshabilitar_todos(u, _context()))
        self.assertFalse(bot_db.es_habilitada("dev-1"))
        self.assertFalse(bot_db.es_habilitada("dev-2"))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("2", texto)

    def test_habilitar_todos(self):
        bot_db.set_habilitada_todos(False)
        u = _update(12345, "/habilitar_todos")
        self._correr(telegram.cmd_habilitar_todos(u, _context()))
        self.assertTrue(bot_db.es_habilitada("dev-1"))
        self.assertTrue(bot_db.es_habilitada("dev-2"))

    def test_comando_no_autorizado(self):
        u = _update(999, "/deshabilitar juan")
        self._correr(telegram.cmd_deshabilitar(u, _context(["juan"])))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("No autorizado", texto)
        self.assertTrue(bot_db.es_habilitada("dev-1"))

    def test_deshabilitar_agente_inexistente(self):
        u = _update(12345, "/deshabilitar inexistente")
        self._correr(telegram.cmd_deshabilitar(u, _context(["inexistente"])))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("No encontré", texto)

    def test_deshabilitar_ambiguo(self):
        bot_db.registrar_agente("dev-3", "Juan", "622 333 444")
        u = _update(12345, "/deshabilitar juan")
        self._correr(telegram.cmd_deshabilitar(u, _context(["juan"])))
        texto = u.effective_message.reply_text.call_args[0][0]
        self.assertIn("coinciden", texto)

    def test_consulta_crea_tarea(self):
        u = _update(12345, "/consulta juan")
        with patch.object(telegram, "application", MagicMock()) as app_mock:
            app_mock.bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
            self._correr(telegram.cmd_consulta(u, _context(["juan"])))
        self.assertEqual(len(bot_db.tareas_pendientes("dev-1")), 1)
        self.assertEqual(len(bot_db.tareas_pendientes("dev-2")), 0)

    def test_resumen_crea_tarea_para_todos(self):
        u = _update(12345, "/resumen")
        with patch.object(telegram, "application", MagicMock()) as app_mock:
            app_mock.bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
            self._correr(telegram.cmd_resumen(u, _context()))
        self.assertEqual(len(bot_db.tareas_pendientes("dev-1")), 1)
        self.assertEqual(len(bot_db.tareas_pendientes("dev-2")), 1)

    def test_webhook_secret(self):
        telegram.WEBHOOK_SECRET = "secreto-test"
        try:
            self.assertTrue(telegram.verificar_secret("secreto-test"))
            self.assertFalse(telegram.verificar_secret("malo"))
            self.assertFalse(telegram.verificar_secret(None))
        finally:
            telegram.WEBHOOK_SECRET = ""

    def test_resolver_agente(self):
        agente, error = telegram._resolver_agente("juan")
        self.assertIsNone(error)
        self.assertEqual(agente["device_id"], "dev-1")
        agente, error = telegram._resolver_agente("inexistente")
        self.assertIsNone(agente)
        self.assertIn("No encontré", error)


class WebhookArranqueTests(unittest.TestCase):
    """El webhook solo se configura con una URL real, nunca con un
    placeholder del .env.example (regresión: tu-app.up.railway.app /
    tu-app.onrender.com). Sin URL resoluble se devuelve vacío y el
    webhook queda desactivado."""

    def setUp(self):
        telegram.TOKEN = "token-test"
        telegram.WEBHOOK_SECRET = ""

    def tearDown(self):
        telegram.TOKEN = ""
        telegram.WEBHOOK_SECRET = ""

    def test_base_url_efectiva_con_url_real(self):
        with patch.dict("os.environ", {"BASE_URL": "https://mi-servicio.up.railway.app"}, clear=False):
            self.assertEqual(
                telegram._base_url_efectiva(),
                "https://mi-servicio.up.railway.app",
            )

    def test_base_url_efectiva_con_render_external_url(self):
        with patch.dict("os.environ", {"RENDER_EXTERNAL_URL": "https://mi-bot.onrender.com"}, clear=True):
            self.assertEqual(
                telegram._base_url_efectiva(),
                "https://mi-bot.onrender.com",
            )

    def test_base_url_efectiva_prioriza_base_url_sobre_render(self):
        with patch.dict("os.environ", {
            "BASE_URL": "https://dominio-propio.com",
            "RENDER_EXTERNAL_URL": "https://mi-bot.onrender.com",
        }, clear=True):
            self.assertEqual(
                telegram._base_url_efectiva(),
                "https://dominio-propio.com",
            )

    def test_base_url_efectiva_ignora_el_placeholder(self):
        with patch.dict("os.environ", {"BASE_URL": "https://tu-app.up.railway.app"}, clear=False):
            self.assertEqual(telegram._base_url_efectiva(), "")

    def test_base_url_efectiva_ignora_el_placeholder_de_render(self):
        with patch.dict("os.environ", {"BASE_URL": "https://tu-app.onrender.com"}, clear=False):
            self.assertEqual(telegram._base_url_efectiva(), "")

    def test_base_url_efectiva_vacia_devuelve_vacio(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(telegram._base_url_efectiva(), "")

    def test_arrancar_configura_webhook_solo_con_url_real(self):
        app_mock = MagicMock()
        app_mock.initialize = AsyncMock()
        app_mock.start = AsyncMock()
        app_mock.bot.set_webhook = AsyncMock()
        with patch.object(telegram, "application", app_mock),              patch.object(telegram, "BASE_URL", "https://mi-servicio.up.railway.app"):
            asyncio.run(telegram.arrancar())
        app_mock.bot.set_webhook.assert_awaited_once_with(
            "https://mi-servicio.up.railway.app/webhook/telegram",
            secret_token=None,
        )

    def test_arrancar_sin_base_url_no_llama_al_webhook(self):
        app_mock = MagicMock()
        app_mock.initialize = AsyncMock()
        app_mock.start = AsyncMock()
        app_mock.bot.set_webhook = AsyncMock()
        with patch.object(telegram, "application", app_mock),              patch.object(telegram, "BASE_URL", ""):
            asyncio.run(telegram.arrancar())
        app_mock.bot.set_webhook.assert_not_awaited()


class SecretSanitizacionTests(unittest.TestCase):
    """El secret_token del webhook solo puede llevar A-Z, a-z, 0-9, _ y -."""

    def test_conserva_caracteres_permitidos(self):
        self.assertEqual(telegram._sanitizar_secret("Abz-09_XY"), "Abz-09_XY")

    def test_elimina_caracteres_no_permitidos(self):
        self.assertEqual(telegram._sanitizar_secret("a.b/c+d=e!f$g:h"), "abcdefgh")

    def test_vacio_o_solo_no_permitidos_devuelve_vacio(self):
        self.assertEqual(telegram._sanitizar_secret(""), "")
        self.assertEqual(telegram._sanitizar_secret("...///"), "")

    def test_trunca_a_256_caracteres(self):
        self.assertEqual(len(telegram._sanitizar_secret("a" * 300)), 256)


if __name__ == "__main__":
    unittest.main()
