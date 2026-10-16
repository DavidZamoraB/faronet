"""DispositivoLuzAdaptador: comunicacion entre el nodo y el Faro.

Uso basico:

    from dispositivo_luz_adaptador import DispositivoLuzAdaptador

    with DispositivoLuzAdaptador("/dev/ttyUSB0") as faro:
        print(faro.info())
        faro.enviar("a1:b2:c3:d4", b"hola")
        trama = faro.recibir(timeout=5)
"""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import enlace as E
from .trama import (DIFUSION, MAX_CARGA, MAX_TRAMA, MIN_TRAMA, Trama, ErrorTrama,
                    crc_valido, direccion_valida, formatear_direccion, parsear_direccion)


class ErrorFaro(RuntimeError):
    """El Faro respondio con un error o no respondio."""


@dataclass
class InfoFirmware:
    version_firmware: str
    version_protocolo: int
    max_trama: int


@dataclass
class InfoFaro:
    direccion: bytes
    bps: int
    promiscuo: bool
    entregar_crc_malo: bool
    reintentos: int
    secreto_presente: bool

    def __str__(self) -> str:
        return (f"direccion={formatear_direccion(self.direccion)} bps={self.bps} "
                f"reintentos={self.reintentos} promiscuo={self.promiscuo} "
                f"entregar_crc_malo={self.entregar_crc_malo} "
                f"secreto={'si' if self.secreto_presente else 'no'}")


@dataclass
class ResultadoTx:
    estado: int
    intentos: int
    seq: int

    @property
    def ok(self) -> bool:
        return self.estado == E.TX_OK

    def __str__(self) -> str:
        return f"{E.ESTADOS_TX.get(self.estado, hex(self.estado))} (intentos={self.intentos}, seq={self.seq})"


@dataclass
class TramaRecibida:
    crudo: bytes
    crc_ok: bool
    recibida_en: float

    @property
    def trama(self) -> Optional[Trama]:
        """La trama interpretada, o None si esta corrupta o es de otra version."""
        try:
            return Trama.desde_bytes(self.crudo, verificar_crc=self.crc_ok)
        except ErrorTrama:
            return None


@dataclass
class Estadisticas:
    tramas_tx: int
    tramas_rx: int
    crc_malos: int
    sin_ack: int
    retransmisiones: int
    truncadas: int


