"""Criptografia de FaroNet. Solo usa primitivas de libsodium (via PyNaCl).

* Identidad: una semilla de 32 bytes de la que se derivan la llave de firma
  (Ed25519, firma las entradas del directorio) y la llave onion (X25519, con
  la que se negocian los circuitos). Caben en el espacio secreto del Faro, que
  el boton de panico borra.
* Handshake de circuito (tipo ntor de Tor): el cliente manda una llave
  efimera; el rele responde con otra efimera y un autenticador que prueba que
  conoce su llave onion. Las llaves de sesion salen de dos Diffie-Hellman
  (efimera-efimera para secreto hacia adelante, efimera-estatica para
  autenticar al rele).
* Capas de la cebolla: XChaCha20-Poly1305 con nonce por contador. Cada capa
  agrega TAG bytes, y los reles rellenan para que la celda siga midiendo lo
  mismo (ver CapaOnion).
"""
from __future__ import annotations

import hmac
import os
import struct
from dataclasses import dataclass, field

import nacl.bindings as sodium
from nacl.exceptions import CryptoError
from nacl.hash import blake2b
from nacl.encoding import RawEncoder
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey

from .celda import ID_LEN

SEMILLA_LEN = 32
LLAVE_LEN = 32
TAG = sodium.crypto_aead_xchacha20poly1305_ietf_ABYTES  # 16
SOBRE_EXTRA = 48  # SealedBox: llave efimera (32) + MAC (16)

IDA = 0x01
VUELTA = 0x02


class ErrorCripto(Exception):
    """Fallo de autenticacion o datos criptograficos invalidos."""


def _h(datos: bytes, persona: bytes, largo: int = 32, llave: bytes = b"") -> bytes:
    return blake2b(datos, digest_size=largo, key=llave, person=persona.ljust(16, b"\x00"),
                   encoder=RawEncoder)


def id_de_llave(llave_firma: bytes) -> bytes:
    """Identificador de nodo: hash de su llave publica de firma."""
    return _h(llave_firma, b"faronet-id", ID_LEN)


class Identidad:
    """Llaves de largo plazo de un nodo."""

    def __init__(self, semilla: bytes):
        if len(semilla) != SEMILLA_LEN:
            raise ValueError("la semilla debe medir 32 bytes")
        self._semilla = bytearray(semilla)
        self.firma = SigningKey(bytes(semilla))
        self.onion = PrivateKey(_h(bytes(semilla), b"faronet-onion"))
        self.llave_firma = bytes(self.firma.verify_key)
        self.llave_onion = bytes(self.onion.public_key)
        self.id = id_de_llave(self.llave_firma)

    @classmethod
    def nueva(cls) -> "Identidad":
        return cls(os.urandom(SEMILLA_LEN))

    @property
    def semilla(self) -> bytes:
        return bytes(self._semilla)

    def firmar(self, datos: bytes) -> bytes:
        return self.firma.sign(datos).signature

    def abrir_sobre(self, sobre: bytes) -> bytes:
        try:
            return SealedBox(self.onion).decrypt(sobre)
        except CryptoError as e:
            raise ErrorCripto("sobre invalido") from e

    def borrar(self) -> None:
        """Sobrescribe la semilla. Python no garantiza borrar las copias que
        hizo internamente PyNaCl; por eso el nodo ademas termina el proceso."""
        for i in range(len(self._semilla)):
            self._semilla[i] = 0
        self.firma = self.onion = None  # type: ignore[assignment]


def verificar_firma(llave_firma: bytes, datos: bytes, firma: bytes) -> bool:
    try:
        VerifyKey(llave_firma).verify(datos, firma)
        return True
    except (CryptoError, ValueError):
        return False


def cerrar_sobre(llave_onion: bytes, datos: bytes) -> bytes:
    """Cifrado de extremo a extremo: solo el duenno de `llave_onion` lo abre."""
    return SealedBox(PublicKey(llave_onion)).encrypt(datos)


