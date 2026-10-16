"""Protocolo nodo <-> Faro por USB-serial.

Cada paquete viaja como COBS(TIPO | DATOS | CRC16) + 0x00.
Debe coincidir con firmware/faro/enlace_serial.h.
"""
from __future__ import annotations

from . import cobs
from .crc import crc16

BAUDIOS = 115200
SECRETO_LEN = 32

# Comandos nodo -> Faro
CMD_PING = 0x01
CMD_INFO = 0x02
CMD_ENVIAR = 0x03
CMD_ENVIAR_CRUDA = 0x04
CMD_FIJAR_DIRECCION = 0x05
CMD_ROTAR_DIRECCION = 0x06
CMD_CONFIGURAR = 0x07
CMD_ESTADISTICAS = 0x08
CMD_REINICIAR_ESTAD = 0x09
CMD_GUARDAR_SECRETO = 0x0A
CMD_LEER_SECRETO = 0x0B
CMD_PANICO = 0x0C
CMD_SONDEAR = 0x0D
CMD_EMISOR_FIJO = 0x0E

# Respuestas Faro -> nodo
RSP_PONG = 0x81
RSP_INFO = 0x82
RSP_RESULTADO_TX = 0x83
RSP_DIRECCION = 0x85
RSP_ESTADISTICAS = 0x88
RSP_SECRETO_GUARDADO = 0x8A
RSP_SECRETO = 0x8B
RSP_SONDEO = 0x8D
RSP_ERROR = 0xFF

# Eventos asincronos
EVT_PANICO = 0x8C
EVT_TRAMA_RECIBIDA = 0x90
EVENTOS = (EVT_PANICO, EVT_TRAMA_RECIBIDA)

# Errores
ERRORES = {
    0x01: "comando desconocido",
    0x02: "longitud invalida",
    0x03: "CRC del enlace serial invalido",
    0x04: "parametro invalido",
    0x05: "no hay secreto guardado",
}

# Resultado de una transmision
TX_OK = 0x00
TX_SIN_ACK = 0x01
TX_CANAL_OCUPADO = 0x02
TX_TRAMA_INVALIDA = 0x03
TX_ABORTADO_PANICO = 0x04
ESTADOS_TX = {
    TX_OK: "ok",
    TX_SIN_ACK: "sin ACK",
    TX_CANAL_OCUPADO: "canal ocupado",
    TX_TRAMA_INVALIDA: "trama invalida",
    TX_ABORTADO_PANICO: "abortado por panico",
}

# Opciones de CMD_CONFIGURAR
OPC_PROMISCUO = 0x01
OPC_ENTREGAR_CRC_MALO = 0x02

BPS_MIN = 500
BPS_MAX = 20000


class ErrorEnlace(ValueError):
    pass


def empaquetar(tipo: int, datos: bytes = b"") -> bytes:
    cuerpo = bytes([tipo]) + bytes(datos)
    cuerpo += crc16(cuerpo).to_bytes(2, "big")
    return cobs.codificar(cuerpo) + b"\x00"


def desempaquetar(crudo: bytes) -> tuple[int, bytes]:
    """Recibe un paquete SIN el 0x00 final. Devuelve (tipo, datos)."""
    try:
        cuerpo = cobs.decodificar(crudo)
    except cobs.ErrorCOBS as e:
        raise ErrorEnlace(str(e)) from e
    if len(cuerpo) < 3:
        raise ErrorEnlace("paquete demasiado corto")
    if crc16(cuerpo) != 0:
        raise ErrorEnlace("CRC del paquete invalido")
    return cuerpo[0], cuerpo[1:-2]


class Delimitador:
    """Separa el flujo de bytes del puerto serial en paquetes."""

    def __init__(self, maximo: int = 512):
        self._buf = bytearray()
        self._maximo = maximo

    def alimentar(self, datos: bytes) -> list[bytes]:
        paquetes = []
        for b in datos:
            if b == 0:
                if self._buf:
                    paquetes.append(bytes(self._buf))
                self._buf.clear()
            elif len(self._buf) < self._maximo:
                self._buf.append(b)
            # si se pasa del maximo seguimos descartando hasta el proximo 0x00
        return paquetes
