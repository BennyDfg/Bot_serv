"""Tests de la API de agentes y la cola de tareas (sin Telegram real)."""
import tempfile
import unittest
from pathlib import Path

from app.bot import db as bot_db
from app.routes import bot_api


class BotDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bot_db.RUTA_DB = Path(self.tmp.name) / "test_bot.db"
        bot_db.inicializar()

    def tearDown(self):
        self.tmp.cleanup()

    def _registrar(self, device="dev-1", nombre="Juan", telefono="600 000 000"):
        return bot_api.RegistrarIn(device_id=device, nombre=nombre, telefono=telefono)

    def test_registro_y_re_registro_actualiza(self):
        bot_api.registrar(self._registrar())
        bot_api.registrar(self._registrar(nombre="Juan Carlos"))
        agentes = bot_db.listar_agentes()
        self.assertEqual(len(agentes), 1)
        self.assertEqual(agentes[0]["nombre"], "Juan Carlos")
        self.assertIsNotNone(agentes[0]["ultima_conexion"])

    def test_tareas_pendientes_y_respuesta(self):
        bot_api.registrar(self._registrar())
        bot_db.crear_tareas("consulta-1", "consulta", ["dev-1"])

        pendientes = bot_api.tareas("dev-1").get("tareas")
        self.assertEqual(len(pendientes), 1)
        tarea_id = pendientes[0]["id"]

        r = bot_api.responder("dev-1", bot_api.RespuestaIn(tarea_id=tarea_id, datos={"hoy": 3, "total": 12}))
        self.assertTrue(r["ok"])

        self.assertEqual(bot_api.tareas("dev-1").get("tareas"), [])

    def test_responder_dos_veces_falla(self):
        bot_api.registrar(self._registrar())
        bot_db.crear_tareas("consulta-1", "consulta", ["dev-1"])
        tarea_id = bot_api.tareas("dev-1").get("tareas")[0]["id"]
        bot_api.responder("dev-1", bot_api.RespuestaIn(tarea_id=tarea_id, datos={"hoy": 1, "total": 1}))
        with self.assertRaises(Exception):
            bot_api.responder("dev-1", bot_api.RespuestaIn(tarea_id=tarea_id, datos={"hoy": 2, "total": 2}))

    def test_entrega_marca_entregada(self):
        bot_api.registrar(self._registrar())
        bot_db.crear_tareas("consulta-1", "consulta", ["dev-1"])
        tarea_id = bot_api.tareas("dev-1").get("tareas")[0]["id"]
        bot_api.responder("dev-1", bot_api.RespuestaIn(tarea_id=tarea_id, datos={"hoy": 0, "total": 5}))
        entregables = bot_db.tareas_entregables()
        self.assertEqual(len(entregables), 1)
        bot_db.marcar_entregada(entregables[0]["id"])
        self.assertEqual(bot_db.tareas_entregables(), [])

    def test_buscar_agente_por_nombre_o_telefono(self):
        bot_api.registrar(self._registrar())
        bot_api.registrar(self._registrar(device="dev-2", nombre="Ana", telefono="611222333"))
        self.assertEqual(len(bot_db.buscar_agente("juan")), 1)
        self.assertEqual(len(bot_db.buscar_agente("JUAN")), 1)
        self.assertEqual(len(bot_db.buscar_agente("611222333")), 1)
        self.assertEqual(len(bot_db.buscar_agente("611 222 333")), 1)
        self.assertEqual(len(bot_db.buscar_agente("inexistente")), 0)

    def test_tareas_de_otro_dispositivo_no_se_mezclan(self):
        bot_api.registrar(self._registrar())
        bot_api.registrar(self._registrar(device="dev-2", nombre="Ana", telefono="611222333"))
        bot_db.crear_tareas("consulta-1", "consulta", ["dev-1", "dev-2"])
        self.assertEqual(len(bot_api.tareas("dev-1").get("tareas")), 1)
        self.assertEqual(len(bot_api.tareas("dev-2").get("tareas")), 1)

    def test_registrar_devuelve_habilitada(self):
        self.assertTrue(bot_api.registrar(self._registrar())["habilitada"])

    def test_tareas_devuelven_habilitada(self):
        bot_api.registrar(self._registrar())
        self.assertTrue(bot_api.tareas("dev-1")["habilitada"])

    def test_deshabilitar_y_habilitar_un_agente(self):
        bot_api.registrar(self._registrar())
        self.assertTrue(bot_db.set_habilitada("dev-1", False))
        self.assertFalse(bot_db.es_habilitada("dev-1"))
        self.assertFalse(bot_db.obtener_agente("dev-1")["habilitada"])
        self.assertFalse(bot_api.tareas("dev-1")["habilitada"])
        self.assertTrue(bot_db.set_habilitada("dev-1", True))
        self.assertTrue(bot_db.es_habilitada("dev-1"))

    def test_deshabilitar_todos(self):
        bot_api.registrar(self._registrar())
        bot_api.registrar(self._registrar(device="dev-2", nombre="Ana", telefono="611222333"))
        self.assertEqual(bot_db.set_habilitada_todos(False), 2)
        self.assertFalse(bot_db.es_habilitada("dev-1"))
        self.assertFalse(bot_db.es_habilitada("dev-2"))
        self.assertEqual(bot_db.set_habilitada_todos(True), 2)
        self.assertTrue(bot_db.es_habilitada("dev-1"))

    def test_re_registro_no_reactiva_a_un_deshabilitado(self):
        bot_api.registrar(self._registrar())
        bot_db.set_habilitada("dev-1", False)
        # El agente vuelve a registrarse (polling): no debe desbloquearse.
        bot_api.registrar(self._registrar(nombre="Juan Carlos"))
        self.assertFalse(bot_db.es_habilitada("dev-1"))
        self.assertEqual(bot_db.obtener_agente("dev-1")["nombre"], "Juan Carlos")

    def test_set_habilitada_agente_inexistente_devuelve_false(self):
        self.assertFalse(bot_db.set_habilitada("no-existe", False))


if __name__ == "__main__":
    unittest.main()
