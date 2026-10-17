"""Cliente del Worker de FaroNet en el edge.

El gateway firma cada peticion con su llave Ed25519 (la misma identidad del
nodo FaroNet), ver worker/src/seguridad.ts:

    "faronet-edge-v1\\n" METODO "\\n" RUTA "\\n" TIEMPO_MS "\\n" hex(SHA-256(cuerpo))

El buzon muerto no necesita firma: cualquiera con el secreto compartido
deposita o retira. Del secreto se derivan el identificador opaco del buzon y
la llave de cifrado, asi que el Worker nunca ve el contenido en claro.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from nacl.encoding import RawEncoder
from nacl.hash import blake2b
from nacl.secret import SecretBox
from nacl.exceptions import CryptoError

from faronet.cripto import Identidad

CONTEXTO = "faronet-edge-v1"
BLOB = 1024
BUZON_CLARO = BLOB - SecretBox.NONCE_SIZE - SecretBox.MACBYTES - 2  # 982 bytes de texto


class ErrorEdge(RuntimeError):
    def __init__(self, estado: int, mensaje: str):
        super().__init__(f"{estado}: {mensaje}")
        self.estado = estado


def _pedir(metodo: str, url: str, cuerpo: bytes | None = None, cabeceras: dict | None = None,
           timeout: float = 15.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read()
        try:
            mensaje = json.loads(cuerpo_error).get("error", "")
        except ValueError:
            mensaje = cuerpo_error.decode(errors="replace")
        raise ErrorEdge(e.code, mensaje) from None


class ClienteEdge:
    """Peticiones firmadas del gateway hacia el Worker."""

    def __init__(self, url: str, identidad: Identidad, timeout: float = 15.0):
        self.url = url.rstrip("/")
        self.identidad = identidad
        self.timeout = timeout
        self._ultimo_tiempo = 0
        self._lock = threading.Lock()

    @property
    def llave(self) -> str:
        """Lo que va en GATEWAYS del wrangler.toml."""
        return self.identidad.llave_firma.hex()

    def _tiempo(self) -> int:
        # El Worker exige tiempos estrictamente crecientes por gateway.
        with self._lock:
            t = max(int(time.time() * 1000), self._ultimo_tiempo + 1)
            self._ultimo_tiempo = t
            return t

    def _firmado(self, metodo: str, ruta: str, datos: dict) -> dict:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        tiempo = str(self._tiempo())
        ruta_firmada = urlsplit(self.url + ruta).path
        mensaje = "\n".join([CONTEXTO, metodo, ruta_firmada, tiempo, hashlib.sha256(cuerpo).hexdigest()])
        cabeceras = {
            "content-type": "application/json",
            "x-faronet-gateway": self.llave,
            "x-faronet-tiempo": tiempo,
            "x-faronet-firma": self.identidad.firmar(mensaje.encode()).hex(),
        }
        _, respuesta = _pedir(metodo, self.url + ruta, cuerpo, cabeceras, self.timeout)
        return json.loads(respuesta)

    def publicar(self, tema: str, texto: str, alias: str = "") -> str:
        """Publica en la sala publica `tema`. Devuelve el id del mensaje."""
        return self._firmado("POST", "/api/gateway/publicar", {"tema": tema, "texto": texto, "alias": alias})["id"]

    def subir_directorio(self, entradas: list[bytes]) -> dict:
        datos = {"entradas": [base64.b64encode(e).decode() for e in entradas]}
        return self._firmado("POST", "/api/gateway/directorio", datos)

    def directorio(self) -> list[dict]:
        _, r = _pedir("GET", self.url + "/api/directorio", timeout=self.timeout)
        return json.loads(r)["entradas"]

    def mensajes(self, tema: str) -> list[dict]:
        _, r = _pedir("GET", f"{self.url}/salas/{quote(tema)}/mensajes", timeout=self.timeout)
        return json.loads(r)["mensajes"]


# ---------------------------------------------------------------------- #
# Buzon muerto
# ---------------------------------------------------------------------- #
def _derivar(secreto: bytes, persona: bytes) -> bytes:
    return blake2b(secreto, digest_size=32, person=persona.ljust(16, b"\x00"), encoder=RawEncoder)


def id_buzon(secreto: bytes) -> str:
    """Identificador opaco del buzon: no revela el secreto."""
    return _derivar(secreto, b"faronet-buzon-id").hex()


def sellar_buzon(secreto: bytes, texto: bytes) -> bytes:
    """Blob cifrado de exactamente BLOB bytes (relleno: no filtra el largo)."""
    if len(texto) > BUZON_CLARO:
        raise ValueError(f"el mensaje del buzon mide mas de {BUZON_CLARO} bytes")
    claro = struct.pack(">H", len(texto)) + texto
    claro += bytes(BUZON_CLARO + 2 - len(claro))
    blob = SecretBox(_derivar(secreto, b"faronet-buzon-k")).encrypt(claro)
    assert len(blob) == BLOB
    return bytes(blob)


def abrir_buzon(secreto: bytes, blob: bytes) -> bytes:
    try:
        claro = SecretBox(_derivar(secreto, b"faronet-buzon-k")).decrypt(blob)
    except CryptoError as e:
        raise ValueError("el blob no corresponde a este secreto") from e
    (largo,) = struct.unpack_from(">H", claro)
    return claro[2:2 + largo]


def depositar(url: str, secreto: bytes, texto: bytes, ttl: int | None = None) -> None:
    destino = f"{url.rstrip('/')}/api/buzon/{id_buzon(secreto)}"
    if ttl is not None:
        destino += f"?ttl={int(ttl)}"
    _pedir("PUT", destino, sellar_buzon(secreto, texto), {"content-type": "application/octet-stream"})


def retirar(url: str, secreto: bytes) -> bytes | None:
    """Texto del buzon, o None si no hay nada. El Worker lo borra al leerlo."""
    try:
        _, blob = _pedir("GET", f"{url.rstrip('/')}/api/buzon/{id_buzon(secreto)}")
    except ErrorEdge as e:
        if e.estado == 404:
            return None
        raise
    return abrir_buzon(secreto, blob)
