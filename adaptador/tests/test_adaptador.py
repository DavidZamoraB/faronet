"""Pruebas de DispositivoLuzAdaptador usando Faros simulados.

    cd adaptador && python3 -m unittest -v
"""
import os
import subprocess
import unittest
from pathlib import Path

from dispositivo_luz_adaptador import (DIFUSION, MAX_CARGA, DispositivoLuzAdaptador, ErrorFaro,
                                       Trama, parsear_direccion)
from dispositivo_luz_adaptador import cobs, enlace, medicion
from dispositivo_luz_adaptador.crc import crc16
from dispositivo_luz_adaptador.simulador import FaroSimulado, MedioSimulado
from dispositivo_luz_adaptador.trama import ErrorTrama

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware" / "faro"


class TestFormato(unittest.TestCase):
    def test_crc_vector_conocido(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_cobs(self):
        for datos in [b"\x00", b"\x00\x00", b"\x11\x22\x00\x33", bytes(range(256)) * 2, b"\x01" * 300]:
            cod = cobs.codificar(datos)
            self.assertNotIn(0, cod)
            self.assertEqual(cobs.decodificar(cod), datos)

    def test_trama_ida_y_vuelta(self):
        t = Trama(destino=b"\x01\x02\x03\x04", origen=b"\x0a\x0b\x0c\x0d",
                  carga=b"x" * MAX_CARGA, pide_ack=True, seq=200)
        crudo = t.a_bytes()
        self.assertEqual(len(crudo), 128)
        self.assertEqual(Trama.desde_bytes(crudo), t)
        malo = bytearray(crudo)
        malo[30] ^= 4
        with self.assertRaises(ErrorTrama):
            Trama.desde_bytes(bytes(malo))

    def test_carga_demasiado_grande(self):
        with self.assertRaises(ErrorTrama):
            Trama(destino=DIFUSION, origen=b"\x01" * 4, carga=b"x" * (MAX_CARGA + 1)).a_bytes()

    def test_direcciones(self):
        self.assertEqual(parsear_direccion("a1:b2:c3:d4"), b"\xa1\xb2\xc3\xd4")
        self.assertEqual(parsear_direccion("difusion"), DIFUSION)
        with self.assertRaises(ErrorTrama):
            parsear_direccion("a1:b2")

    def test_paquete_enlace(self):
        crudo = enlace.empaquetar(enlace.CMD_ENVIAR, b"\x00\x01\x00")
        self.assertEqual(crudo[-1], 0)
        self.assertEqual(enlace.desempaquetar(crudo[:-1]), (enlace.CMD_ENVIAR, b"\x00\x01\x00"))
        dañado = bytearray(crudo[:-1])
        dañado[2] ^= 0x40
        with self.assertRaises(enlace.ErrorEnlace):
            enlace.desempaquetar(bytes(dañado) if 0 not in dañado else b"\x01")


class TestCompatibilidadFirmware(unittest.TestCase):
    """Las constantes de Python deben coincidir con las del firmware."""

    def _defines(self, archivo):
        valores = {}
        for linea in (FIRMWARE / archivo).read_text().splitlines():
            partes = linea.split()
            if len(partes) >= 3 and partes[0] == "#define":
                try:
                    valores[partes[1]] = int(partes[2], 0)
                except ValueError:
                    pass
        return valores

    def test_codigos_del_enlace(self):
        d = self._defines("enlace_serial.h")
        for nombre in ["CMD_PING", "CMD_ENVIAR", "CMD_ENVIAR_CRUDA", "CMD_CONFIGURAR", "CMD_PANICO",
                       "CMD_SONDEAR", "CMD_EMISOR_FIJO", "RSP_INFO", "RSP_RESULTADO_TX", "EVT_PANICO",
                       "EVT_TRAMA_RECIBIDA", "TX_SIN_ACK", "OPC_PROMISCUO", "OPC_ENTREGAR_CRC_MALO"]:
            self.assertEqual(d[nombre], getattr(enlace, nombre), nombre)

    def test_formato_de_trama(self):
        from dispositivo_luz_adaptador import trama
        d = self._defines("faro_core.h")
        self.assertEqual(d["FARO_VERSION"], trama.VERSION)
        self.assertEqual(d["FARO_CABECERA"], trama.CABECERA)
        self.assertEqual(d["FARO_MAX_TRAMA"], trama.MAX_TRAMA)
        self.assertEqual(d["BANDERA_PIDE_ACK"], trama.BANDERA_PIDE_ACK)


class TestConSimulador(unittest.TestCase):
    def setUp(self):
        self.medio = MedioSimulado(semilla=1)
        self.a = DispositivoLuzAdaptador(FaroSimulado(self.medio), timeout=1).abrir()
        self.b = DispositivoLuzAdaptador(FaroSimulado(self.medio), timeout=1).abrir()

    def tearDown(self):
        self.a.cerrar()
        self.b.cerrar()

    def test_ping_e_info(self):
        self.assertEqual(self.a.ping().max_trama, 128)
        self.assertEqual(len(self.a.info().direccion), 4)

    def test_unicast_con_ack(self):
        r = self.a.enviar(self.b.direccion, b"hola faro")
        self.assertTrue(r.ok, r)
        rec = self.b.recibir(timeout=1)
        self.assertTrue(rec.crc_ok)
        self.assertEqual(rec.trama.carga, b"hola faro")
        self.assertEqual(rec.trama.origen, self.a.direccion)

    def test_destino_inexistente_sin_ack(self):
        r = self.a.enviar("01:02:03:04", b"nadie")
        self.assertFalse(r.ok)
        self.assertEqual(r.intentos, self.a.info().reintentos + 1)
        self.assertIsNone(self.b.recibir(timeout=0.2))

    def test_difusion(self):
        self.assertTrue(self.a.enviar(DIFUSION, b"todos").ok)
        self.assertEqual(self.b.recibir(timeout=1).trama.carga, b"todos")

    def test_trama_cruda_armada_afuera(self):
        t = Trama(destino=self.b.direccion, origen=b"\x42" * 4, carga=b"de scapy", seq=9)
        self.assertTrue(self.a.enviar_trama(t).ok)
        self.assertEqual(self.b.recibir(timeout=1).trama.seq, 9)

    def test_carga_maxima(self):
        with self.assertRaises(ValueError):
            self.a.enviar(self.b.direccion, b"x" * (MAX_CARGA + 1))

    def test_rotar_direccion(self):
        antes = self.a.direccion
        nueva = self.a.rotar_direccion()
        self.assertNotEqual(antes, nueva)
        self.assertEqual(self.a.info().direccion, nueva)

    def test_secreto_y_panico(self):
        borrado = []
        self.a.al_panico(borrado.append)
        secreto = os.urandom(32)
        self.a.guardar_secreto(secreto)
        self.assertEqual(self.a.leer_secreto(), secreto)
        antes = self.a.direccion
        self.a.panico()
        self.a.ping()  # deja pasar el evento
        self.assertEqual(len(borrado), 1)
        self.assertIsNone(self.a.leer_secreto())
        self.assertNotEqual(self.a.info().direccion, antes)

    def test_configurar(self):
        info = self.a.configurar(bps=4000, promiscuo=True)
        self.assertEqual((info.bps, info.promiscuo), (4000, True))
        with self.assertRaises(ValueError):
            self.a.configurar(bps=100)

    def test_promiscuo_ve_tramas_ajenas(self):
        c = DispositivoLuzAdaptador(FaroSimulado(self.medio), timeout=1).abrir()
        try:
            c.configurar(promiscuo=True)
            self.a.enviar(self.b.direccion, b"privado")
            self.assertEqual(c.recibir(timeout=1).trama.carga, b"privado")
        finally:
            c.cerrar()

    def test_comando_sin_respuesta(self):
        self.a._serial.write = lambda datos: len(datos)  # el Faro "se cuelga"
        with self.assertRaises(ErrorFaro):
            self.a.ping(timeout=0.2)


class TestMedicion(unittest.TestCase):
    def test_ber_con_ruido(self):
        medio = MedioSimulado(ber=2e-3, semilla=7)  # BER alto a proposito
        a = DispositivoLuzAdaptador(FaroSimulado(medio), timeout=1).abrir()
        b = DispositivoLuzAdaptador(FaroSimulado(medio), timeout=1).abrir()
        try:
            b.configurar(entregar_crc_malo=True)
            medicion.emisor(a, tramas=60, tam=100)
            r = medicion.receptor(b, tramas=60, tam=100, espera_inicial=1, inactividad=0.3)
            self.assertEqual(r.recibidas, 60)
            self.assertLess(r.crc_ok, 60)            # con este BER algunas llegan dañadas
            self.assertGreater(r.ber, 5e-4)
            self.assertLess(r.ber, 5e-3)
        finally:
            a.cerrar()
            b.cerrar()


class TestScapy(unittest.TestCase):
    def test_trama_scapy_compatible(self):
        try:
            from dispositivo_luz_adaptador.scapy_faro import FaroTrama
        except ImportError:
            self.skipTest("scapy no esta instalado")
        crudo = bytes(FaroTrama(dst=DIFUSION, src=b"\x01\x02\x03\x04", seq=7,
                                banderas=1, carga=b"hola"))
        esperado = Trama(destino=DIFUSION, origen=b"\x01\x02\x03\x04", carga=b"hola",
                         pide_ack=True, seq=7).a_bytes()
        self.assertEqual(crudo, esperado)


class TestFirmwareCore(unittest.TestCase):
    """Compila y corre las pruebas en C++ del firmware si hay g++."""

    def test_core_cpp(self):
        import shutil
        import tempfile
        if not shutil.which("g++"):
            self.skipTest("g++ no esta instalado")
        with tempfile.TemporaryDirectory() as tmp:
            binario = os.path.join(tmp, "test_core")
            subprocess.run(["g++", "-std=c++11", "-Wall", f"-I{FIRMWARE}",
                            str(FIRMWARE / "test" / "test_core.cpp"),
                            str(FIRMWARE / "faro_core.cpp"), "-o", binario], check=True)
            r = subprocess.run([binario], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
