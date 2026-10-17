"""Pruebas de integracion del Worker contra `wrangler dev` (local, sin cuenta).

    cd gateway && python -m unittest -v

Necesitan Node y `npm install` en worker/. Si no estan, se saltan.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from faronet.cripto import Identidad
from faronet.directorio import ROL_GATEWAY, ROL_RELE, Entrada
from faronet_gateway import edge

WORKER = Path(__file__).resolve().parents[2] / "worker"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which("npx") and (WORKER / "node_modules").is_dir(),
                     "falta Node o `npm install` en worker/")
class TestWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = Identidad.nueva()
        cls.puerto = _puerto_libre()
        cls.url = f"http://127.0.0.1:{cls.puerto}"
        cls.estado = tempfile.mkdtemp(prefix="faronet-worker-")
        cls.proceso = subprocess.Popen(
            ["npx", "wrangler", "dev", "--port", str(cls.puerto), "--ip", "127.0.0.1",
             "--persist-to", cls.estado, "--var", f"GATEWAYS:{cls.gateway.llave_firma.hex()}",
             "--show-interactive-dev-session=false"],
            cwd=WORKER, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, "WRANGLER_SEND_METRICS": "false", "CI": "1"})
        limite = time.monotonic() + 90
        while time.monotonic() < limite:
            try:
                with urllib.request.urlopen(cls.url + "/api/salud", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            cls.tearDownClass()
            raise RuntimeError("wrangler dev no arranco")
        cls.cliente = edge.ClienteEdge(cls.url, cls.gateway)

    @classmethod
    def tearDownClass(cls):
        cls.proceso.terminate()
        try:
            cls.proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proceso.kill()
        shutil.rmtree(cls.estado, ignore_errors=True)

    # ---- gateway autenticado ----
    def test_publicar_aparece_en_sala_y_feed(self):
        self.cliente.publicar("pruebas", "hola desde la mesh", alias="anon")
        mensajes = self.cliente.mensajes("pruebas")
        self.assertEqual(mensajes[-1]["texto"], "hola desde la mesh")
        self.assertEqual(set(mensajes[-1]), {"id", "fecha", "alias", "texto"})  # nada del remitente
        with urllib.request.urlopen(self.url + "/salas/pruebas/feed.xml") as r:
            feed = r.read().decode()
        self.assertIn("<feed xmlns=\"http://www.w3.org/2005/Atom\">", feed)
        self.assertIn("hola desde la mesh", feed)
        with urllib.request.urlopen(self.url + "/api/salas") as r:
            self.assertIn("pruebas", [s["tema"] for s in json.load(r)["salas"]])

    def test_gateway_desconocido_rechazado(self):
        intruso = edge.ClienteEdge(self.url, Identidad.nueva())
        with self.assertRaises(edge.ErrorEdge) as e:
            intruso.publicar("pruebas", "no deberia entrar")
        self.assertEqual(e.exception.estado, 401)

    def test_replay_rechazado(self):
        cuerpo = json.dumps({"tema": "pruebas", "texto": "una vez"}).encode()
        tiempo = str(self.cliente._tiempo())
        mensaje = "\n".join([edge.CONTEXTO, "POST", "/api/gateway/publicar", tiempo,
                             hashlib.sha256(cuerpo).hexdigest()])
        cabeceras = {"content-type": "application/json", "x-faronet-gateway": self.cliente.llave,
                     "x-faronet-tiempo": tiempo,
                     "x-faronet-firma": self.gateway.firmar(mensaje.encode()).hex()}
        estado, _ = edge._pedir("POST", self.url + "/api/gateway/publicar", cuerpo, cabeceras)
        self.assertEqual(estado, 201)
        with self.assertRaises(edge.ErrorEdge) as e:
            edge._pedir("POST", self.url + "/api/gateway/publicar", cuerpo, cabeceras)
        self.assertIn("repetida", str(e.exception))

    def test_cuerpo_alterado_rechazado(self):
        cuerpo = json.dumps({"tema": "pruebas", "texto": "original"}).encode()
        tiempo = str(self.cliente._tiempo())
        mensaje = "\n".join([edge.CONTEXTO, "POST", "/api/gateway/publicar", tiempo,
                             hashlib.sha256(cuerpo).hexdigest()])
        cabeceras = {"content-type": "application/json", "x-faronet-gateway": self.cliente.llave,
                     "x-faronet-tiempo": tiempo,
                     "x-faronet-firma": self.gateway.firmar(mensaje.encode()).hex()}
        alterado = json.dumps({"tema": "pruebas", "texto": "alterado"}).encode()
        with self.assertRaises(edge.ErrorEdge) as e:
            edge._pedir("POST", self.url + "/api/gateway/publicar", alterado, cabeceras)
        self.assertEqual(e.exception.estado, 401)

    def test_directorio_con_firmas_verificables(self):
        nodo = Identidad.nueva()
        buena = Entrada.publicar(nodo, "faro-sur", ROL_RELE | ROL_GATEWAY).a_bytes()
        mala = bytearray(Entrada.publicar(Identidad.nueva(), "falso").a_bytes())
        mala[20] ^= 1
        r = self.cliente.subir_directorio([buena, bytes(mala)])
        self.assertEqual((r["aceptadas"], r["rechazadas"]), (1, 1))
        publica = {e["id"]: e for e in self.cliente.directorio()}
        e = publica[nodo.id.hex()]
        self.assertEqual((e["nombre"], e["roles"]), ("faro-sur", ["rele", "gateway"]))
        import base64
        self.assertEqual(Entrada.desde_bytes(base64.b64decode(e["entrada"])).id, nodo.id)

    # ---- buzon muerto ----
    def test_buzon_lectura_unica(self):
        secreto = os.urandom(32)
        edge.depositar(self.url, secreto, "nos vemos en el faro norte".encode())
        with self.assertRaises(edge.ErrorEdge) as e:
            edge.depositar(self.url, secreto, b"otro")
        self.assertEqual(e.exception.estado, 409)
        self.assertEqual(edge.retirar(self.url, secreto), "nos vemos en el faro norte".encode())
        self.assertIsNone(edge.retirar(self.url, secreto))

    def test_buzon_tamano_fijo(self):
        with self.assertRaises(edge.ErrorEdge) as e:
            edge._pedir("PUT", f"{self.url}/api/buzon/{'ab' * 32}", b"x" * 100)
        self.assertEqual(e.exception.estado, 400)
        self.assertEqual(len(edge.sellar_buzon(os.urandom(32), b"")), edge.BLOB)
        self.assertEqual(len(edge.sellar_buzon(os.urandom(32), b"y" * edge.BUZON_CLARO)), edge.BLOB)

    # ---- sala en vivo ----
    @unittest.skipUnless(shutil.which("node"), "falta node")
    def test_websocket_recibe_en_vivo(self):
        script = (
            "const ws=new WebSocket(process.argv[1]);let n=0;"
            "ws.onmessage=(e)=>{const d=JSON.parse(e.data);console.log(d.tipo+':'+(d.mensaje?d.mensaje.texto:''));"
            "if(++n===2){ws.close();process.exit(0)}};"
            "setTimeout(()=>process.exit(2),15000);")
        oyente = subprocess.Popen(["node", "-e", script, f"ws://127.0.0.1:{self.puerto}/salas/envivo/ws"],
                                  stdout=subprocess.PIPE, text=True)
        time.sleep(1.5)
        self.cliente.publicar("envivo", "en vivo!")
        salida, _ = oyente.communicate(timeout=20)
        self.assertIn("historial:", salida)
        self.assertIn("mensaje:en vivo!", salida)

    def test_pagina_sala_con_csp(self):
        with urllib.request.urlopen(self.url + "/salas/pruebas") as r:
            self.assertIn("nonce-", r.headers["content-security-policy"])
            self.assertIn("#pruebas", r.read().decode())


class TestBuzonLocal(unittest.TestCase):
    def test_secreto_equivocado_no_abre(self):
        blob = edge.sellar_buzon(b"a" * 32, b"secreto")
        self.assertEqual(edge.abrir_buzon(b"a" * 32, blob), b"secreto")
        with self.assertRaises(ValueError):
            edge.abrir_buzon(b"b" * 32, blob)
        self.assertNotEqual(edge.id_buzon(b"a" * 32), edge.id_buzon(b"b" * 32))


if __name__ == "__main__":
    unittest.main()
