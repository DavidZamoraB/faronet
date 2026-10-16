"""Faros simulados para desarrollar y probar sin hardware.

Cada FaroSimulado se comporta como el puerto serial de un Faro real (habla
el mismo protocolo que el firmware), y un MedioSimulado hace de "luz" entre
ellos. Sirve para que la mesh (nodo/, gateway/) se pueda desarrollar antes
de tener los Faros soldados:

    medio = MedioSimulado(ber=1e-4)
    a = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
    b = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
    a.enviar(b.direccion, b"hola")
    print(b.recibir(timeout=1).trama.carga)
"""
from __future__ import annotations

import os
import random
import threading

from . import enlace as E
from .trama import (BANDERA_PIDE_ACK, DIFUSION, MAX_CARGA, TIPO_ACK, TIPO_DATOS,
                    TIPO_MASCARA, VERSION, Trama, crc_valido, direccion_valida)


class MedioSimulado:
    """Canal compartido. `ber` es la probabilidad de invertir cada bit."""

    def __init__(self, ber: float = 0.0, semilla: int | None = None):
        self.ber = ber
        self.faros: list["FaroSimulado"] = []
        self._azar = random.Random(semilla)
        self._lock = threading.Lock()

    def _ruido(self, datos: bytes) -> bytes:
        if self.ber <= 0:
            return datos
        salida = bytearray(datos)
        for i in range(len(salida)):
            for bit in range(8):
                if self._azar.random() < self.ber:
                    salida[i] ^= 1 << bit
        return bytes(salida)

    def transmitir(self, emisor: "FaroSimulado", trama: bytes) -> bool:
        """Entrega la trama a los demas Faros. Devuelve True si llego un ACK."""
        with self._lock:
            ack = False
            for faro in self.faros:
                if faro is emisor:
                    continue
                if faro._recibir_luz(self._ruido(trama)):
                    # el ACK tambien puede corromperse en el camino de vuelta
                    ack = ack or crc_valido(self._ruido(faro._ultimo_ack))
            return ack


