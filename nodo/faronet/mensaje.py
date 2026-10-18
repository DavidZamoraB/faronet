"""Mensajes de la aplicacion (capa 7) que viajan cifrados de extremo a extremo.

El texto en claro siempre mide SOBRE_CLARO bytes (relleno con ceros) y se
cierra con SealedBox hacia la llave onion del destinatario, asi que el sobre
mide siempre SOBRE bytes y nadie en el camino aprende el largo del texto.

    +-----+------+---------+-------+-----------+-----------+-------+-------+---------+
    | VER | TIPO | CREADO  | TTL   | LON_ALIAS | ALIAS     | LON   | TEXTO | relleno |
    | 1   | 1    | 4       | 4     | 1         | LON_ALIAS | 2     | LON   | ceros   |
    +-----+------+---------+-------+-----------+-----------+-------+-------+---------+

ALIAS es un seudonimo opcional que el remitente elige; FaroNet no le agrega
ninguna identidad del remitente.
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, field

from .cripto import Identidad, cerrar_sobre
from .onion import SOBRE, SOBRE_CLARO

VERSION = 0x01
PRIVADO = 0x01
TTL_DEFECTO = 24 * 3600
MAX_ALIAS = 32
_CABECERA = struct.Struct(">BBII")
MAX_TEXTO = SOBRE_CLARO - _CABECERA.size - 1 - 2  # sin alias


class ErrorMensaje(ValueError):
    pass


@dataclass
class Mensaje:
    texto: str
    alias: str = ""
    ttl: int = TTL_DEFECTO
    creado: int = field(default_factory=lambda: int(time.time()))
    tipo: int = PRIVADO

    def a_bytes(self) -> bytes:
        alias = self.alias.encode()
        texto = self.texto.encode()
        if len(alias) > MAX_ALIAS:
            raise ErrorMensaje(f"el alias mide mas de {MAX_ALIAS} bytes")
        datos = (_CABECERA.pack(VERSION, self.tipo, self.creado, self.ttl) +
                 bytes([len(alias)]) + alias + struct.pack(">H", len(texto)) + texto)
        if len(datos) > SOBRE_CLARO:
            raise ErrorMensaje(f"el mensaje no cabe: maximo {MAX_TEXTO - len(alias)} bytes de texto")
        return datos + bytes(SOBRE_CLARO - len(datos))

    @classmethod
    def desde_bytes(cls, datos: bytes) -> "Mensaje":
        try:
            version, tipo, creado, ttl = _CABECERA.unpack_from(datos)
            if version != VERSION:
                raise ErrorMensaje(f"version de mensaje desconocida: {version}")
            i = _CABECERA.size
            lon_alias = datos[i]
            alias = datos[i + 1:i + 1 + lon_alias].decode()
            i += 1 + lon_alias
            (lon,) = struct.unpack_from(">H", datos, i)
            if i + 2 + lon > len(datos):
                raise ErrorMensaje("LON del texto fuera de rango")
            texto = datos[i + 2:i + 2 + lon].decode()
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            raise ErrorMensaje("mensaje malformado") from e
        return cls(texto, alias, ttl, creado, tipo)

    def sellar(self, llave_onion_destino: bytes) -> bytes:
        return cerrar_sobre(llave_onion_destino, self.a_bytes())

    @classmethod
    def abrir(cls, identidad: Identidad, sobre: bytes) -> "Mensaje":
        return cls.desde_bytes(identidad.abrir_sobre(sobre))

    def vencido(self, ahora: float | None = None) -> bool:
        return (ahora or time.time()) > self.creado + self.ttl


# ---------------------------------------------------------------------- #
# Mensajes publicos (salen a clearnet por el gateway)
# ---------------------------------------------------------------------- #
TEMA = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
PUBLICO = SOBRE  # el mensaje publico tambien mide siempre lo mismo
MAX_TEXTO_PUBLICO = 500  # limite del Worker, en caracteres


@dataclass
class MensajePublico:
    """Mensaje para una sala publica. Viaja por el circuito hasta el gateway.

        +-----+----------+------+-----------+-------+-------+-------+---------+
        | VER | LON_TEMA | TEMA | LON_ALIAS | ALIAS | LON   | TEXTO | relleno |
        | 1   | 1        |      | 1         |       | 2     |       | ceros   |
        +-----+----------+------+-----------+-------+-------+-------+---------+

    No lleva identidad del remitente: el gateway solo ve el alias que el
    remitente eligio (o ninguno).
    """
    tema: str
    texto: str
    alias: str = ""

    def validar(self) -> None:
        if not TEMA.fullmatch(self.tema):
            raise ErrorMensaje("tema invalido: minusculas, numeros y guiones, maximo 32")
        if not self.texto.strip() or len(self.texto) > MAX_TEXTO_PUBLICO:
            raise ErrorMensaje(f"el texto debe tener entre 1 y {MAX_TEXTO_PUBLICO} caracteres")
        if len(self.alias.encode()) > MAX_ALIAS:
            raise ErrorMensaje(f"el alias mide mas de {MAX_ALIAS} bytes")

    def a_bytes(self) -> bytes:
        self.validar()
        tema, alias, texto = self.tema.encode(), self.alias.encode(), self.texto.encode()
        datos = (bytes([VERSION, len(tema)]) + tema + bytes([len(alias)]) + alias +
                 struct.pack(">H", len(texto)) + texto)
        if len(datos) > PUBLICO:
            raise ErrorMensaje(f"el mensaje publico no cabe: maximo {PUBLICO} bytes en total")
        return datos + bytes(PUBLICO - len(datos))

    @classmethod
    def desde_bytes(cls, datos: bytes) -> "MensajePublico":
        try:
            if datos[0] != VERSION:
                raise ErrorMensaje(f"version de mensaje publico desconocida: {datos[0]}")
            i = 1
            campos = []
            for largo_campo in (1, 1, 2):
                largo = int.from_bytes(datos[i:i + largo_campo], "big")
                i += largo_campo
                if i + largo > len(datos):
                    raise ErrorMensaje("campo fuera de rango")
                campos.append(datos[i:i + largo].decode())
                i += largo
        except (IndexError, UnicodeDecodeError) as e:
            raise ErrorMensaje("mensaje publico malformado") from e
        m = cls(campos[0], campos[2], campos[1])
        m.validar()
        return m


class Buzon:
    """Mensajes recibidos. Solo en memoria y con TTL: no hay registros en disco."""

    def __init__(self, ttl_maximo: int = TTL_DEFECTO):
        self.ttl_maximo = ttl_maximo
        self._mensajes: list[tuple[float, Mensaje]] = []

    def agregar(self, mensaje: Mensaje) -> None:
        mensaje.ttl = min(mensaje.ttl, self.ttl_maximo)
        self._mensajes.append((time.time(), mensaje))

    def purgar(self) -> None:
        ahora = time.time()
        self._mensajes = [(t, m) for t, m in self._mensajes
                          if ahora <= min(t, m.creado) + m.ttl]

    def mensajes(self) -> list[Mensaje]:
        self.purgar()
        return [m for _, m in self._mensajes]

    def borrar(self) -> None:
        self._mensajes.clear()
