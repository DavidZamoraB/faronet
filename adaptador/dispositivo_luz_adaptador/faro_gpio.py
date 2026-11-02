"""Faro controlado por los pines GPIO de una Raspberry Pi (sin Arduino).

La Raspberry hace lo mismo que el firmware del Arduino (firmware/faro):
codificacion Manchester, CSMA/CA con ACK, CRC, direccion fisica rotable,
boton de panico y LEDs TX/RX/estado. Habla con DispositivoLuzAdaptador con
el mismo protocolo serial que el firmware (hereda la logica de comandos de
FaroSimulado), asi que el nodo, el gateway y las herramientas no cambian:

    faronet --faro gpio --nombre gw --gateway ...
    faro gpio info

Los tiempos los maneja pigpio (demonio pigpiod): las tramas salen como
formas de onda por DMA y los flancos del receptor llegan con su marca de
tiempo en microsegundos, asi que la latencia de Linux no afecta la
decodificacion.

Pines por defecto (numeracion BCM) y pin del conector J1 de la placa:

    emisor     GPIO17 -> J1 D4 (base del transistor del LED IR)
    receptor   GPIO27 <- J1 D2 (salida del LM393, ver la nota de 3,3 V)
    boton      GPIO22 <- J1 D3 (boton de panico a tierra, pull-up interno)
    led_tx     GPIO5  -> J1 D5 (LED verde)
    led_rx     GPIO6  -> J1 D6 (LED azul)
    led_estado GPIO13 -> J1 D7 (LED rojo)

Los pines de la Raspberry son de 3,3 V. La salida del LM393 sube a 5 V por
R5, asi que DEBE pasar por un divisor (10 kOhm en serie y 20 kOhm a tierra)
antes de llegar a GPIO27. A0 no se conecta: la Raspberry no tiene entrada
analogica.

La direccion fisica y el secreto (lo que el Arduino guarda en su EEPROM) se
guardan en un archivo de la tarjeta SD con permisos 0600. El panico lo
sobrescribe con ceros antes de borrarlo.

Formato del puerto: "gpio[:emisor,receptor,boton,led_tx,led_rx,led_estado][@host]".
Con @host se usa el pigpiod de otra Raspberry (util para probar desde la
laptop).
"""
from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
from typing import Optional

from . import enlace as E
from .simulador import FaroSimulado
from .trama import (BANDERA_PIDE_ACK, DIFUSION, TIPO_ACK, TIPO_MASCARA, VERSION,
                    crc_valido, direccion_valida)

PREAMBULO = b"\x55" * 4
SFD = 0xD5
PATRON_SYNC = 0x55D5
LARGOS_PARA_SINCRONIZAR = 8
MAX_BITS_SIN_SFD = 64
MAX_TRAMA = 128

RANURA_BITS = 24
SIFS_BITS = 12
DIFS_BITS = 32
ACK_EXTRA_BITS = 48
VENTANA_INICIAL = 8
VENTANA_MAXIMA = 64
CANAL_OCUPADO_S = 3.0
DUPLICADOS = 8
ANTIRREBOTE_US = 50_000

PINES_DEFECTO = (17, 27, 22, 5, 6, 13)
NOMBRES_PINES = ("emisor", "receptor", "boton", "led_tx", "led_rx", "led_estado")
_MASCARA = 0xFFFFFFFF


def _transcurrido(desde: int, hasta: int) -> int:
    """Microsegundos entre dos ticks de 32 bits (negativo si `desde` es futuro)."""
    d = (hasta - desde) & _MASCARA
    return d - (1 << 32) if d >= 1 << 31 else d


# ---------------------------------------------------------------------- #
# Codificacion Manchester (igual que firmware/faro)
# ---------------------------------------------------------------------- #
def medio_bit_us(bps: int) -> int:
    return 500_000 // bps


def pulsos_manchester(trama: bytes, bps: int) -> list[tuple[int, int]]:
    """(nivel, microsegundos) de preambulo + SFD + trama. 0 = LED apagado.

    Bit 0: encendido -> apagado; bit 1: apagado -> encendido (IEEE 802.3),
    MSB primero. Termina con el LED apagado."""
    medio = medio_bit_us(bps)
    pulsos: list[list[int]] = []
    for byte in PREAMBULO + bytes([SFD]) + trama:
        for i in range(7, -1, -1):
            for nivel in ((0, 1) if (byte >> i) & 1 else (1, 0)):
                if pulsos and pulsos[-1][0] == nivel:
                    pulsos[-1][1] += medio
                else:
                    pulsos.append([nivel, medio])
    if pulsos[-1][0] == 1:
        pulsos.append([0, medio])
    return [(n, d) for n, d in pulsos]