class FaroSimulado:
    """Objeto con la interfaz minima de pyserial (read/write/close)."""

    def __init__(self, medio: MedioSimulado, direccion: bytes | None = None, bps: int = 2000):
        self.medio = medio
        medio.faros.append(self)
        self.direccion = direccion or self._direccion_aleatoria()
        self.bps = bps
        self.opciones = 0
        self.reintentos = 3
        self.secreto: bytes | None = None
        self.secuencia = random.randrange(256)
        self.estad = [0] * 6  # tx, rx, crc_malos, sin_ack, retransmisiones, truncadas
        self._ultimo_ack = b""
        self._salida = bytearray()
        self._cond = threading.Condition()
        self._delim = E.Delimitador()
        self.timeout = 0.05

    @staticmethod
    def _direccion_aleatoria() -> bytes:
        while True:
            d = os.urandom(4)
            if direccion_valida(d):
                return d

    # ---- interfaz tipo pyserial ----
    def write(self, datos: bytes) -> int:
        for crudo in self._delim.alimentar(datos):
            try:
                tipo, cuerpo = E.desempaquetar(crudo)
            except E.ErrorEnlace:
                self._responder(E.RSP_ERROR, bytes([0x03]))
                continue
            self._atender(tipo, cuerpo)
        return len(datos)

    def read(self, n: int = 1) -> bytes:
        with self._cond:
            if not self._salida:
                self._cond.wait(self.timeout)
            datos = bytes(self._salida[:n])
            del self._salida[:n]
            return datos

    def close(self) -> None:
        if self in self.medio.faros:
            self.medio.faros.remove(self)

    def reset_input_buffer(self) -> None:
        with self._cond:
            self._salida.clear()

    # ---- logica del Faro ----
    def _responder(self, tipo: int, datos: bytes = b"") -> None:
        with self._cond:
            self._salida += E.empaquetar(tipo, datos)
            self._cond.notify_all()

    def _info(self) -> bytes:
        return (self.direccion + self.bps.to_bytes(2, "big") +
                bytes([self.opciones, self.reintentos, 1 if self.secreto else 0]))

    def _transmitir(self, trama: bytes) -> tuple[int, int]:
        pide_ack = (trama[0] == VERSION and trama[2] & BANDERA_PIDE_ACK
                    and trama[4:8] != DIFUSION)
        for intento in range(self.reintentos + 1):
            if intento:
                self.estad[4] += 1
            self.estad[0] += 1
            ack = self.medio.transmitir(self, trama)
            if not pide_ack or ack:
                return E.TX_OK, intento + 1
        self.estad[3] += 1
        return E.TX_SIN_ACK, self.reintentos + 1

    def _recibir_luz(self, trama: bytes) -> bool:
        """Procesa una trama que llega por la luz. True si este Faro manda ACK."""
        self._ultimo_ack = b""
        if not crc_valido(trama) or len(trama) != 14 + trama[1]:
            self.estad[2] += 1
            if self.opciones & E.OPC_ENTREGAR_CRC_MALO:
                self._responder(E.EVT_TRAMA_RECIBIDA, b"\x00" + trama)
            return False
        self.estad[1] += 1
        promiscuo = self.opciones & E.OPC_PROMISCUO
        dst, src, tipo = trama[4:8], trama[8:12], trama[2] & TIPO_MASCARA
        para_mi = dst == self.direccion
        if trama[0] != VERSION or tipo == TIPO_ACK:
            if promiscuo:
                self._responder(E.EVT_TRAMA_RECIBIDA, b"\x01" + trama)
            return False
        if para_mi or dst == DIFUSION or promiscuo:
            self._responder(E.EVT_TRAMA_RECIBIDA, b"\x01" + trama)
        if para_mi and trama[2] & BANDERA_PIDE_ACK:
            self._ultimo_ack = Trama(destino=src, origen=self.direccion, tipo=TIPO_ACK,
                                     seq=trama[3]).a_bytes()
            return True
        return False

    def _panico(self) -> None:
        self.secreto = None
        self.direccion = self._direccion_aleatoria()
        self.estad = [0] * 6
        self._responder(E.EVT_PANICO, self.direccion)

    def _atender(self, cmd: int, d: bytes) -> None:
        if cmd == E.CMD_PING:
            self._responder(E.RSP_PONG, bytes([1, 0, VERSION, 128]))
        elif cmd == E.CMD_INFO:
            self._responder(E.RSP_INFO, self._info())
        elif cmd == E.CMD_ENVIAR:
            if len(d) < 5 or len(d) - 5 > MAX_CARGA:
                self._responder(E.RSP_RESULTADO_TX, bytes([E.TX_TRAMA_INVALIDA, 0, 0]))
                return
            seq = self.secuencia
            self.secuencia = (self.secuencia + 1) & 0xFF
            t = Trama(destino=d[:4], origen=self.direccion, carga=d[5:], tipo=TIPO_DATOS,
                      pide_ack=bool(d[4] & BANDERA_PIDE_ACK), seq=seq).a_bytes()
            estado, intentos = self._transmitir(t)
            self._responder(E.RSP_RESULTADO_TX, bytes([estado, intentos, seq]))
        elif cmd == E.CMD_ENVIAR_CRUDA:
            if not 14 <= len(d) <= 128 or len(d) != 14 + d[1]:
                self._responder(E.RSP_RESULTADO_TX, bytes([E.TX_TRAMA_INVALIDA, 0, 0]))
                return
            estado, intentos = self._transmitir(d)
            self._responder(E.RSP_RESULTADO_TX, bytes([estado, intentos, d[3]]))
        elif cmd == E.CMD_FIJAR_DIRECCION:
            if len(d) != 4 or not direccion_valida(d):
                self._responder(E.RSP_ERROR, bytes([0x04]))
                return
            self.direccion = bytes(d)
            self._responder(E.RSP_DIRECCION, self.direccion)
        elif cmd == E.CMD_ROTAR_DIRECCION:
            self.direccion = self._direccion_aleatoria()
            self._responder(E.RSP_DIRECCION, self.direccion)
        elif cmd == E.CMD_CONFIGURAR:
            if len(d) != 4:
                self._responder(E.RSP_ERROR, bytes([0x02]))
                return
            bps = int.from_bytes(d[:2], "big")
            if not E.BPS_MIN <= bps <= E.BPS_MAX or d[3] > 7:
                self._responder(E.RSP_ERROR, bytes([0x04]))
                return
            self.bps, self.opciones, self.reintentos = bps, d[2] & 0x03, d[3]
            self._responder(E.RSP_INFO, self._info())
        elif cmd in (E.CMD_ESTADISTICAS, E.CMD_REINICIAR_ESTAD):
            if cmd == E.CMD_REINICIAR_ESTAD:
                self.estad = [0] * 6
            self._responder(E.RSP_ESTADISTICAS, b"".join(v.to_bytes(4, "big") for v in self.estad))
        elif cmd == E.CMD_GUARDAR_SECRETO:
            if len(d) != 32:
                self._responder(E.RSP_ERROR, bytes([0x02]))
                return
            self.secreto = bytes(d)
            self._responder(E.RSP_SECRETO_GUARDADO)
        elif cmd == E.CMD_LEER_SECRETO:
            if self.secreto is None:
                self._responder(E.RSP_ERROR, bytes([0x05]))
            else:
                self._responder(E.RSP_SECRETO, self.secreto)
        elif cmd == E.CMD_PANICO:
            self._panico()
        elif cmd in (E.CMD_SONDEAR, E.CMD_EMISOR_FIJO):
            self._responder(E.RSP_SONDEO, (512).to_bytes(2, "big") + b"\x00")
        else:
            self._responder(E.RSP_ERROR, bytes([0x01]))
