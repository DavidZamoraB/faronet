"""Capa Scapy para la trama del Faro (opcional: pip install scapy).

Permite armar tramas "fuera del Faro" y transmitirlas tal cual:

    from dispositivo_luz_adaptador.scapy_faro import FaroTrama
    t = FaroTrama(dst=b"\\xff"*4, src=b"\\x01\\x02\\x03\\x04", seq=7, carga=b"hola")
    faro.enviar_trama(bytes(t))

Si no se indica `crc`, se calcula al construir la trama.
"""
from scapy.fields import (BitField, ByteField, FieldLenField, StrFixedLenField,
                          StrLenField, XShortField)
from scapy.packet import Packet

from .crc import crc16


class FaroTrama(Packet):
    name = "FaroTrama"
    fields_desc = [
        ByteField("ver", 1),
        FieldLenField("lon", None, length_of="carga", fmt="B"),
        BitField("banderas", 0, 4),   # bit 0 = pide ACK
        BitField("tipo", 0, 4),       # 0 = DATOS, 1 = ACK
        ByteField("seq", 0),
        StrFixedLenField("dst", b"\xff" * 4, 4),
        StrFixedLenField("src", b"\x00" * 4, 4),
        StrLenField("carga", b"", length_from=lambda p: p.lon),
        XShortField("crc", None),
    ]

    def post_build(self, p, pay):
        if self.crc is None:
            p = p[:-2] + crc16(p[:-2]).to_bytes(2, "big")
        return p + pay
