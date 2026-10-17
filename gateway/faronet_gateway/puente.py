"""Puente FaroNet <-> edge, para correr en el nodo gateway (Raspberry Pi).

* Mensajes publicos: el nodo recibe PUBLICAR como salida de un circuito y el
  puente lo sube al Worker con una peticion firmada. El gateway no sabe quien
  origino el mensaje: solo lo recibe del salto anterior del circuito.
* Directorio: cada `intervalo` segundos sube al Worker todas las entradas
  firmadas que conoce, para la replica publica.

No guarda registros: ni mensajes, ni direcciones, ni respuestas del Worker.
"""
from __future__ import annotations

import threading

from faronet.mensaje import MensajePublico
from faronet.nodo import Nodo

from .edge import ClienteEdge, ErrorEdge

MAX_POR_PETICION = 200  # limite del Worker


class Puente:
    def __init__(self, nodo: Nodo, url: str, intervalo_directorio: float = 300.0,
                 primera_sincronizacion: float = 15.0):
        self.nodo = nodo
        self.cliente = ClienteEdge(url, nodo.identidad)
        self.intervalo = intervalo_directorio
        self.primera = primera_sincronizacion
        self._parar = threading.Event()
        nodo.al_publicar = self.publicar

    def iniciar(self) -> "Puente":
        threading.Thread(target=self._ciclo, name="puente-edge", daemon=True).start()
        return self

    def detener(self) -> None:
        self._parar.set()
        if self.nodo.al_publicar == self.publicar:
            self.nodo.al_publicar = None

    def publicar(self, mensaje: MensajePublico) -> bool:
        try:
            self.cliente.publicar(mensaje.tema, mensaje.texto, mensaje.alias)
            return True
        except (ErrorEdge, OSError, ValueError):
            return False

    def sincronizar_directorio(self) -> int:
        """Sube el directorio conocido. Devuelve cuantas entradas acepto el Worker."""
        entradas = [e.a_bytes() for e in self.nodo.directorio.entradas()]
        aceptadas = 0
        for i in range(0, len(entradas), MAX_POR_PETICION):
            aceptadas += self.cliente.subir_directorio(entradas[i:i + MAX_POR_PETICION])["aceptadas"]
        return aceptadas

    def _ciclo(self) -> None:
        espera = self.primera  # deja que el directorio se llene por la mesh
        while not self._parar.wait(espera):
            try:
                self.sincronizar_directorio()
            except (ErrorEdge, OSError, ValueError, AttributeError):
                pass  # sin conexion o identidad borrada por panico: se reintenta
            espera = self.intervalo
