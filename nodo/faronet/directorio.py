"""Directorio de nodos de FaroNet.

Cada nodo publica una entrada firmada con su llave Ed25519. Las entradas se
difunden por la mesh (celdas DIRECTORIO, inundacion con supresion de
duplicados), asi que cada nodo tiene una copia del directorio y no hay un
servidor central que pueda mentir: una entrada alterada no verifica.

Formato de una entrada (version 1):

    +-----+------+-------------+-------------+-------+-----------+--------+---------+--------+--------+
    | VER | ID   | LLAVE FIRMA | LLAVE ONION | ROLES | PUBLICADA | EXPIRA | LON_NOM | NOMBRE | FIRMA  |
    | 1   | 8    | 32          | 32          | 1     | 4         | 4      | 1       | LON    | 64     |
    +-----+------+-------------+-------------+-------+-----------+--------+---------+--------+--------+

La FIRMA cubre todos los bytes anteriores. ID DEBE ser id_de_llave(LLAVE FIRMA).
Las entradas no llevan direcciones IP ni fisicas: los nodos se alcanzan por
ID usando las rutas de la mesh.
"""
from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass

from .celda import ID_LEN
from .cripto import Identidad, id_de_llave, verificar_firma

VERSION = 0x01
ROL_RELE = 0x01
ROL_GATEWAY = 0x02
MAX_NOMBRE = 32
VIGENCIA = 10 * 60          # una entrada dura 10 minutos...
MAX_VIGENCIA = 60 * 60      # ...y se rechazan las que pidan mas de una hora
TOLERANCIA_RELOJ = 5 * 60

_FIJO = struct.Struct(f">B{ID_LEN}s32s32sBIIB")
FIRMA_LEN = 64


class ErrorDirectorio(ValueError):
    pass


@dataclass(frozen=True)
class Entrada:
    id: bytes
    llave_firma: bytes
    llave_onion: bytes
    roles: int
    publicada: int
    expira: int
    nombre: str
    firma: bytes

    @staticmethod
    def _sin_firma(id_, llave_firma, llave_onion, roles, publicada, expira, nombre: bytes) -> bytes:
        return _FIJO.pack(VERSION, id_, llave_firma, llave_onion, roles, publicada, expira,
                          len(nombre)) + nombre

    @classmethod
    def publicar(cls, identidad: Identidad, nombre: str = "", roles: int = ROL_RELE,
                 vigencia: int = VIGENCIA, ahora: float | None = None) -> "Entrada":
        nom = nombre.encode()
        if len(nom) > MAX_NOMBRE:
            raise ErrorDirectorio(f"el nombre mide mas de {MAX_NOMBRE} bytes")
        publicada = int(ahora if ahora is not None else time.time())
        datos = cls._sin_firma(identidad.id, identidad.llave_firma, identidad.llave_onion,
                               roles, publicada, publicada + vigencia, nom)
        return cls(identidad.id, identidad.llave_firma, identidad.llave_onion, roles,
                   publicada, publicada + vigencia, nombre, identidad.firmar(datos))

    def a_bytes(self) -> bytes:
        return self._sin_firma(self.id, self.llave_firma, self.llave_onion, self.roles,
                               self.publicada, self.expira, self.nombre.encode()) + self.firma

    @classmethod
    def desde_bytes(cls, datos: bytes, ahora: float | None = None) -> "Entrada":
        """Interpreta y VERIFICA una entrada. Lanza ErrorDirectorio si no es valida."""
        if len(datos) < _FIJO.size + FIRMA_LEN:
            raise ErrorDirectorio("entrada demasiado corta")
        version, id_, firma_pub, onion_pub, roles, publicada, expira, lon = _FIJO.unpack_from(datos)
        if version != VERSION:
            raise ErrorDirectorio(f"version de entrada desconocida: {version}")
        fin = _FIJO.size + lon
        if lon > MAX_NOMBRE or len(datos) != fin + FIRMA_LEN:
            raise ErrorDirectorio("largo de entrada invalido")
        firma = datos[fin:]
        if id_ != id_de_llave(firma_pub):
            raise ErrorDirectorio("el ID no corresponde a la llave de firma")
        if not verificar_firma(firma_pub, datos[:fin], firma):
            raise ErrorDirectorio("firma invalida")
        ahora = ahora if ahora is not None else time.time()
        if expira <= ahora:
            raise ErrorDirectorio("entrada vencida")
        if publicada > ahora + TOLERANCIA_RELOJ or expira - publicada > MAX_VIGENCIA:
            raise ErrorDirectorio("fechas de la entrada fuera de rango")
        try:
            nombre = datos[_FIJO.size:fin].decode()
        except UnicodeDecodeError as e:
            raise ErrorDirectorio("nombre invalido") from e
        return cls(id_, firma_pub, onion_pub, roles, publicada, expira, nombre, firma)

    def es(self, rol: int) -> bool:
        return bool(self.roles & rol)


class Directorio:
    """Copia local del directorio. Las entradas vencidas se descartan solas."""

    def __init__(self):
        self._entradas: dict[bytes, Entrada] = {}
        self._lock = threading.Lock()

    def agregar(self, entrada: Entrada) -> bool:
        """True si la entrada es nueva o mas reciente que la que habia."""
        with self._lock:
            actual = self._entradas.get(entrada.id)
            if actual is not None and actual.publicada >= entrada.publicada:
                return False
            self._entradas[entrada.id] = entrada
            return True

    def agregar_bytes(self, datos: bytes) -> Entrada | None:
        try:
            entrada = Entrada.desde_bytes(datos)
        except ErrorDirectorio:
            return None
        return entrada if self.agregar(entrada) else None

    def purgar(self, ahora: float | None = None) -> None:
        ahora = ahora if ahora is not None else time.time()
        with self._lock:
            for id_ in [i for i, e in self._entradas.items() if e.expira <= ahora]:
                del self._entradas[id_]

    def entradas(self) -> list[Entrada]:
        self.purgar()
        with self._lock:
            return list(self._entradas.values())

    def buscar(self, texto: str | bytes) -> Entrada | None:
        """Por ID (hex o bytes) o por nombre."""
        for e in self.entradas():
            if texto in (e.id, e.id.hex(), e.nombre):
                return e
        return None

    def borrar(self) -> None:
        with self._lock:
            self._entradas.clear()
