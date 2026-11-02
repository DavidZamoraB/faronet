"""Pruebas del Faro sobre GPIO con una Raspberry falsa.

El "aire" une el LED IR de cada Raspberry falsa con el sensor de las demas y
entrega los flancos en tiempo real, con marcas de tiempo en microsegundos
como pigpio.
"""
import os
import random
import tempfile
import threading
import time
import unittest

from dispositivo_luz_adaptador import DispositivoLuzAdaptador
from dispositivo_luz_adaptador import enlace as E
from dispositivo_luz_adaptador.faro_gpio import (DecodificadorManchester, FaroGPIO, PINES_DEFECTO,
                                                 parsear_puerto, pulsos_manchester)
from dispositivo_luz_adaptador.trama import Trama

MASCARA = 0xFFFFFFFF


def ahora_us() -> int:
    return int(time.monotonic() * 1e6) & MASCARA


class Aire:
    def __init__(self):
        self.pis = []
        self.descartar = None  # funcion(origen, edges) -> True para perder la transmision

    def transmitir(self, origen, flancos):
        if self.descartar and self.descartar(origen, flancos):
            return
        for pi in self.pis:
            if pi is not origen:
                threading.Thread(target=pi.recibir_luz, args=(flancos,), daemon=True).start()


class _Cb:
    def __init__(self, lista, item):
        self.lista, self.item = lista, item

    def cancel(self):
        if self.item in self.lista:
            self.lista.remove(self.item)


class PiFalsa:
    def __init__(self, aire, pines=PINES_DEFECTO):
        self.aire = aire
        aire.pis.append(self)
        self.emisor, self.receptor, self.boton = pines[:3]
        self.niveles = {}
        self.cbs = []
        self.pulsos = []
        self.ocupado_hasta = 0.0

    # ---- API de pigpio que usa FaroGPIO ----
    def set_mode(self, pin, modo): pass
    def set_pull_up_down(self, pin, pud): self.niveles[pin] = 1
    def set_glitch_filter(self, pin, us): pass
    def stop(self): pass
    def get_current_tick(self): return ahora_us()
    def read(self, pin): return self.niveles.get(pin, 0)

    def write(self, pin, nivel):
        if pin == self.emisor and self.niveles.get(pin, 0) != nivel:
            self.aire.transmitir(self, [(ahora_us(), nivel)])
        self.niveles[pin] = nivel

    def callback(self, pin, flanco, func):
        item = (pin, flanco, func)
        self.cbs.append(item)
        return _Cb(self.cbs, item)

    def wave_add_new(self): self.pulsos = []
    def wave_add_generic(self, pulsos): self.pulsos.extend(pulsos)
    def wave_create(self): return 0
    def wave_delete(self, wid): pass
    def wave_tx_busy(self): return time.monotonic() < self.ocupado_hasta

    def wave_send_once(self, wid):
        t0 = time.monotonic()
        t, nivel, flancos = 0, self.niveles.get(self.emisor, 0), []
        for encender, apagar, us in self.pulsos:
            nuevo = 1 if encender & (1 << self.emisor) else 0 if apagar & (1 << self.emisor) else nivel
            if nuevo != nivel:
                flancos.append((t, nuevo))
                nivel = nuevo
            t += us
        self.ocupado_hasta = t0 + t / 1e6
        base = int(t0 * 1e6)
        self.aire.transmitir(self, [((base + dt) & MASCARA, n) for dt, n in flancos])

    # ---- lado receptor ----
    def recibir_luz(self, flancos):
        for tick, nivel in flancos:
            espera = _seg(tick) - time.monotonic()
            if espera > 0.0003:
                time.sleep(espera)
            self.niveles[self.receptor] = nivel
            for pin, _, func in list(self.cbs):
                if pin == self.receptor:
                    func(pin, nivel, tick)

    def presionar_boton(self):
        for pin, _, func in list(self.cbs):
            if pin == self.boton:
                func(pin, 0, ahora_us())


def _seg(tick: int) -> float:
    """Tick de 32 bits -> segundos de time.monotonic (sin vuelta del contador)."""
    actual = int(time.monotonic() * 1e6)
    base = actual - ((actual - tick) & MASCARA)
    if actual - base > 1 << 31:
        base += 1 << 32
    return base / 1e6


