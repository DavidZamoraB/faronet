"""Celda de FaroNet (version 1): el paquete de las capas 2 y 3.

Todas las celdas miden exactamente CELDA bytes, sin importar su contenido,
para no filtrar la longitud de los mensajes (minimizacion de metadatos).

    0      1      2      3      4 .. 11    12 .. 19   20 .. 23   24..25  26 ..
    +------+------+------+------+----------+----------+----------+-------+-----------+
    | VER  | CMD  | TTL  | RES  | DESTINO  | ORIGEN   | CIRCUITO | LON   | CUERPO    |
    +------+------+------+------+----------+----------+----------+-------+-----------+

DESTINO y ORIGEN son identificadores de nodo (8 bytes) de un solo tramo del
circuito (p. ej. cliente -> rele 1), nunca del mensaje de extremo a extremo.
LON indica cuantos bytes del CUERPO son significativos; el resto es relleno
aleatorio.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

VERSION = 0x01
CELDA = 512
ID_LEN = 8
CABECERA = 26
CUERPO = CELDA - CABECERA  # 486
TTL_INICIAL = 16

SIN_ID = b"\x00" * ID_LEN  # destino de las celdas que solo viajan un enlace

# Comandos de un solo enlace (no se rutean)
HOLA = 0x01
RUTAS = 0x02
DIRECTORIO = 0x03
RELLENO = 0x04
# Comandos ruteados por la mesh
CREAR = 0x10
CREADA = 0x11
RELE_IDA = 0x12
RELE_VUELTA = 0x13
DESTRUIR = 0x14
ENTREGA = 0x15

DE_ENLACE = {HOLA, RUTAS, DIRECTORIO, RELLENO}
NOMBRES = {
    HOLA: "HOLA", RUTAS: "RUTAS", DIRECTORIO: "DIRECTORIO", RELLENO: "RELLENO",
    CREAR: "CREAR", CREADA: "CREADA", RELE_IDA: "RELE_IDA", RELE_VUELTA: "RELE_VUELTA",
    DESTRUIR: "DESTRUIR", ENTREGA: "ENTREGA",
}

_FORMATO = struct.Struct(">BBBB8s8sIH")
assert _FORMATO.size == CABECERA


class ErrorCelda(ValueError):
    pass


def formatear_id(i: bytes) -> str:
    return i.hex()


def parsear_id(texto: str | bytes) -> bytes:
    if isinstance(texto, (bytes, bytearray)):
        i = bytes(texto)
    else:
        try:
            i = bytes.fromhex(texto)
        except ValueError as e:
            raise ErrorCelda(f"identificador invalido: {texto!r}") from e
    if len(i) != ID_LEN:
        raise ErrorCelda(f"el identificador debe tener {ID_LEN} bytes")
    return i


@dataclass
class Celda:
    comando: int
    destino: bytes = SIN_ID
    origen: bytes = SIN_ID
    circuito: int = 0
    cuerpo: bytes = b""
    ttl: int = TTL_INICIAL

    def a_bytes(self) -> bytes:
        if len(self.cuerpo) > CUERPO:
            raise ErrorCelda(f"el cuerpo mide {len(self.cuerpo)} bytes; el maximo es {CUERPO}")
        cabecera = _FORMATO.pack(VERSION, self.comando, self.ttl, 0, self.destino,
                                 self.origen, self.circuito, len(self.cuerpo))
        return cabecera + self.cuerpo + os.urandom(CUERPO - len(self.cuerpo))

    @classmethod
    def desde_bytes(cls, datos: bytes) -> "Celda":
        if len(datos) != CELDA:
            raise ErrorCelda(f"la celda mide {len(datos)} bytes; debe medir {CELDA}")
        version, cmd, ttl, _, destino, origen, circuito, lon = _FORMATO.unpack_from(datos)
        if version != VERSION:
            raise ErrorCelda(f"version de celda desconocida: {version}")
        if lon > CUERPO:
            raise ErrorCelda("LON fuera de rango")
        return cls(cmd, destino, origen, circuito, datos[CABECERA:CABECERA + lon], ttl)

    def __str__(self) -> str:
        return (f"{NOMBRES.get(self.comando, hex(self.comando))} "
                f"{formatear_id(self.origen)}->{formatear_id(self.destino)} "
                f"circ={self.circuito:08x} lon={len(self.cuerpo)} ttl={self.ttl}")
