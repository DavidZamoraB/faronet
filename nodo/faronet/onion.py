"""Capas de la cebolla sobre el cuerpo de las celdas RELE_IDA / RELE_VUELTA.

El cuerpo de una celda de rele siempre mide CUERPO bytes. Cada capa agrega
TAG bytes, asi que el salto `p` (contando desde 1 en el cliente) ve:

    IDA     llega:  [ cifrado para p: CUERPO-(p-1)*TAG ][ relleno ]
            sale:   [ cifrado para p+1: CUERPO-p*TAG  ][ relleno ]   (si no es para el)

    VUELTA  llega:  [ cifrado por p+1: CUERPO-p*TAG   ][ relleno ]
            sale:   [ cifrado por p:   CUERPO-(p-1)*TAG ][ relleno ]

El relleno es aleatorio y se renueva en cada salto, de modo que un
observador no puede seguir una celda comparando bytes, y todas las celdas
miden lo mismo.

Cuando un salto quita su capa y el resultado empieza con RECONOCIDO (4 bytes
en cero), el mensaje es para el. Si no, es el cifrado del siguiente salto (y
la probabilidad de que un cifrado empiece con 4 ceros es 2^-32; si pasa, el
mensaje no se puede interpretar y el circuito se destruye).

Mensaje de rele (texto en claro de una capa):

    +-------------+---------+-------+-------------+----------+
    | RECONOCIDO  | COMANDO | LON   | DATOS       | relleno  |
    | 4 x 0x00    | 1       | 2     | LON bytes   |          |
    +-------------+---------+-------+-------------+----------+
"""
from __future__ import annotations

import os
import struct

from .celda import CUERPO, ID_LEN
from .cripto import IDA, SOBRE_EXTRA, TAG, VUELTA, CapaOnion

RECONOCIDO = b"\x00\x00\x00\x00"
CABECERA_RELE = 7
MAX_SALTOS = 5
MIN_SALTOS = 3

# Comandos de rele
EXTENDER = 0x01   # cliente -> salto p: destino(8) | x(32) | posicion(1)
EXTENDIDO = 0x02  # salto p -> cliente: respuesta del handshake (64)
ENTREGAR = 0x03   # cliente -> salida: destino(8) | sobre(SOBRE)
ENTREGADO = 0x04  # salida -> cliente: estado(1)
ERROR = 0x05      # salto p -> cliente: codigo(1)

# Estados de ENTREGADO
ENTREGA_OK = 0
ENTREGA_SIN_RUTA = 1

# El sobre (mensaje de extremo a extremo) mide siempre lo mismo, calculado
# para el circuito mas largo permitido.
SOBRE = CUERPO - MAX_SALTOS * TAG - CABECERA_RELE - ID_LEN  # 391
SOBRE_CLARO = SOBRE - SOBRE_EXTRA  # 343


class ErrorOnion(ValueError):
    pass


def largo_claro(posicion: int) -> int:
    """Bytes de texto en claro que lleva el salto `posicion`."""
    return CUERPO - posicion * TAG


def armar_mensaje(comando: int, datos: bytes, posicion: int) -> bytes:
    largo = largo_claro(posicion)
    if CABECERA_RELE + len(datos) > largo:
        raise ErrorOnion(f"los datos no caben en el salto {posicion}")
    msg = RECONOCIDO + struct.pack(">BH", comando, len(datos)) + datos
    return msg + os.urandom(largo - len(msg))


def leer_mensaje(claro: bytes) -> tuple[int, bytes] | None:
    """(comando, datos) si el mensaje es para este salto, si no None."""
    if claro[:4] != RECONOCIDO:
        return None
    comando, lon = struct.unpack_from(">BH", claro, 4)
    if CABECERA_RELE + lon > len(claro):
        raise ErrorOnion("LON del mensaje de rele fuera de rango")
    return comando, claro[CABECERA_RELE:CABECERA_RELE + lon]


def _rellenar(datos: bytes) -> bytes:
    return datos + os.urandom(CUERPO - len(datos))


# ---- lado del cliente ----
def envolver(capas: list[CapaOnion], comando: int, datos: bytes) -> bytes:
    """Cuerpo para un mensaje dirigido al salto len(capas)."""
    datos = armar_mensaje(comando, datos, len(capas))
    for capa in reversed(capas):
        datos = capa.cifrar(IDA, datos)
    return datos


def desenvolver(capas: list[CapaOnion], cuerpo: bytes) -> tuple[int, int, bytes]:
    """Quita capas de un cuerpo de vuelta hasta reconocerlo.

    Devuelve (posicion del salto que lo origino, comando, datos)."""
    datos = cuerpo
    for posicion, capa in enumerate(capas, start=1):
        datos = capa.descifrar(VUELTA, datos[:largo_claro(posicion - 1)])
        mensaje = leer_mensaje(datos)
        if mensaje is not None:
            return (posicion, *mensaje)
    raise ErrorOnion("ningun salto del circuito reconoce el mensaje")


# ---- lado del rele ----
def quitar_capa(capa: CapaOnion, posicion: int, cuerpo: bytes) -> tuple[tuple[int, bytes] | None, bytes]:
    """Celda de ida en el salto `posicion`.

    Devuelve (mensaje si es para este salto, cuerpo para reenviar si no)."""
    claro = capa.descifrar(IDA, cuerpo[:largo_claro(posicion - 1)])
    mensaje = leer_mensaje(claro)
    return mensaje, (b"" if mensaje else _rellenar(claro))


def agregar_capa(capa: CapaOnion, posicion: int, cuerpo: bytes) -> bytes:
    """Celda de vuelta que viene del salto siguiente."""
    return _rellenar(capa.cifrar(VUELTA, cuerpo[:largo_claro(posicion)]))


def originar(capa: CapaOnion, posicion: int, comando: int, datos: bytes) -> bytes:
    """Mensaje de vuelta que nace en el salto `posicion`."""
    return _rellenar(capa.cifrar(VUELTA, armar_mensaje(comando, datos, posicion)))
