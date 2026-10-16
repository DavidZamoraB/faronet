"""Trama de Capa 1 del Faro (version 1).

    0      1      2      3      4..7   8..11  12..           +2
    +------+------+------+------+------+------+------------+-------+
    | VER  | LON  | TIPO | SEQ  | DST  | SRC  |  CARGA     | CRC16 |
    +------+------+------+------+------+------+------------+-------+

Debe coincidir con firmware/faro/faro_core.h.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .crc import crc16

VERSION = 0x01
DIR_LEN = 4
CABECERA = 12
CRC_LEN = 2
MAX_TRAMA = 128
MAX_CARGA = MAX_TRAMA - CABECERA - CRC_LEN  # 114
MIN_TRAMA = CABECERA + CRC_LEN

TIPO_DATOS = 0x00
TIPO_ACK = 0x01
TIPO_MASCARA = 0x0F
BANDERA_PIDE_ACK = 0x10

DIFUSION = b"\xff\xff\xff\xff"


class ErrorTrama(ValueError):
    pass


def formatear_direccion(d: bytes) -> str:
    return ":".join(f"{b:02x}" for b in d)


def parsear_direccion(texto: str | bytes) -> bytes:
    """Acepta "a1:b2:c3:d4", "a1b2c3d4", "difusion"/"broadcast" o bytes."""
    if isinstance(texto, (bytes, bytearray)):
        d = bytes(texto)
    elif texto.lower() in ("difusion", "broadcast", "*"):
        d = DIFUSION
    else:
        try:
            d = bytes.fromhex(texto.replace(":", "").replace("-", ""))
        except ValueError as e:
            raise ErrorTrama(f"direccion invalida: {texto!r}") from e
    if len(d) != DIR_LEN:
        raise ErrorTrama(f"la direccion debe tener {DIR_LEN} bytes")
    return d


def direccion_valida(d: bytes) -> bool:
    return len(d) == DIR_LEN and d not in (b"\x00" * DIR_LEN, DIFUSION)


@dataclass
class Trama:
    destino: bytes
    origen: bytes
    carga: bytes = b""
    tipo: int = TIPO_DATOS
    pide_ack: bool = False
    seq: int = 0
    version: int = VERSION
    crc: int | None = field(default=None, compare=False)

    @property
    def es_ack(self) -> bool:
        return self.tipo == TIPO_ACK

    @property
    def es_difusion(self) -> bool:
        return self.destino == DIFUSION

    def a_bytes(self) -> bytes:
        """Serializa la trama calculando el CRC."""
        if len(self.carga) > MAX_CARGA:
            raise ErrorTrama(f"la carga mide {len(self.carga)} bytes; maximo {MAX_CARGA}")
        if len(self.destino) != DIR_LEN or len(self.origen) != DIR_LEN:
            raise ErrorTrama("las direcciones deben medir 4 bytes")
        tipo = (self.tipo & TIPO_MASCARA) | (BANDERA_PIDE_ACK if self.pide_ack else 0)
        cuerpo = bytes([self.version, len(self.carga), tipo, self.seq & 0xFF])
        cuerpo += self.destino + self.origen + self.carga
        return cuerpo + crc16(cuerpo).to_bytes(2, "big")

    @classmethod
    def desde_bytes(cls, datos: bytes, verificar_crc: bool = True) -> "Trama":
        if not MIN_TRAMA <= len(datos) <= MAX_TRAMA:
            raise ErrorTrama(f"longitud de trama invalida: {len(datos)}")
        lon = datos[1]
        if CABECERA + lon + CRC_LEN != len(datos):
            raise ErrorTrama("el campo LON no coincide con la longitud de la trama")
        crc = int.from_bytes(datos[-2:], "big")
        if verificar_crc and crc16(datos[:-2]) != crc:
            raise ErrorTrama("CRC invalido")
        return cls(
            version=datos[0],
            tipo=datos[2] & TIPO_MASCARA,
            pide_ack=bool(datos[2] & BANDERA_PIDE_ACK),
            seq=datos[3],
            destino=bytes(datos[4:8]),
            origen=bytes(datos[8:12]),
            carga=bytes(datos[12:12 + lon]),
            crc=crc,
        )

    def __str__(self) -> str:
        tipo = "ACK" if self.es_ack else "DATOS"
        return (f"v{self.version} {tipo} seq={self.seq} "
                f"{formatear_direccion(self.origen)} -> {formatear_direccion(self.destino)} "
                f"({len(self.carga)} B)")


def crc_valido(datos: bytes) -> bool:
    return len(datos) >= MIN_TRAMA and crc16(datos[:-2]) == int.from_bytes(datos[-2:], "big")
