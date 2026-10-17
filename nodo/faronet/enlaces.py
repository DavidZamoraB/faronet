"""Enlaces entre vecinos de la mesh: TCP (Ethernet / WiFi), Faro (luz) y memoria.

Un enlace solo sabe mover celdas completas de CELDA bytes a su vecino, en
orden. Todo lo demas (rutas, circuitos) lo hace el nodo.
"""
from __future__ import annotations

import itertools
import queue
import socket
import threading
import time
from typing import Callable, Optional

from .celda import CELDA


class Enlace:
    """Interfaz comun. El nodo asigna `al_recibir` y `al_cerrar`."""

    costo = 1
    tipo = "?"

    def __init__(self):
        self.vecino: Optional[bytes] = None
        self.al_recibir: Callable[["Enlace", bytes], None] = lambda enlace, celda: None
        self.al_cerrar: Callable[["Enlace"], None] = lambda enlace: None
        self.abierto = True

    def enviar(self, celda: bytes) -> None:
        raise NotImplementedError

    def iniciar(self) -> None:
        """Empieza a recibir (despues de que el nodo asigno los callbacks)."""

    def cerrar(self) -> None:
        if self.abierto:
            self.abierto = False
            self.al_cerrar(self)

    def __str__(self) -> str:
        vecino = self.vecino.hex() if self.vecino else "?"
        return f"{self.tipo}({vecino})"


# ---------------------------------------------------------------------- #
# Memoria (pruebas)
# ---------------------------------------------------------------------- #
class EnlaceMemoria(Enlace):
    tipo = "mem"

    def __init__(self, costo: int = 1):
        super().__init__()
        self.costo = costo
        self.otro: Optional["EnlaceMemoria"] = None
        self._cola: "queue.Queue[bytes | None]" = queue.Queue()

    @classmethod
    def par(cls, costo: int = 1) -> tuple["EnlaceMemoria", "EnlaceMemoria"]:
        a, b = cls(costo), cls(costo)
        a.otro, b.otro = b, a
        return a, b

    def iniciar(self) -> None:
        threading.Thread(target=self._entregar, name="enlace-mem", daemon=True).start()

    def _entregar(self) -> None:
        while True:
            celda = self._cola.get()
            if celda is None or not self.abierto:
                return
            self.al_recibir(self, celda)

    def enviar(self, celda: bytes) -> None:
        if self.abierto and self.otro is not None and self.otro.abierto:
            self.otro._cola.put(celda)

    def cerrar(self) -> None:
        if self.abierto:
            self._cola.put(None)
            super().cerrar()
            if self.otro is not None:
                self.otro.cerrar()


# ---------------------------------------------------------------------- #
# TCP
# ---------------------------------------------------------------------- #
def parsear_host_puerto(texto: str) -> tuple[str, int]:
    host, _, puerto = texto.rpartition(":")
    if not host or not puerto.isdigit():
        raise ValueError(f"se esperaba HOST:PUERTO y llego {texto!r}")
    return host.strip("[]"), int(puerto)


class EnlaceTCP(Enlace):
    tipo = "tcp"

    def __init__(self, sock: socket.socket):
        super().__init__()
        self._sock = sock
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._lock = threading.Lock()

    @classmethod
    def conectar(cls, host: str, puerto: int, timeout: float = 5.0) -> "EnlaceTCP":
        sock = socket.create_connection((host, puerto), timeout=timeout)
        sock.settimeout(None)
        return cls(sock)

    def iniciar(self) -> None:
        threading.Thread(target=self._leer, name="enlace-tcp", daemon=True).start()

    def _leer(self) -> None:
        try:
            while self.abierto:
                celda = self._leer_exacto(CELDA)
                if celda is None:
                    break
                self.al_recibir(self, celda)
        except OSError:
            pass
        self.cerrar()

    def _leer_exacto(self, n: int) -> Optional[bytes]:
        datos = bytearray()
        while len(datos) < n:
            parte = self._sock.recv(n - len(datos))
            if not parte:
                return None
            datos += parte
        return bytes(datos)

    def enviar(self, celda: bytes) -> None:
        if not self.abierto:
            return
        try:
            with self._lock:
                self._sock.sendall(celda)
        except OSError:
            self.cerrar()

    def cerrar(self) -> None:
        if self.abierto:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            super().cerrar()