class DispositivoLuzAdaptador:
    """Interfaz de red sobre el Faro.

    `puerto` es la ruta del puerto serial (p. ej. /dev/ttyUSB0) o un objeto
    con la interfaz de pyserial (read/write/close), como el FaroSimulado.
    """

    MTU = MAX_CARGA

    def __init__(self, puerto, baudios: int = E.BAUDIOS, timeout: float = 2.0,
                 esperar_reinicio: float = 2.0):
        self._puerto_nombre = puerto
        self._baudios = baudios
        self.timeout = timeout
        self._esperar_reinicio = esperar_reinicio
        self._serial = None
        self._hilo: Optional[threading.Thread] = None
        self._activo = False
        self._lock_cmd = threading.Lock()
        self._respuestas: "queue.Queue[tuple[int, bytes]]" = queue.Queue()
        self._recibidas: "queue.Queue[TramaRecibida]" = queue.Queue()
        self._al_recibir: list[Callable[[TramaRecibida], None]] = []
        self._al_panico: list[Callable[[bytes], None]] = []
        self._rotacion: Optional[threading.Timer] = None
        self._info: Optional[InfoFaro] = None

    # ------------------------------------------------------------------ #
    # Conexion
    # ------------------------------------------------------------------ #
    def abrir(self) -> "DispositivoLuzAdaptador":
        if isinstance(self._puerto_nombre, str):
            import serial  # pyserial

            self._serial = serial.Serial(self._puerto_nombre, self._baudios, timeout=0.05)
            # El Arduino Nano se reinicia al abrir el puerto (DTR).
            time.sleep(self._esperar_reinicio)
            self._serial.reset_input_buffer()
        else:
            self._serial = self._puerto_nombre
        self._activo = True
        self._hilo = threading.Thread(target=self._leer, name="faro-lector", daemon=True)
        self._hilo.start()
        self._sincronizar()
        return self

    def cerrar(self) -> None:
        self.detener_rotacion()
        self._activo = False
        if self._hilo:
            self._hilo.join(timeout=1)
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def __enter__(self):
        return self.abrir()

    def __exit__(self, *exc):
        self.cerrar()

    def _sincronizar(self) -> None:
        """Manda PING hasta que el Faro conteste (puede seguir arrancando)."""
        limite = time.monotonic() + max(self.timeout, 3.0)
        ultimo_error: Exception | None = None
        while time.monotonic() < limite:
            try:
                self.ping(timeout=0.5)
                return
            except ErrorFaro as e:
                ultimo_error = e
        raise ErrorFaro(f"el Faro no responde en {self._puerto_nombre}: {ultimo_error}")

    # ------------------------------------------------------------------ #
    # Hilo lector
    # ------------------------------------------------------------------ #
    def _leer(self) -> None:
        delimitador = E.Delimitador()
        while self._activo:
            try:
                datos = self._serial.read(256)
            except Exception:  # puerto desconectado
                if self._activo:
                    self._respuestas.put((E.RSP_ERROR, b"\xfe"))
                break
            if not datos:
                continue
            for crudo in delimitador.alimentar(datos):
                try:
                    tipo, cuerpo = E.desempaquetar(crudo)
                except E.ErrorEnlace:
                    continue  # ruido en el puerto: se descarta
                if tipo == E.EVT_TRAMA_RECIBIDA:
                    self._entregar(cuerpo)
                elif tipo == E.EVT_PANICO:
                    self._panico_recibido(cuerpo)
                else:
                    self._respuestas.put((tipo, cuerpo))

    def _entregar(self, cuerpo: bytes) -> None:
        if not cuerpo:
            return
        rec = TramaRecibida(crudo=cuerpo[1:], crc_ok=bool(cuerpo[0]), recibida_en=time.monotonic())
        if self._al_recibir:
            for cb in list(self._al_recibir):
                cb(rec)
        else:
            self._recibidas.put(rec)

    def _panico_recibido(self, nueva_direccion: bytes) -> None:
        self._info = None
        # Lo que estaba en cola era estado sensible: se descarta.
        while not self._recibidas.empty():
            try:
                self._recibidas.get_nowait()
            except queue.Empty:
                break
        for cb in list(self._al_panico):
            cb(nueva_direccion)

    # ------------------------------------------------------------------ #
    # Comandos
    # ------------------------------------------------------------------ #
    def _comando(self, cmd: int, datos: bytes = b"", esperado: int | None = None,
                 timeout: float | None = None) -> bytes:
        if self._serial is None:
            raise ErrorFaro("el adaptador no esta abierto (use abrir() o 'with')")
        with self._lock_cmd:
            while not self._respuestas.empty():  # respuestas viejas (timeouts previos)
                self._respuestas.get_nowait()
            self._serial.write(E.empaquetar(cmd, datos))
            try:
                tipo, cuerpo = self._respuestas.get(timeout=timeout or self.timeout)
            except queue.Empty:
                raise ErrorFaro(f"sin respuesta al comando 0x{cmd:02x}") from None
        if tipo == E.RSP_ERROR:
            codigo = cuerpo[0] if cuerpo else 0
            raise ErrorFaro(E.ERRORES.get(codigo, f"error 0x{codigo:02x}"))
        if esperado is not None and tipo != esperado:
            raise ErrorFaro(f"respuesta inesperada 0x{tipo:02x} al comando 0x{cmd:02x}")
        return cuerpo

    def ping(self, timeout: float | None = None) -> InfoFirmware:
        r = self._comando(E.CMD_PING, esperado=E.RSP_PONG, timeout=timeout)
        return InfoFirmware(f"{r[0]}.{r[1]}", r[2], r[3])

    @staticmethod
    def _parsear_info(r: bytes) -> InfoFaro:
        return InfoFaro(
            direccion=bytes(r[0:4]),
            bps=int.from_bytes(r[4:6], "big"),
            promiscuo=bool(r[6] & E.OPC_PROMISCUO),
            entregar_crc_malo=bool(r[6] & E.OPC_ENTREGAR_CRC_MALO),
            reintentos=r[7],
            secreto_presente=bool(r[8]),
        )

    def info(self) -> InfoFaro:
        self._info = self._parsear_info(self._comando(E.CMD_INFO, esperado=E.RSP_INFO))
        return self._info

    @property
    def direccion(self) -> bytes:
        return (self._info or self.info()).direccion

    def configurar(self, bps: int | None = None, promiscuo: bool | None = None,
                   entregar_crc_malo: bool | None = None,
                   reintentos: int | None = None) -> InfoFaro:
        """Cambia solo los parametros indicados. Ambos Faros deben usar los mismos bps."""
        actual = self.info()
        bps = actual.bps if bps is None else bps
        if not E.BPS_MIN <= bps <= E.BPS_MAX:
            raise ValueError(f"bps debe estar entre {E.BPS_MIN} y {E.BPS_MAX}")
        promiscuo = actual.promiscuo if promiscuo is None else promiscuo
        entregar = actual.entregar_crc_malo if entregar_crc_malo is None else entregar_crc_malo
        reintentos = actual.reintentos if reintentos is None else reintentos
        opciones = (E.OPC_PROMISCUO if promiscuo else 0) | (E.OPC_ENTREGAR_CRC_MALO if entregar else 0)
        datos = bps.to_bytes(2, "big") + bytes([opciones, reintentos])
        self._info = self._parsear_info(self._comando(E.CMD_CONFIGURAR, datos, E.RSP_INFO))
        return self._info

    def _timeout_tx(self, n_bytes: int) -> float:
        """Peor caso de una transmision: esperas, reintentos y ACKs."""
        bps = (self._info.bps if self._info else E.BPS_MIN)
        reintentos = (self._info.reintentos if self._info else 7)
        bit = 1.0 / bps
        aire = (5 + n_bytes) * 8 * bit
        por_intento = aire + (64 * 24 + 32 + 12 + 48 + 19 * 8) * bit
        return 3.5 + (reintentos + 1) * por_intento + 1.0

    def enviar(self, destino: bytes | str, datos: bytes, pedir_ack: bool = True) -> ResultadoTx:
        """Envia `datos` (max. 114 bytes) a `destino`. La difusion nunca pide ACK."""
        destino = parsear_direccion(destino)
        if len(datos) > MAX_CARGA:
            raise ValueError(f"la carga mide {len(datos)} bytes; el maximo es {MAX_CARGA}")
        if self._info is None:
            self.info()
        banderas = 0x10 if (pedir_ack and destino != DIFUSION) else 0
        r = self._comando(E.CMD_ENVIAR, destino + bytes([banderas]) + bytes(datos),
                          E.RSP_RESULTADO_TX, timeout=self._timeout_tx(len(datos) + 14))
        return ResultadoTx(r[0], r[1], r[2])

    def enviar_trama(self, trama: Trama | bytes) -> ResultadoTx:
        """Transmite una trama armada fuera del Faro (p. ej. con Scapy) tal cual."""
        crudo = trama.a_bytes() if isinstance(trama, Trama) else bytes(trama)
        if not MIN_TRAMA <= len(crudo) <= MAX_TRAMA:
            raise ValueError("la trama debe medir entre 14 y 128 bytes")
        if self._info is None:
            self.info()
        r = self._comando(E.CMD_ENVIAR_CRUDA, crudo, E.RSP_RESULTADO_TX,
                          timeout=self._timeout_tx(len(crudo)))
        return ResultadoTx(r[0], r[1], r[2])

    def recibir(self, timeout: float | None = None) -> Optional[TramaRecibida]:
        """Siguiente trama recibida, o None si vence el timeout.

        No se usa si hay callbacks registrados con al_recibir()."""
        try:
            return self._recibidas.get(timeout=timeout)
        except queue.Empty:
            return None

    def al_recibir(self, callback: Callable[[TramaRecibida], None]) -> None:
        """Registra una funcion que se llama (desde el hilo lector) por cada trama."""
        self._al_recibir.append(callback)

    def al_panico(self, callback: Callable[[bytes], None]) -> None:
        """Registra una funcion que se llama cuando se presiona el boton de panico.

        El nodo DEBE usarla para borrar sus propias llaves y estado."""
        self._al_panico.append(callback)

    # ------------------------------------------------------------------ #
    # Direccion fisica
    # ------------------------------------------------------------------ #
    def fijar_direccion(self, direccion: bytes | str) -> bytes:
        d = parsear_direccion(direccion)
        if not direccion_valida(d):
            raise ValueError("la direccion no puede ser 00:00:00:00 ni la de difusion")
        r = self._comando(E.CMD_FIJAR_DIRECCION, d, E.RSP_DIRECCION)
        self._info = None
        return bytes(r)

    def rotar_direccion(self) -> bytes:
        """Direccion nueva tomada del generador criptografico del sistema."""
        while True:
            d = os.urandom(4)
            if direccion_valida(d):
                return self.fijar_direccion(d)

    def rotacion_automatica(self, cada_segundos: float,
                            al_rotar: Callable[[bytes], None] | None = None) -> None:
        """Rota la direccion periodicamente (con +-20% de variacion aleatoria
        para que el momento del cambio tampoco sirva para rastrear)."""
        self.detener_rotacion()

        def tarea():
            try:
                nueva = self.rotar_direccion()
                if al_rotar:
                    al_rotar(nueva)
            except ErrorFaro:
                pass
            if self._activo:
                self.rotacion_automatica(cada_segundos, al_rotar)

        variacion = 0.8 + 0.4 * (int.from_bytes(os.urandom(2), "big") / 0xFFFF)
        self._rotacion = threading.Timer(cada_segundos * variacion, tarea)
        self._rotacion.daemon = True
        self._rotacion.start()

    def detener_rotacion(self) -> None:
        if self._rotacion:
            self._rotacion.cancel()
            self._rotacion = None

    # ------------------------------------------------------------------ #
    # Secreto, panico, diagnostico
    # ------------------------------------------------------------------ #
    def guardar_secreto(self, secreto: bytes) -> None:
        """Guarda 32 bytes en la EEPROM del Faro (se borran con el panico)."""
        if len(secreto) != E.SECRETO_LEN:
            raise ValueError("el secreto debe medir 32 bytes")
        self._comando(E.CMD_GUARDAR_SECRETO, secreto, E.RSP_SECRETO_GUARDADO)
        self._info = None

    def leer_secreto(self) -> Optional[bytes]:
        try:
            return self._comando(E.CMD_LEER_SECRETO, esperado=E.RSP_SECRETO)
        except ErrorFaro as e:
            if "secreto" in str(e):
                return None
            raise

    def panico(self) -> None:
        """Igual que presionar el boton: borra secreto y direccion del Faro."""
        if self._serial is None:
            raise ErrorFaro("el adaptador no esta abierto")
        self._serial.write(E.empaquetar(E.CMD_PANICO))

    def estadisticas(self) -> Estadisticas:
        r = self._comando(E.CMD_ESTADISTICAS, esperado=E.RSP_ESTADISTICAS)
        return Estadisticas(*(int.from_bytes(r[i:i + 4], "big") for i in range(0, 24, 4)))

    def reiniciar_estadisticas(self) -> None:
        self._comando(E.CMD_REINICIAR_ESTAD, esperado=E.RSP_ESTADISTICAS)

    def sondear(self) -> tuple[int, int]:
        """(lectura analogica 0-1023 del fototransistor, salida del comparador)."""
        r = self._comando(E.CMD_SONDEAR, esperado=E.RSP_SONDEO)
        return int.from_bytes(r[0:2], "big"), r[2]

    def emisor_fijo(self, encendido: bool) -> tuple[int, int]:
        """Deja el LED IR encendido/apagado para medir con el multimetro.
        Devuelve la lectura del sensor propio, igual que sondear()."""
        r = self._comando(E.CMD_EMISOR_FIJO, bytes([1 if encendido else 0]), E.RSP_SONDEO)
        return int.from_bytes(r[0:2], "big"), r[2]


__all__ = [
    "DispositivoLuzAdaptador", "ErrorFaro", "InfoFaro", "InfoFirmware",
    "ResultadoTx", "TramaRecibida", "Estadisticas", "crc_valido",
]