def duracion_us(n_bytes: int, bps: int) -> int:
    return (len(PREAMBULO) + 1 + n_bytes) * 8 * 2 * medio_bit_us(bps)


class DecodificadorManchester:
    """Traduccion de DecodificadorManchester de firmware/faro/faro_core.cpp,
    con correccion de ancho de pulso.

    Se alimenta con flancos (microsegundos desde el anterior, nivel despues
    del flanco) y devuelve la trama completa cuando termina.

    Con poca luz el fototransistor tarda mas en apagarse que en encenderse:
    los periodos con luz llegan mas largos y los oscuros mas cortos (en el
    Faro 1 a 2000 bit/s: 615/385 us en vez de 500/500). El preambulo 0x55
    tiene periodos de luz y de oscuridad iguales, asi que de el se mide ese
    `sesgo` y se corrige en el resto de la trama."""

    CAZANDO, SINCRONIZADO, RECIBIENDO = range(3)

    def __init__(self, bps: int = 2000):
        self.configurar(bps)

    def configurar(self, bps: int) -> None:
        self.medio = medio_bit_us(bps)
        self.reiniciar()

    def reiniciar(self) -> None:
        self.estado = self.CAZANDO
        self.corrida_largos = 0
        self.esperando_corto = False
        self.invertido = 0
        self.bits_sin_sfd = 0
        self.registro = 0
        self.byte_actual = 0
        self.bits_en_byte = 0
        self.buf = bytearray()
        self.esperados = 0
        self.sesgo = 0.0           # us que la luz dura de mas (medido en el preambulo)
        self._con_luz: list[int] = []
        self._sin_luz: list[int] = []

    def clasificar(self, dt: int) -> int:
        """0 invalido, 1 corto (medio bit), 2 largo (bit completo); +-50%."""
        h = self.medio
        if h // 2 <= dt < h + h // 2:
            return 1
        if h + h // 2 <= dt < 2 * h + h // 2:
            return 2
        return 0

    def flanco(self, dt: int, nivel: int) -> Optional[bytes]:
        con_luz = 1 - nivel  # el periodo que termino tenia el nivel contrario
        if self.estado == self.CAZANDO:
            # En el preambulo todos los intervalos son de un bit completo; se
            # acepta de 1 a 3 medios bits para tolerar el sesgo antes de medirlo.
            h = self.medio
            if not h <= dt < 3 * h:
                self.corrida_largos = 0
                self._con_luz.clear()
                self._sin_luz.clear()
                return None
            (self._con_luz if con_luz else self._sin_luz).append(dt)
            self.corrida_largos += 1
            if self.corrida_largos < LARGOS_PARA_SINCRONIZAR:
                return None
            self._medir_sesgo()
            self.estado = self.SINCRONIZADO
            self.registro = 0
            self.bits_sin_sfd = 0
            self.esperando_corto = False
            return self._bit(nivel)
        clase = self.clasificar(round(dt - self.sesgo if con_luz else dt + self.sesgo))
        if clase == 0:
            self.reiniciar()
            return None
        if self.estado == self.SINCRONIZADO and clase == 2:
            # sigue el preambulo: mas muestras para promediar el sesgo
            (self._con_luz if con_luz else self._sin_luz).append(dt)
            self._medir_sesgo()
        if clase == 2:
            if self.esperando_corto:
                self.reiniciar()
                return None
            return self._bit(nivel)
        if not self.esperando_corto:
            self.esperando_corto = True
            return None
        self.esperando_corto = False
        return self._bit(nivel)

    def _medir_sesgo(self) -> None:
        luz, osc = self._con_luz[-16:], self._sin_luz[-16:]
        if luz and osc:
            sesgo = (sum(luz) / len(luz) - sum(osc) / len(osc)) / 2
            # Con ruido aleatorio el promedio da un sesgo falso pequeno: solo se
            # corrige uno claro (el del Faro 1 era 46 % de medio bit).
            if abs(sesgo) < 0.2 * self.medio:
                sesgo = 0.0
            self.sesgo = max(-0.45 * self.medio, min(0.45 * self.medio, sesgo))

    def _bit(self, nivel: int) -> Optional[bytes]:
        if self.estado == self.SINCRONIZADO:
            self.registro = ((self.registro << 1) | (nivel & 1)) & 0xFFFF
            if self.registro == PATRON_SYNC:
                self.invertido = 0
            elif self.registro == (~PATRON_SYNC & 0xFFFF):
                self.invertido = 1
            else:
                self.bits_sin_sfd += 1
                if self.bits_sin_sfd > MAX_BITS_SIN_SFD:
                    self.reiniciar()
                return None
            self.estado = self.RECIBIENDO
            self.byte_actual = self.bits_en_byte = self.esperados = 0
            self.buf = bytearray()
            return None
        self.byte_actual = ((self.byte_actual << 1) | ((nivel ^ self.invertido) & 1)) & 0xFF
        self.bits_en_byte += 1
        if self.bits_en_byte < 8:
            return None
        self.buf.append(self.byte_actual)
        self.byte_actual = self.bits_en_byte = 0
        if len(self.buf) == 2:
            total = 14 + self.buf[1]
            if total > MAX_TRAMA:
                self.reiniciar()
                return None
            self.esperados = total
        if self.esperados and len(self.buf) >= self.esperados:
            trama = bytes(self.buf)
            self.reiniciar()
            return trama
        return None

    @property
    def ocupado(self) -> bool:
        return self.estado != self.CAZANDO