class ServidorTCP:
    """Acepta conexiones de vecinos y entrega un EnlaceTCP por cada una."""

    def __init__(self, host: str, puerto: int, al_conectar: Callable[[Enlace], None]):
        self._sock = socket.create_server((host, puerto), reuse_port=False)
        self.puerto = self._sock.getsockname()[1]
        self._al_conectar = al_conectar
        self._activo = True
        threading.Thread(target=self._aceptar, name="servidor-tcp", daemon=True).start()

    def _aceptar(self) -> None:
        while self._activo:
            try:
                sock, _ = self._sock.accept()  # la IP del vecino no se guarda
            except OSError:
                return
            self._al_conectar(EnlaceTCP(sock))

    def cerrar(self) -> None:
        self._activo = False
        self._sock.close()


# ---------------------------------------------------------------------- #
# Faro
# ---------------------------------------------------------------------- #
class EnlaceFaro(Enlace):
    """Enlace punto a punto por luz entre dos Faros.

    Una celda (512 bytes) no cabe en una trama (114 bytes de carga), asi que
    se parte en fragmentos:

        +-----------+-------------------+-----------------------+
        | ID_CELDA  | INDICE | TOTAL    | DATOS (hasta 112)     |
        | 1         | 4 bits | 4 bits   |                       |
        +-----------+-------------------+-----------------------+

    Las tramas van unicast con ACK a la ultima direccion fisica que se vio
    del otro Faro. Como las direcciones rotan, si no hay ACK el fragmento se
    repite por difusion. Mientras todavia no se conoce al otro Faro, se usa
    difusion.
    """

    tipo = "faro"
    DATOS_POR_TRAMA = 112
    ESPERA_FRAGMENTOS = 30.0

    def __init__(self, faro, costo: int = 4):
        from dispositivo_luz_adaptador import DIFUSION, MAX_CARGA

        super().__init__()
        assert self.DATOS_POR_TRAMA + 2 <= MAX_CARGA
        self._difusion = DIFUSION
        self.costo = costo
        self.faro = faro
        self.par: Optional[bytes] = None
        self._ids = itertools.count()
        self._cola: "queue.Queue[bytes | None]" = queue.Queue()
        self._partes: dict[tuple[bytes, int], tuple[float, int, dict[int, bytes]]] = {}
        self._lock = threading.Lock()

    def iniciar(self) -> None:
        self.faro.al_recibir(self._trama_recibida)
        threading.Thread(target=self._emisor, name="enlace-faro", daemon=True).start()

    def enviar(self, celda: bytes) -> None:
        if self.abierto:
            self._cola.put(celda)

    def _emisor(self) -> None:
        from dispositivo_luz_adaptador import ErrorFaro

        while True:
            celda = self._cola.get()
            if celda is None or not self.abierto:
                return
            id_celda = next(self._ids) & 0xFF
            partes = [celda[i:i + self.DATOS_POR_TRAMA]
                      for i in range(0, len(celda), self.DATOS_POR_TRAMA)]
            try:
                for indice, datos in enumerate(partes):
                    carga = bytes([id_celda, (indice << 4) | len(partes)]) + datos
                    destino = self.par or self._difusion
                    r = self.faro.enviar(destino, carga)
                    if not r.ok and destino != self._difusion:
                        self.faro.enviar(self._difusion, carga)
            except ErrorFaro:
                pass  # se pierde la celda; los circuitos que la usaban se reconstruyen

    def _trama_recibida(self, rec) -> None:
        trama = rec.trama if rec.crc_ok else None
        if trama is None or trama.es_ack or len(trama.carga) < 3:
            return
        self.par = trama.origen  # aprende la direccion actual del otro Faro
        id_celda, info = trama.carga[0], trama.carga[1]
        indice, total = info >> 4, info & 0x0F
        if total == 0 or indice >= total:
            return
        clave = (trama.origen, id_celda)
        ahora = time.monotonic()
        completa = None
        with self._lock:
            for k in [k for k, (t, _, _) in self._partes.items() if ahora - t > self.ESPERA_FRAGMENTOS]:
                del self._partes[k]
            inicio, esperado, partes = self._partes.get(clave, (ahora, total, {}))
            partes[indice] = trama.carga[2:]
            self._partes[clave] = (inicio, esperado, partes)
            if len(partes) == esperado:
                del self._partes[clave]
                completa = b"".join(partes[i] for i in range(esperado))
        if completa is not None and len(completa) == CELDA:
            self.al_recibir(self, completa)

    def cerrar(self) -> None:
        if self.abierto:
            self._cola.put(None)
            super().cerrar()