class TestCodigo(unittest.TestCase):
    def flancos(self, trama, bps, jitter=0.0, invertir=False):
        dec = DecodificadorManchester(bps)
        nivel_previo = 0
        salida = None
        azar = random.Random(1)
        acumulado = 0
        for nivel, us in pulsos_manchester(trama, bps):
            if nivel != nivel_previo:
                dt = int(acumulado * (1 + azar.uniform(-jitter, jitter))) if acumulado else 10_000
                r = dec.flanco(dt, nivel ^ invertir)
                salida = salida or r
                acumulado = 0
            nivel_previo = nivel
            acumulado += us
        return salida

    def test_ida_y_vuelta_con_desfase_e_inversion(self):
        trama = Trama(destino=b"\x01\x02\x03\x04", origen=b"\x0a\x0b\x0c\x0d",
                      carga=bytes(range(100)), seq=7).a_bytes()
        for bps in (500, 2000, 10000):
            self.assertEqual(self.flancos(trama, bps), trama)
            self.assertEqual(self.flancos(trama, bps, jitter=0.25), trama)
            self.assertEqual(self.flancos(trama, bps, invertir=True), trama)

    def test_pulsos_terminan_apagados(self):
        pulsos = pulsos_manchester(b"\xff" * 14, 2000)
        self.assertEqual(pulsos[-1][0], 0)
        self.assertEqual(pulsos[0][0], 1)  # el preambulo 0x55 empieza con un 0 = encendido

    def test_parsear_puerto(self):
        self.assertEqual(parsear_puerto("gpio"), (PINES_DEFECTO, None))
        self.assertEqual(parsear_puerto("gpio:1,2,3,4,5,6@pi.local"), ((1, 2, 3, 4, 5, 6), "pi.local"))
        with self.assertRaises(ValueError):
            parsear_puerto("gpio:1,2")


class TestFaroGPIO(unittest.TestCase):
    BPS = 5000

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.aire = Aire()
        self.pis = [PiFalsa(self.aire), PiFalsa(self.aire)]
        self.faros = [DispositivoLuzAdaptador(
            FaroGPIO(pi=pi, bps=self.BPS, archivo=os.path.join(self.dir.name, f"f{i}.json"))).abrir()
            for i, pi in enumerate(self.pis)]

    def tearDown(self):
        for f in self.faros:
            f.cerrar()
        self.dir.cleanup()

    def test_unicast_con_ack(self):
        a, b = self.faros
        r = a.enviar(b.direccion, b"hola por luz")
        self.assertTrue(r.ok, r)
        rec = b.recibir(timeout=2)
        self.assertEqual(rec.trama.carga, b"hola por luz")
        self.assertEqual(rec.trama.origen, a.direccion)

    def test_difusion(self):
        a, b = self.faros
        self.assertTrue(a.enviar(b"\xff\xff\xff\xff", b"a todos").ok)
        self.assertEqual(b.recibir(timeout=2).trama.carga, b"a todos")

    def test_ack_perdido_se_retransmite_sin_duplicar(self):
        a, b = self.faros
        perdidos = []

        def perder_primer_ack(origen, flancos):
            if origen is self.pis[1] and len(flancos) > 50 and not perdidos:
                perdidos.append(1)
                return True
            return False
        self.aire.descartar = perder_primer_ack
        r = a.enviar(b.direccion, b"una sola vez")
        self.assertTrue(r.ok)
        self.assertGreaterEqual(r.intentos, 2)
        self.assertEqual(b.recibir(timeout=2).trama.carga, b"una sola vez")
        self.assertIsNone(b.recibir(timeout=0.5))  # la retransmision no se entrega dos veces

    def test_panico_con_el_boton(self):
        a = self.faros[0]
        a.guardar_secreto(b"s" * 32)
        archivo = os.path.join(self.dir.name, "f0.json")
        with open(archivo) as f:
            self.assertIn("737373", f.read())
        vieja = a.direccion
        avisos = []
        a.al_panico(avisos.append)
        self.pis[0].presionar_boton()
        deadline = time.monotonic() + 3
        while not avisos and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(avisos)
        self.assertIsNone(a.leer_secreto())
        self.assertNotEqual(a.info().direccion, vieja)
        with open(archivo) as f:
            self.assertNotIn("737373", f.read())

    def test_direccion_persiste(self):
        a = self.faros[0]
        nueva = a.rotar_direccion()
        faro = FaroGPIO(pi=PiFalsa(Aire()), archivo=os.path.join(self.dir.name, "f0.json"))
        self.assertEqual(faro.direccion, nueva)


if __name__ == "__main__":
    unittest.main()