# ---------------------------------------------------------------------- #
# Faro sobre GPIO
# ---------------------------------------------------------------------- #
class _MedioPropio:
    """FaroSimulado espera un medio; aqui el medio es la luz real."""

    def __init__(self):
        self.faros: list = []


def parsear_puerto(texto: str) -> tuple[tuple[int, ...], Optional[str]]:
    """'gpio[:17,27,22,5,6,13][@host]' -> (pines, host)."""
    if not texto.startswith("gpio"):
        raise ValueError(f"no es un puerto gpio: {texto!r}")
    resto = texto[4:]
    host = None
    if "@" in resto:
        resto, host = resto.split("@", 1)
    pines = PINES_DEFECTO
    if resto.startswith(":"):
        pines = tuple(int(p) for p in resto[1:].split(","))
        if len(pines) != len(PINES_DEFECTO):
            raise ValueError("gpio:EMISOR,RECEPTOR,BOTON,LED_TX,LED_RX,LED_ESTADO")
    elif resto:
        raise ValueError(f"puerto gpio invalido: {texto!r}")
    return pines, host


class FaroGPIO(FaroSimulado):
    """Faro real manejado por una Raspberry Pi. Interfaz tipo pyserial."""

    def __init__(self, pines: tuple[int, ...] = PINES_DEFECTO, bps: int = 2000,
                 archivo: Optional[str] = None, pi=None, host: Optional[str] = None):
        (self.p_emisor, self.p_receptor, self.p_boton,
         self.p_led_tx, self.p_led_rx, self.p_led_estado) = pines
        if pi is None:
            import pigpio  # demonio pigpiod

            pi = pigpio.pi(host) if host else pigpio.pi()
            if not pi.connected:
                raise OSError("no se pudo conectar a pigpiod (sudo systemctl enable --now pigpiod)")
        self.pi = pi
        self.archivo = archivo or os.path.expanduser(f"~/.faronet/faro-gpio-{self.p_emisor}.json")
        super().__init__(_MedioPropio(), bps=bps)
        self._cargar()

        self._decod = DecodificadorManchester(bps)
        self._lock_tx = threading.Lock()
        self._transmitiendo = False
        self._ultimo_tick: Optional[int] = None
        self._ultimo_valido = self.pi.get_current_tick() - (1 << 30)
        self._ignorar_hasta: Optional[int] = None
        self._ack = threading.Event()
        self._ack_esperado: Optional[tuple[bytes, int]] = None
        self._recientes: list[tuple[bytes, int]] = []
        self._cola: "queue.Queue[Optional[bytes]]" = queue.Queue()
        # Loopback: el Faro lee con su propio sensor lo que emite (reflejo).
        self.loopback = False
        self._eco: "queue.Queue[bytes]" = queue.Queue()
        self._activo = True
        self._preparar_pines()
        threading.Thread(target=self._procesador, name="faro-gpio-rx", daemon=True).start()

    @classmethod
    def desde_texto(cls, texto: str, **kw) -> "FaroGPIO":
        pines, host = parsear_puerto(texto)
        return cls(pines, host=host, **kw)

    # ---- pines ----
    def _preparar_pines(self) -> None:
        salida, entrada = 1, 0  # pigpio.OUTPUT, pigpio.INPUT
        for p in (self.p_emisor, self.p_led_tx, self.p_led_rx, self.p_led_estado):
            self.pi.set_mode(p, salida)
            self.pi.write(p, 0)
        self.pi.set_mode(self.p_receptor, entrada)
        self.pi.set_mode(self.p_boton, entrada)
        self.pi.set_pull_up_down(self.p_boton, 2)  # PUD_UP
        self.pi.set_glitch_filter(self.p_boton, ANTIRREBOTE_US)
        self._cb_rx = self.pi.callback(self.p_receptor, 2, self._flanco)   # EITHER_EDGE
        self._cb_boton = self.pi.callback(self.p_boton, 1, self._boton)   # FALLING_EDGE

    def close(self) -> None:
        self._activo = False
        self._cola.put(None)
        for cb in (self._cb_rx, self._cb_boton):
            cb.cancel()
        for p in (self.p_emisor, self.p_led_tx, self.p_led_rx):
            self.pi.write(p, 0)
        self.pi.stop()

    # ---- memoria no volatil (archivo en la SD) ----
    def _cargar(self) -> None:
        try:
            with open(self.archivo) as f:
                datos = json.load(f)
            d = bytes.fromhex(datos.get("direccion", ""))
            if direccion_valida(d):
                self.direccion = d
            if datos.get("secreto"):
                self.secreto = bytes.fromhex(datos["secreto"])
        except (OSError, ValueError):
            pass
        self._guardar()

    def _guardar(self) -> None:
        os.makedirs(os.path.dirname(self.archivo), mode=0o700, exist_ok=True)
        datos = json.dumps({"direccion": self.direccion.hex(),
                            "secreto": self.secreto.hex() if self.secreto else None})
        fd = os.open(self.archivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())

    def _borrar_archivo(self) -> None:
        """Sobrescribe con ceros y borra (lo mas cercano a zeroize en una SD)."""
        try:
            largo = os.path.getsize(self.archivo)
            with open(self.archivo, "r+b") as f:
                f.write(bytes(largo))
                f.flush()
                os.fsync(f.fileno())
            os.remove(self.archivo)
        except OSError:
            pass

    # ---- comandos ----
    def _atender(self, cmd: int, d: bytes) -> None:
        antes = (self.direccion, self.secreto)
        if cmd == E.CMD_SONDEAR:
            self._sondeo()
            return
        if cmd == E.CMD_EMISOR_FIJO:
            if len(d) != 1:
                self._responder(E.RSP_ERROR, bytes([0x02]))
                return
            with self._lock_tx:
                self.pi.write(self.p_emisor, 1 if d[0] else 0)
                self.pi.write(self.p_led_tx, 1 if d[0] else 0)
            time.sleep(0.005)
            self._sondeo()
            return
        super()._atender(cmd, d)
        if cmd == E.CMD_CONFIGURAR:
            self._decod.configurar(self.bps)
        if (self.direccion, self.secreto) != antes and cmd != E.CMD_PANICO:
            self._guardar()

    def _sondeo(self) -> None:
        """Sin entrada analogica: se informa 1023/0 segun la salida digital."""
        digital = 1 if self.pi.read(self.p_receptor) else 0
        self._responder(E.RSP_SONDEO, (1023 if digital else 0).to_bytes(2, "big") + bytes([digital]))

    def _boton(self, gpio, nivel, tick) -> None:
        threading.Thread(target=self._panico, name="faro-gpio-panico", daemon=True).start()

    def _panico(self) -> None:
        self.pi.write(self.p_emisor, 0)
        self._borrar_archivo()
        self._recientes.clear()
        self._decod.reiniciar()
        super()._panico()  # secreto None, direccion nueva, evento PANICO al nodo
        self._guardar()
        for i in range(6):
            self.pi.write(self.p_led_estado, 1)
            self.pi.write(self.p_led_tx, i & 1)
            self.pi.write(self.p_led_rx, (i + 1) & 1)
            time.sleep(0.12)
            self.pi.write(self.p_led_estado, 0)
            time.sleep(0.08)
        self.pi.write(self.p_led_tx, 0)
        self.pi.write(self.p_led_rx, 0)
        self.pi.write(self.p_led_estado, 1)  # queda encendido: Faro "en blanco"

    # ---- recepcion ----
    def _flanco(self, gpio, nivel, tick) -> None:
        if nivel not in (0, 1):
            return  # watchdog de pigpio
        if self._ignorar_hasta is not None and not self.loopback:
            if _transcurrido(tick, self._ignorar_hasta) > 0:
                self._ultimo_tick = tick
                return
            self._ignorar_hasta = None
        if self._transmitiendo and not self.loopback:
            self._ultimo_tick = tick
            return
        if self._ultimo_tick is None:
            self._ultimo_tick = tick
            return
        dt = _transcurrido(self._ultimo_tick, tick)
        self._ultimo_tick = tick
        # canal ocupado: intervalos con forma de Manchester (con margen para
        # el retraso del sensor, igual que el preambulo en el decodificador)
        if self._decod.medio // 2 <= dt < 3 * self._decod.medio:
            self._ultimo_valido = tick
        trama = self._decod.flanco(dt, nivel)
        if trama is not None:
            self._cola.put(trama)

    def _procesador(self) -> None:
        while self._activo:
            trama = self._cola.get()
            if trama is None:
                return
            try:
                self._procesar(trama)
            except Exception:  # un error con una trama no debe detener la recepcion
                pass

    def _procesar(self, trama: bytes) -> None:
        if self.loopback:
            self._eco.put(trama)  # se entrega tal cual, aunque el CRC este malo
            return
        self.pi.write(self.p_led_rx, 1)
        try:
            valida = crc_valido(trama) and len(trama) == 14 + trama[1]
            if valida and trama[8:12] == self.direccion:
                return  # eco de una trama propia
            if valida and trama[0] == VERSION and (trama[2] & TIPO_MASCARA) == TIPO_ACK:
                if self._ack_esperado == (trama[4:8], trama[3]):
                    self._ack.set()
            if valida and trama[0] == VERSION and trama[4:8] == self.direccion \
                    and trama[2] & BANDERA_PIDE_ACK and (trama[2] & TIPO_MASCARA) != TIPO_ACK:
                clave = (trama[8:12], trama[3])
                if clave in self._recientes:
                    # se perdio nuestro ACK: se repite, pero no se entrega dos veces
                    from .trama import Trama
                    ack = Trama(destino=trama[8:12], origen=self.direccion, tipo=TIPO_ACK,
                                seq=trama[3]).a_bytes()
                    self._enviar_ack(ack)
                    return
                self._recientes = (self._recientes + [clave])[-DUPLICADOS:]
            if super()._recibir_luz(trama):
                self._enviar_ack(self._ultimo_ack)
        finally:
            self.pi.write(self.p_led_rx, 0)

    def _enviar_ack(self, ack: bytes) -> None:
        time.sleep(SIFS_BITS * 2 * self._decod.medio / 1e6)
        self._emitir(ack)  # sin escuchar el canal: SIFS < DIFS le da prioridad

    # ---- transmision ----
    def _bit_s(self) -> float:
        return 2 * medio_bit_us(self.bps) / 1e6

    def _canal_libre(self) -> bool:
        if self._decod.ocupado or self._transmitiendo:
            return False
        return _transcurrido(self._ultimo_valido, self.pi.get_current_tick()) >= \
            DIFS_BITS * 2 * medio_bit_us(self.bps)

    def _esperar_canal(self, ventana: int) -> bool:
        limite = time.monotonic() + CANAL_OCUPADO_S
        ranuras = random.SystemRandom().randrange(ventana)
        while time.monotonic() < limite:
            if not self._canal_libre():
                time.sleep(self._bit_s())
                continue
            if ranuras == 0:
                return True
            time.sleep(RANURA_BITS * self._bit_s())
            if self._canal_libre():
                ranuras -= 1
        return False

    def _emitir(self, trama: bytes) -> None:
        with self._lock_tx:
            self._transmitiendo = True
            self.pi.write(self.p_led_tx, 1)
            try:
                mascara = 1 << self.p_emisor
                pulsos = [self._pulso(mascara if n else 0, 0 if n else mascara, us)
                          for n, us in pulsos_manchester(trama, self.bps)]
                self.pi.wave_add_new()
                self.pi.wave_add_generic(pulsos)
                wid = self.pi.wave_create()
                try:
                    self.pi.wave_send_once(wid)
                    while self.pi.wave_tx_busy():
                        time.sleep(0.001)
                finally:
                    self.pi.wave_delete(wid)
            finally:
                self.pi.write(self.p_emisor, 0)
                self.pi.write(self.p_led_tx, 0)
                if not self.loopback:
                    # el sensor ve el reflejo de su propio LED: se ignora un rato
                    self._ignorar_hasta = (self.pi.get_current_tick() + 4 * medio_bit_us(self.bps)) & _MASCARA
                    self._decod.reiniciar()
                self._transmitiendo = False

    @staticmethod
    def _pulso(encender: int, apagar: int, us: int):
        try:
            import pigpio

            return pigpio.pulse(encender, apagar, us)
        except ImportError:
            return (encender, apagar, us)

    def _transmitir(self, trama: bytes) -> tuple[int, int]:
        pide_ack = (trama[0] == VERSION and trama[2] & BANDERA_PIDE_ACK
                    and trama[4:8] != DIFUSION)
        espera_ack = (SIFS_BITS + ACK_EXTRA_BITS + 8 * (len(PREAMBULO) + 1 + 14)) * self._bit_s()
        ventana = VENTANA_INICIAL
        for intento in range(self.reintentos + 1):
            if intento:
                self.estad[4] += 1
            if not self._esperar_canal(ventana):
                return E.TX_CANAL_OCUPADO, intento + 1
            self.estad[0] += 1
            self._ack.clear()
            self._ack_esperado = (trama[8:12], trama[3])
            self._emitir(trama)
            if not pide_ack:
                return E.TX_OK, intento + 1
            if self._ack.wait(espera_ack + 0.05):  # +50 ms por la latencia de Linux
                return E.TX_OK, intento + 1
            ventana = min(ventana * 2, VENTANA_MAXIMA)
        self.estad[3] += 1
        return E.TX_SIN_ACK, self.reintentos + 1


