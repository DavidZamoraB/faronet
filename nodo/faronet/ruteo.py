"""Enrutamiento dinamico de la mesh: vector de distancias (estilo RIP).

Cada nodo anuncia periodicamente a sus vecinos la distancia que conoce a
cada destino. La metrica es la suma del costo de los enlaces (TCP = 1,
Faro = 4 por defecto, porque es mucho mas lento). Se usa horizonte dividido
con envenenamiento en reversa para que las rutas caidas no "cuenten hasta
infinito", y las rutas que no se refrescan expiran.

Una celda siempre sale por el enlace de la ruta mas corta hacia su destino:
"el siguiente dispositivo que este mas cerca del destino".
"""
from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .celda import CUERPO, ID_LEN

if TYPE_CHECKING:
    from .enlaces import Enlace

INFINITO = 16
_ANUNCIO = struct.Struct(f">{ID_LEN}sB")
MAX_ANUNCIOS = (CUERPO - 1) // _ANUNCIO.size  # 53 destinos por celda RUTAS


@dataclass
class Ruta:
    metrica: int
    enlace: "Enlace"
    actualizada: float


class TablaRutas:
    def __init__(self, propio: bytes, expiracion: float = 30.0):
        self.propio = propio
        self.expiracion = expiracion
        self._rutas: dict[bytes, Ruta] = {}
        self._lock = threading.Lock()

    def vecino(self, id_vecino: bytes, enlace: "Enlace") -> None:
        """Ruta directa hacia un vecino recien saludado."""
        self.procesar_anuncio(enlace, [(id_vecino, 0)])

    def procesar_anuncio(self, enlace: "Enlace", anuncios: list[tuple[bytes, int]]) -> bool:
        """Devuelve True si la tabla cambio."""
        ahora = time.monotonic()
        cambio = False
        with self._lock:
            for destino, metrica in anuncios:
                if destino == self.propio:
                    continue
                nueva = min(INFINITO, metrica + enlace.costo)
                actual = self._rutas.get(destino)
                if actual is not None and actual.enlace is enlace:
                    # El mismo siguiente salto: su informacion siempre manda.
                    if nueva >= INFINITO:
                        del self._rutas[destino]
                        cambio = True
                    else:
                        cambio |= actual.metrica != nueva
                        actual.metrica, actual.actualizada = nueva, ahora
                elif nueva < INFINITO and (actual is None or nueva < actual.metrica):
                    self._rutas[destino] = Ruta(nueva, enlace, ahora)
                    cambio = True
        return cambio

    def siguiente(self, destino: bytes) -> "Enlace | None":
        with self._lock:
            ruta = self._rutas.get(destino)
            return ruta.enlace if ruta else None

    def metrica(self, destino: bytes) -> int:
        with self._lock:
            ruta = self._rutas.get(destino)
            return ruta.metrica if ruta else INFINITO

    def anuncio_para(self, enlace: "Enlace") -> list[tuple[bytes, int]]:
        """Lo que se le anuncia a un vecino (con envenenamiento en reversa)."""
        with self._lock:
            anuncios = [(self.propio, 0)]
            for destino, ruta in self._rutas.items():
                anuncios.append((destino, INFINITO if ruta.enlace is enlace else ruta.metrica))
        return anuncios

    def enlace_caido(self, enlace: "Enlace") -> None:
        with self._lock:
            for destino in [d for d, r in self._rutas.items() if r.enlace is enlace]:
                del self._rutas[destino]

    def purgar(self) -> None:
        limite = time.monotonic() - self.expiracion
        with self._lock:
            for destino in [d for d, r in self._rutas.items() if r.actualizada < limite]:
                del self._rutas[destino]

    def destinos(self) -> dict[bytes, tuple[int, "Enlace"]]:
        with self._lock:
            return {d: (r.metrica, r.enlace) for d, r in self._rutas.items()}

    def borrar(self) -> None:
        with self._lock:
            self._rutas.clear()


def codificar_anuncios(anuncios: list[tuple[bytes, int]]) -> list[bytes]:
    """Cuerpos de celdas RUTAS: cantidad(1) | (id(8) | metrica(1))*"""
    cuerpos = []
    for i in range(0, len(anuncios), MAX_ANUNCIOS):
        parte = anuncios[i:i + MAX_ANUNCIOS]
        cuerpos.append(bytes([len(parte)]) + b"".join(_ANUNCIO.pack(d, m) for d, m in parte))
    return cuerpos


def decodificar_anuncios(cuerpo: bytes) -> list[tuple[bytes, int]]:
    if not cuerpo:
        return []
    n = cuerpo[0]
    if 1 + n * _ANUNCIO.size > len(cuerpo):
        raise ValueError("celda RUTAS truncada")
    return [_ANUNCIO.unpack_from(cuerpo, 1 + i * _ANUNCIO.size) for i in range(n)]