# ---------------------------------------------------------------------- #
# Handshake de circuito
# ---------------------------------------------------------------------- #
def _dh(privada: bytes, publica: bytes) -> bytes:
    secreto = sodium.crypto_scalarmult(privada, publica)
    if not any(secreto):  # punto de orden bajo: la otra parte hace trampa
        raise ErrorCripto("llave publica invalida en el handshake")
    return secreto


def _derivar(dh1: bytes, dh2: bytes, id_rele: bytes, b: bytes, x: bytes, y: bytes):
    transcrito = id_rele + b + x + y
    semilla = _h(dh1 + dh2 + transcrito, b"faronet-ntor", 64)
    ida = _h(semilla, b"faronet-k-ida")
    vuelta = _h(semilla, b"faronet-k-vuelta")
    auth = _h(transcrito, b"faronet-auth", 32, llave=semilla[:32])
    return ida, vuelta, auth


@dataclass
class HandshakeCliente:
    """Lado del cliente: crea la llave efimera y verifica la respuesta."""
    id_rele: bytes
    llave_onion_rele: bytes
    _efimera: PrivateKey = field(default_factory=PrivateKey.generate)

    @property
    def publica(self) -> bytes:
        return bytes(self._efimera.public_key)

    def completar(self, respuesta: bytes) -> "CapaOnion":
        if len(respuesta) != 64:
            raise ErrorCripto("respuesta de handshake con largo invalido")
        y, auth = respuesta[:32], respuesta[32:]
        x_priv = bytes(self._efimera)
        ida, vuelta, esperado = _derivar(_dh(x_priv, y), _dh(x_priv, self.llave_onion_rele),
                                         self.id_rele, self.llave_onion_rele, self.publica, y)
        if not hmac.compare_digest(auth, esperado):
            raise ErrorCripto("el rele no probo conocer su llave onion")
        return CapaOnion(ida, vuelta)


def handshake_rele(identidad: Identidad, x: bytes) -> tuple[bytes, "CapaOnion"]:
    """Lado del rele: devuelve (respuesta de 64 bytes, capa negociada)."""
    if len(x) != 32:
        raise ErrorCripto("llave efimera con largo invalido")
    y_priv = PrivateKey.generate()
    y = bytes(y_priv.public_key)
    ida, vuelta, auth = _derivar(_dh(bytes(y_priv), x), _dh(bytes(identidad.onion), x),
                                 identidad.id, identidad.llave_onion, x, y)
    return y + auth, CapaOnion(ida, vuelta)


# ---------------------------------------------------------------------- #
# Capa de la cebolla
# ---------------------------------------------------------------------- #
class CapaOnion:
    """Llaves de un salto del circuito, compartidas por el cliente y el rele.

    Cada sentido lleva su propio contador, que es el nonce. Los enlaces
    entregan las celdas en orden y sin duplicados, asi que no hace falta
    mandarlo en la celda; si una celda se pierde, el siguiente descifrado
    falla y el circuito se destruye.
    """

    def __init__(self, llave_ida: bytes, llave_vuelta: bytes):
        self._llaves = {IDA: llave_ida, VUELTA: llave_vuelta}
        self._contadores = {IDA: 0, VUELTA: 0}

    def _nonce(self, sentido: int) -> bytes:
        n = self._contadores[sentido]
        self._contadores[sentido] = n + 1
        return bytes([sentido]) + struct.pack(">Q", n) + bytes(15)

    def cifrar(self, sentido: int, datos: bytes) -> bytes:
        return sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(
            datos, None, self._nonce(sentido), self._llaves[sentido])

    def descifrar(self, sentido: int, datos: bytes) -> bytes:
        try:
            return sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(
                datos, None, self._nonce(sentido), self._llaves[sentido])
        except CryptoError as e:
            raise ErrorCripto("capa onion invalida (celda alterada o perdida)") from e