# ---------------------------------------------------------------------- #
# Prueba de loopback: un solo Faro, leyendo su propio reflejo
# ---------------------------------------------------------------------- #
def probar_loopback(faro: FaroGPIO, tramas: int = 50, tam: int = 100, espera_s: float = 0.5,
                    al_avanzar=None) -> dict:
    """Emite `tramas` tramas de `tam` bytes de carga aleatoria y compara lo que
    lee el propio sensor. Devuelve conteos, BER y tasa efectiva.

    BER = bits distintos / bits comparados, solo sobre las tramas que llegaron
    completas (las perdidas se cuentan aparte)."""
    from .trama import Trama

    if not 0 < tam <= 114:
        raise ValueError("tam debe estar entre 1 y 114 bytes")
    faro.loopback = True
    faro._decod.reiniciar()
    while not faro._eco.empty():
        faro._eco.get_nowait()
    ok = crc_malo = perdidas = bits_err = bits_cmp = 0
    inicio = time.monotonic()
    try:
        for i in range(tramas):
            carga = os.urandom(tam)
            esperada = Trama(destino=DIFUSION, origen=faro.direccion, carga=carga,
                             seq=i & 0xFF).a_bytes()
            faro._emitir(esperada)
            try:
                recibida = faro._eco.get(timeout=espera_s)
            except queue.Empty:
                recibida = None
            if recibida is None or len(recibida) != len(esperada):
                perdidas += 1
            else:
                errores = sum(bin(a ^ b).count("1") for a, b in zip(recibida, esperada))
                bits_err += errores
                bits_cmp += 8 * len(esperada)
                if errores == 0:
                    ok += 1
                else:
                    crc_malo += 1
            if al_avanzar:
                al_avanzar(i + 1, ok, crc_malo, perdidas)
    finally:
        faro.loopback = False
        faro._decod.reiniciar()
    segundos = time.monotonic() - inicio
    return {
        "tramas": tramas, "ok": ok, "con_errores": crc_malo, "perdidas": perdidas,
        "bits_erroneos": bits_err, "bits_comparados": bits_cmp,
        "ber": (bits_err / bits_cmp) if bits_cmp else None,
        "segundos": segundos,
        "tasa_efectiva_bps": ok * tam * 8 / segundos if segundos else 0.0,
        "bps": faro.bps,
    }
